import os
from pathlib import Path

import xarray
from loguru import logger

from workflow_tools.config import load_config
from workflow_tools.utils import smooth_climatology

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    args = parser.parse_args()
    config = load_config(args.config)
    tmp = Path(os.environ['TMPDIR'])

    model_output_data = config.filesystem.forecast_output_data
    model_output_data.mkdir(exist_ok=True)
    first_year = config.climatology.first_year
    last_year = config.climatology.last_year
    nens = config.retrospective_forecasts.ensemble_size

    members = []
    # Regular files: concatenate initializations together
    # Note: this will pull in new forecasts in addition to retrospective
    for e in range(1, nens + 1):
        logger.info(f'Member {e}')
        logger.info(model_output_data / 'extracted_region_average' / args.domain)
        files = sorted(
            (model_output_data / 'extracted_region_average' / args.domain).glob(
                f'????-??-e{e:02d}.{args.domain}.nc'
            )
        )
        if len(files) > 0:
            ds = xarray.open_mfdataset(files, decode_timedelta=False).load()
            ds['member'] = e
            members.append(ds)
            ds.close()

    logger.info('Concat by member')
    model_ds = xarray.concat(members, dim='member').sortby(
        'init'
    )  # sorting is important for slicing later
    model_ds = model_ds.drop_vars(
        ['ens', 'verif', 'mstart', 'ystart'], errors='ignore'
    ).load()
    logger.info('Ensemble mean and anomalies')
    ensmean = model_ds.mean('member')
    climo = (
        ensmean.sel(init=slice(f'{first_year}-01-01', f'{last_year}-12-31'))
        .groupby('init.month')
        .mean('init')
    )
    if 'daily' in args.domain:
        logger.info('Smoothing daily climatology')
        climo = smooth_climatology(climo, dim='lead')
    anom = model_ds.groupby('init.month') - climo
    anom = anom.rename({v: f'{v}_anom' for v in anom.data_vars})
    model_ds = xarray.merge([model_ds, anom])
    # Write the climatology, being sure that appropriate coords are ints.
    # Also trying to remove the empty dimension "time" from the output.
    # encoding = {v: {'dtype': 'int32'} for v in ['lead', 'month']}
    # climo.encoding = {}
    # logger.info('Writing climatology')
    # climo.to_netcdf(model_output_data /
    # f'climatology_{args.domain}_{args.var}_{first_year}_{last_year}.nc',
    #     encoding=encoding)
    # Do the same for the full set of forecasts
    encoding = {
        v: {'dtype': 'int32'} for v in ['lead', 'member', 'month'] if v in model_ds
    }
    logger.info('Writing forecasts')
    fname = f'forecasts_{args.domain}_regionmean.nc'
    model_ds.to_netcdf(model_output_data / fname, encoding=encoding)
