import numpy as np
import pandas as pd
import xarray
from loguru import logger
from numba import jit, prange
from numpy.typing import NDArray

from workflow_tools.config import Config, load_config
from workflow_tools.utils import match_obs_to_forecasts


@jit(nogil=True)
def logreg_mle(
    X: NDArray[np.float64],  # noqa: N803
    y: NDArray[np.float64],
    tol: float = 1e-5,
    max_iter: int = 50
) -> NDArray[np.float64]:
    _n_samples, n_features = X.shape
    w = np.zeros(n_features)
    converged = False
    for _ in range(max_iter):
        # Store old parameters for convergence check
        w_old = w.copy()
        # Predicted probabilities
        sigmoid = 1 / (1 + np.exp(-X @ w))
        # Gradient of log-likelihood
        gradient = X.T @ (y - sigmoid)
        # Hessian matrix
        V = np.diag(sigmoid * (1 - sigmoid))  # noqa: N806
        hessian = -X.T @ V @ X
        # Make sure the matrix isn't singular
        # in a way that is friendly to numba.
        # https://stackoverflow.com/a/13270760
        if np.linalg.cond(hessian) < 1 / np.finfo(hessian.dtype).eps:
            # Update parameters
            w -= np.linalg.inv(hessian) @ gradient
            # Check convergence
            if np.sum(np.abs(w - w_old)) < tol:
                converged = True
                break
        else:
            # Singular matrix
            break
    if not converged:
        w *= np.nan
    return w


@jit(parallel=True, nogil=True)
def apply_logreg_mle(
    xd: NDArray[np.float64],
    qd: NDArray[np.float64],
    yd: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    # assuming dimensions are <init, lat, lon, quantile>
    ni, ny, nx, nq = qd.shape #noqa: RUF059
    a = np.full((ny, nx), np.nan)
    b = np.full((ny, nx), np.nan)
    c = np.full((ny, nx), np.nan)
    for y in prange(ny):
        for x in prange(nx):
            # Check for missing data; skip if any present (includes over land)
            if np.all(np.isfinite(xd[:, y, x])):
                # Conform value predictors to match quantile predictors
                x1 = np.repeat(xd[:, y, x], nq).reshape(-1, nq).flatten()
                # Intercepts
                x0 = np.ones_like(x1)
                # Flatten quantile predictors
                x2 = qd[:, y, x, :].flatten()
                # Combine to predictor matrix
                X = np.vstack((x0, x1, x2)).T  # noqa: N806
                # Flatten outcomes to match
                z = yd[:, y, x, :].flatten()
                # Make sure there are both possibilities in the data.
                if np.min(z) < 1 and np.max(z) > 0:
                    fit = logreg_mle(X, z)
                    a[y, x] = fit[0]
                    b[y, x] = fit[1]
                    c[y, x] = fit[2]
    return a, b, c


def main(config: Config, var: str, quantiles: list[float]) -> None:
    forecast_output_data = config.filesystem.forecast_output_data
    logger.info('Load forecasts')
    retro = xarray.open_dataset(
        forecast_output_data / f'forecasts_ocean_month_{var}.nc'
    )
    retro = retro.sel(
        init=slice('1994', '2022')
    )  # Limit forecasts used for regression to this time period.
    retro['valid_time'] = (
        ('lead', 'init'),
        [
            retro.indexes['init'] + pd.DateOffset(months=lead)
            for lead in retro['lead'].astype('int')
        ],
    )
    retro['valid_time'] = retro['valid_time'].transpose('init', 'lead')
    ensmean = retro[var].mean('member')

    glorys_rg = xarray.open_dataarray(
        config.filesystem.glorys_interpolated / f'glorys_{var}.nc'
    )
    qs_file = (
        forecast_output_data
        / 'post_post_processed'
        / f'logreg_quantiles_glorys_{var}.nc'
    )
    # Calculating quantiles is slow, so try to avoid it where possible
    if qs_file.is_file():
        glorys_qs = xarray.open_dataarray(
            qs_file
        ).load()  # exceeds memory if not loaded
    else:
        logger.info('Calculate quantiles from GLORYS')
        glorys_qs = glorys_rg.groupby('time.month').quantile(quantiles, dim='time')
        qs_file.parent.mkdir(exist_ok=True)
        glorys_qs.to_netcdf(qs_file)
    match_qs = glorys_qs.sel(month=retro['valid_time.month'])
    logger.info('Convert to binary exceedance')
    exceeded = (glorys_rg.groupby('time.month') > glorys_qs).astype('int')
    exceeded_match = match_obs_to_forecasts(exceeded, retro)

    logger.info('Logistic regression')
    all_coefs = []
    for mon in np.unique(retro.init.month):
        logger.trace(int(mon))
        all_leads = []
        for lead in np.unique(retro.lead):
            logger.trace(int(lead))
            ysub = exceeded_match.sel(
                lead=lead, init=exceeded_match['init.month'] == mon
            )
            xsub = ensmean.sel(lead=lead, init=ensmean['init.month'] == mon)
            qsub = match_qs.sel(lead=lead, init=match_qs['init.month'] == mon)
            yd = ysub.values
            xd = xsub.values
            qd = qsub.values
            intercept, b1, b2 = apply_logreg_mle(xd, qd, yd)
            coefs = xarray.Dataset(
                {
                    'intercept': (('yh', 'xh'), intercept),
                    'b1': (('yh', 'xh'), b1),
                    'b2': (('yh', 'xh'), b2),
                },
                coords={'yh': ysub.yh.values, 'xh': xsub.xh.values},
            ).squeeze()
            coefs['lead'] = lead
            coefs = coefs.set_coords('lead')
            all_leads.append(coefs)

        all_leads = xarray.concat(all_leads, dim='lead')
        all_leads['month'] = mon
        all_leads = all_leads.set_coords('month')
        all_coefs.append(all_leads)

    coefs = xarray.concat(all_coefs, dim='month')
    # This directory should already exist since it was used for the quantiles file above
    coefs.to_netcdf(
        forecast_output_data / 'post_post_processed' / f'logreg_coefs_forecast_{var}.nc'
    )


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-v', '--var', required=True)
    args = parser.parse_args()
    var = args.var
    config = load_config(args.config)
    # Currently hard coding quantiles.
    quantiles = [0.1, 0.33, 0.5, 0.67, 0.9]
    main(config, var, quantiles)
