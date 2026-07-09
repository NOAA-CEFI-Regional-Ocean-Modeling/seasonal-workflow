from calendar import month_name

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import colormaps as cmaps
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import xarray
from cartopy.mpl.geoaxes import GeoAxes
from custom_colors import smooth_anomaly_cmap
from loguru import logger
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from mpl_toolkits.axes_grid1 import AxesGrid

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


def main(static, forecasts, glorys, year, month):  # noqa: PLR0915
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
    logger.info('Computing GLORYS climatology for bias correction')
    glorys_clim = (
        glorys.sel(time=slice('1994', '2023'))
        .groupby_bins(
            'time.month', [1, 3, 6, 9, 12], include_lowest=True, labels=[1, 4, 7, 10]
        )
        .mean()
        .rename({'month_bins': 'month'})
    )
    year0 = int(seasonal_ensmean['init.year'])
    mon0 = int(seasonal_ensmean['init.month'])
    common = {'vmin': -4, 'vmax': 4, 'cmap': smooth_anomaly_cmap}
    logger.info('Figure 1: anomaly')
    fig = plt.figure(figsize=(10, 8))
    grid = AxesGrid(
        fig,
        111,
        nrows_ncols=(2, 2),
        axes_class=(GeoAxes, {'projection': ccrs.PlateCarree()}),
        axes_pad=0.38,
        cbar_location='bottom',
        cbar_mode='single',
        cbar_size='3%',
        label_mode='keep',
    )
    for ax in grid:
        ax.add_feature(
            countries, zorder=1, linewidth=1, edgecolor='#9999a0', facecolor='#dddde0'
        )
        ax.add_feature(states, zorder=1, linewidth=0.5, edgecolor='#9999a0')
    for i, ax in enumerate(grid):
        plot_data = seasonal_ensmean['tob_anom'].isel(lead=i).where(static.deptho < 500)
        h = ax.pcolormesh(static.geolon_c, static.geolat_c, plot_data, **common)
        mon = int(valid_month.isel(lead=i))
        yr = year0 + 1 if mon < mon0 else year0
        ax.set_title(f'{titles[mon]} {yr}', pad=6)
        ax.set_extent([-77, -60, 35, 46])
        for s in ax.spines.values():
            s.set_visible(False)
    cbar = grid.cbar_axes[0].colorbar(h, extend='both')
    cbar.ax.set_xlabel(
        'Bottom temperature anomaly (°C) relative to 1994-2023 average', fontsize=12
    )
    fig.suptitle(
        'Experimental ocean bottom temperature forecast',
        y=0.96,
        fontweight='bold',
        fontsize=16,
    )
    fig.text(
        0.5,
        0.91,
        f'MOM6-NWA12 model initialized {month_name[mon0][0:3]} 1 2026',
        fontsize=14,
        ha='center',
    )
    img = mpimg.imread('NOAA-Transparent-Logo_1.png')
    imagebox = OffsetImage(img, zoom=0.2, alpha=1)
    ab = AnnotationBbox(
        imagebox,
        (0.785, 0.79),
        xycoords='figure fraction',
        box_alignment=(1.0, -0.0),  # Adjust padding
        frameon=False,
    )
    grid[-1].add_artist(ab)
    plt.savefig(
        f'figures/forecast_tob_anom_neus_{year}{month:02d}.png',
        dpi=200,
        bbox_inches='tight',
    )
    plt.close()

    logger.info('Figure 2: value')
    common = {'vmin': 3, 'vmax': 23, 'cmap': cmaps.BlAqGrYeOrReVi200.discrete(20)}
    fig = plt.figure(figsize=(10, 8))
    grid = AxesGrid(
        fig,
        111,
        nrows_ncols=(2, 2),
        axes_class=(GeoAxes, {'projection': ccrs.PlateCarree()}),
        axes_pad=0.38,
        cbar_location='bottom',
        cbar_mode='single',
        cbar_size='3%',
        label_mode='keep',
    )
    for ax in grid:
        ax.add_feature(
            countries, zorder=1, linewidth=1, edgecolor='#9999a0', facecolor='#dddde0'
        )
        ax.add_feature(states, zorder=1, linewidth=0.5, edgecolor='#9999a0')
    custom_lines = [
        Line2D([0], [0], color=c, lw=lw, linestyle=ls)
        for c, ls, lw in zip(['k', '#333333'], [':', '-'], [1, 0.5], strict=False)
    ]
    for i, ax in enumerate(grid):
        mon = int(valid_month.isel(lead=i))
        yr = year0 + 1 if mon < mon0 else year0
        clim = glorys_clim.sel(month=mon)
        corrected = seasonal_ensmean['tob_anom'].isel(lead=i) + clim
        corrected = corrected.where(static.deptho < 500)
        h = ax.pcolormesh(static.geolon_c, static.geolat_c, corrected, **common)
        ax.contour(
            static.geolon,
            static.geolat,
            static.deptho,
            levels=[30, 150],
            colors=['k', '#333333'],
            linestyles=[':', '-'],
            linewidths=[1, 0.5],
        )
        ax.set_title(f'{titles[mon]} {yr}', pad=6)
        ax.set_extent([-77, -60, 35, 46])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.legend(
            custom_lines,
            ['30 m depth', '150 m depth'],
            loc='lower right',
            frameon=False,
        )
    cbar = grid.cbar_axes[0].colorbar(h, extend='both')
    cbar.ax.set_xlabel('3 month average bottom temperature (°C) ', fontsize=12)
    cbar.ax.set_xticks(range(3, 24, 2))
    fig.suptitle(
        'Experimental ocean bottom temperature forecast',
        y=0.96,
        fontweight='bold',
        fontsize=16,
    )
    fig.text(
        0.5,
        0.91,
        f'MOM6-NWA12 model initialized {month_name[mon0][0:3]} 1 2026',
        fontsize=14,
        ha='center',
    )
    imagebox = OffsetImage(img, zoom=0.2, alpha=1)
    ab = AnnotationBbox(
        imagebox,
        (0.785, 0.79),
        xycoords='figure fraction',
        box_alignment=(1.0, -0.0),  # Adjust padding
        frameon=False,
    )
    grid[-1].add_artist(ab)
    plt.savefig(
        f'figures/forecast_tob_value_neus_{year}{month:02d}.png',
        dpi=200,
        bbox_inches='tight',
    )


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
    forecasts = xarray.open_dataset(output_dir / fname)
    glorys = xarray.open_dataarray(
        config.filesystem.glorys_interpolated / 'glorys_tob.nc'
    )
    main(static, forecasts, glorys, args.year, args.month)
