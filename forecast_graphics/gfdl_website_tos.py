from calendar import month_name
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import xarray
from cartopy.mpl.geoaxes import GeoAxes
from custom_colors import smooth_anomaly_cmap
from loguru import logger
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from mpl_toolkits.axes_grid1 import AxesGrid

HERE = Path(__file__).resolve().parent
plt.rcParams['font.sans-serif'] = 'Cantarell'

states_lo = cfeature.NaturalEarthFeature(
    category='cultural',
    name='admin_1_states_provinces_lines',
    scale='50m',
    facecolor='none',
    edgecolor='k',
)

countries_lo = cfeature.NaturalEarthFeature(
    category='cultural',
    name='admin_0_countries',
    scale='50m',
    facecolor='none',
    edgecolor='k',
)

titles = {1: 'Jan-Feb-Mar', 4: 'Apr-May-Jun', 7: 'Jul-Aug-Sep', 10: 'Oct-Nov-Dec'}


def main(static, forecasts, year, month):
    logger.info(
        'Generating forecast graphics for {year}-{month:02d}', year=year, month=month
    )
    seasonal_ensmean = (
        forecasts.mean('member')
        .groupby_bins(
            'lead', [0, 2, 5, 8, 11], include_lowest=True, labels=[0, 3, 6, 9]
        )
        .mean()
        .rename({'lead_bins': 'lead'})
    )
    valid_month = int(seasonal_ensmean.init.month) + seasonal_ensmean.lead
    valid_month = ((valid_month - 1) % 12) + 1
    logger.info('Figure 1: anomaly')
    common = {'vmin': -4, 'vmax': 4, 'cmap': smooth_anomaly_cmap}

    fig = plt.figure(figsize=(10, 8))
    grid = AxesGrid(
        fig,
        111,
        nrows_ncols=(2, 2),
        axes_class=(GeoAxes, {'projection': ccrs.PlateCarree()}),
        axes_pad=0.29,
        cbar_location='bottom',
        cbar_mode='single',
        cbar_size='3%',
        label_mode='keep',
    )
    for ax in grid:
        ax.set_facecolor('#dddde0')
        ax.add_feature(states_lo, zorder=1, linewidth=0.5, edgecolor='#9999a0')
        ax.add_feature(countries_lo, zorder=1, linewidth=0.5, edgecolor='#9999a0')
        ax.add_feature(cfeature.LAKES, zorder=0, linewidth=0.5, color='#9999a0')
        ax.add_feature(cfeature.OCEAN, zorder=0, linewidth=0.5, color='#9999a0')
    for i, ax in enumerate(grid):
        h = ax.pcolormesh(
            static.geolon_c,
            static.geolat_c,
            seasonal_ensmean['tos_anom'].isel(lead=i),
            **common,
        )
        mon = int(valid_month.isel(lead=i))
        yr = year + 1 if mon < month else year
        ax.set_title(f'{titles[mon]} {yr}', pad=6)
        ax.set_extent([-100, -34, 3, 56])
        for s in ax.spines.values():
            s.set_visible(False)
    cbar = grid.cbar_axes[0].colorbar(h, extend='both')
    cbar.ax.set_xlabel(
        'Sea surface temperature anomaly (°C) relative to 1994-2023 average',
        fontsize=12,
    )
    fig.suptitle(
        'Experimental ocean surface temperature forecast',
        y=0.97,
        fontweight='bold',
        fontsize=16,
    )
    fig.text(
        0.5,
        0.92,
        f'MOM6-NWA12 model initialized {month_name[month][0:3]} 1 {year}',
        fontsize=14,
        ha='center',
    )
    img = mpimg.imread(HERE / 'NOAA-Transparent-Logo_1.png')
    imagebox = OffsetImage(img, zoom=0.17, alpha=1)
    ab = AnnotationBbox(
        imagebox,
        (0.665, 0.845),
        xycoords='figure fraction',
        box_alignment=(1.0, -0.0),  # Adjust padding
        frameon=False,
    )
    grid[-1].add_artist(ab)
    plt.savefig(
        HERE / 'figures' / f'forecast_tos_anom_nwa12_{year}{month:02d}.png',
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
        freq='monthly', var='tos', year=args.year, month=args.month
    )
    forecasts = xarray.open_dataset(output_dir / fname)
    main(static, forecasts, args.year, args.month)
