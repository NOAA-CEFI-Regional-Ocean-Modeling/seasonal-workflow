from calendar import month_name
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import xarray
from cartopy.mpl.geoaxes import GeoAxes
from loguru import logger
from matplotlib.colors import ListedColormap
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from mpl_toolkits.axes_grid1 import AxesGrid

HERE = Path(__file__).resolve().parent
plt.rcParams['font.sans-serif'] = 'Cantarell'

states = cfeature.NaturalEarthFeature(
    category='cultural',
    name='admin_1_states_provinces_lines',
    scale='10m',
    facecolor='none',
    edgecolor='k',
)

countries = cfeature.NaturalEarthFeature(
    category='cultural',
    name='admin_0_countries',
    scale='10m',
    facecolor='none',
    edgecolor='k',
)

titles = {1: 'Jan-Feb-Mar', 4: 'Apr-May-Jun', 7: 'Jul-Aug-Sep', 10: 'Oct-Nov-Dec'}

cool = ListedColormap(['#4575b4'])
near = ListedColormap(['#f3d90a'])
warm = ListedColormap(['#d73027'])
uncertain = ListedColormap(['#c8c8c8'])


def sigma(x):
    return 1 / (1 + np.exp(-x))


def main(static, forecasts, coefs, quantiles, year, month):
    logger.info(
        'Generating forecast graphics for {year}-{month:02d}', year=year, month=month
    )
    seasonal_ensmean = (
        forecasts.mean('member')
        .where(static.deptho < 500)
        .groupby_bins(
            'lead', [0, 2, 5, 8, 11], include_lowest=True, labels=[0, 3, 6, 9]
        )
        .mean()
        .rename({'lead_bins': 'lead'})
    )
    valid_month = int(seasonal_ensmean.init.month) + seasonal_ensmean.lead
    valid_month = ((valid_month - 1) % 12) + 1

    qs = quantiles.sel(month=valid_month)
    match_coefs = coefs.sel(month=int(forecasts['init.month']))

    # Prob of not exceeding low tercile
    plow = 1 - sigma(
        match_coefs['intercept']
        + match_coefs['b1'] * seasonal_ensmean
        + match_coefs['b2'] * qs.sel(quantile=0.33)
    )

    # Prob of exceeding high tercile
    phigh = sigma(
        match_coefs['intercept']
        + match_coefs['b1'] * seasonal_ensmean
        + match_coefs['b2'] * qs.sel(quantile=0.67)
    )

    # Prob of exceeding low tercile (1 - plow)
    # but excluding the prob of exceeding high tercile
    pmid = (1 - plow) - phigh

    # Combine the probabilities together into one dataarray
    cat = xarray.concat(
        [plow, pmid, phigh], dim='category', coords='minimal', compat='override'
    )
    cat['category'] = np.arange(len(cat['category']))

    # Find the highest probability and the category that probability is in
    max_prob = cat.max('category')
    max_cat = cat.idxmax('category', skipna=True)

    logger.info('Figure 1')
    fig = plt.figure(figsize=(10, 8))
    grid = AxesGrid(
        fig,
        111,
        nrows_ncols=(2, 2),
        axes_class=(GeoAxes, {'projection': ccrs.PlateCarree()}),
        axes_pad=0.29,
        cbar_location='bottom',
        label_mode='keep',
    )
    for i, ax in enumerate(grid):
        ax.add_feature(
            countries, zorder=1, linewidth=1, edgecolor='#9999a0', facecolor='#efefed'
        )
        ax.add_feature(states, zorder=1, linewidth=0.5, edgecolor='#9999a0')
        ax.add_feature(cfeature.LAKES, zorder=100, linewidth=0.5, color='#9999a0')
        ax.add_feature(cfeature.OCEAN, zorder=0, linewidth=0.5, color='#ffffff')
        prob = max_prob.isel(lead=i)
        conf = prob.where(prob >= 0.5)
        i_cat = max_cat.isel(lead=i)
        # Uncertain
        ax.pcolormesh(
            static.geolon_c,
            static.geolat_c,
            xarray.ones_like(prob).where(prob < 0.5),
            cmap=uncertain,
        )
        # Plot where cold most likely
        ax.pcolormesh(
            static.geolon_c, static.geolat_c, conf.where(i_cat == 0), cmap=cool
        )
        # Plot where normal most likely
        ax.pcolormesh(
            static.geolon_c, static.geolat_c, conf.where(i_cat == 1), cmap=near
        )
        # Plot where warm most likely
        ax.pcolormesh(
            static.geolon_c, static.geolat_c, conf.where(i_cat == 2), cmap=warm
        )
        mon = int(valid_month.isel(lead=i))
        yr = year + 1 if mon < month else year
        ax.set_title(f'{titles[mon]} {yr}', pad=6)
        ax.set_extent([-99.5, -55, 17.2, 44.4])
        for s in ax.spines.values():
            s.set_visible(False)
    fig.suptitle(
        'Experimental probabilistic bottom temperature forecast',
        y=0.945,
        fontweight='bold',
        fontsize=16,
    )
    fig.text(
        0.5,
        0.89,
        f'MOM6-NWA12 model initialized {month_name[month][0:3]} 1 {year}',
        fontsize=14,
        ha='center',
    )
    img = mpimg.imread(HERE / 'NOAA-Transparent-Logo_1.png')
    imagebox = OffsetImage(img, zoom=0.2, alpha=1)
    ab = AnnotationBbox(
        imagebox,
        (0.785, 0.79),
        xycoords='figure fraction',
        box_alignment=(1.0, -0.0),  # Adjust padding
        frameon=False,
    )
    grid[-1].add_artist(ab)
    fig.subplots_adjust(bottom=0.15)
    fig.text(
        0.13,
        0.135,
        'Most likely bottom temperature relative to 1994-2023 average: ',
        fontsize=14,
        color='k',
        ha='left',
        va='center',
    )
    fig.text(
        0.69,
        0.17,
        'Warmer than average',
        fontsize=14,
        color=warm.colors[0],
        ha='left',
        va='center',
    )
    fig.text(
        0.69,
        0.14,
        'Near average',
        fontsize=14,
        color=near.colors[0],
        ha='left',
        va='center',
    )
    fig.text(
        0.69,
        0.11,
        'Cooler than average',
        fontsize=14,
        color=cool.colors[0],
        ha='left',
        va='center',
    )
    fig.text(
        0.69, 0.08, 'Uncertain', fontsize=14, color='#bbbbbb', ha='left', va='center'
    )

    plt.savefig(
        HERE / 'figures' / f'forecast_tob_prob_us_{year}{month:02d}.png',
        dpi=200,
        bbox_inches='tight',
    )
    plt.close()


if __name__ == '__main__':
    import argparse

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-y', '--year', type=int, required=True)
    parser.add_argument('-m', '--month', type=int, required=True)
    args = parser.parse_args()
    config = load_config(args.config)

    static = xarray.open_dataset(config.domain.ocean_static_file)
    output_dir = config.filesystem.forecast_output_data / 'individual'
    fname = config.filesystem.combined_name.format(
        freq='monthly', var='tob', year=args.year, month=args.month
    )
    forecasts = xarray.open_dataset(output_dir / fname)['tob']
    # Pre-calculated coefficients for logistic regression
    ppp_path = config.filesystem.forecast_output_data / 'post_post_processed'
    coefs = xarray.open_dataset(ppp_path / 'logreg_coefs_forecast_seasonal_tob.nc')
    # Quantile values from GLORYS
    glorys_qs = (
        xarray.open_dataarray(ppp_path / 'logreg_quantiles_glorys_seasonal_tob.nc')
        .sel(quantile=[0.33, 0.67])  # just the tercile boundaries
        .load()
    )

    main(static, forecasts, coefs, glorys_qs, args.year, args.month)
