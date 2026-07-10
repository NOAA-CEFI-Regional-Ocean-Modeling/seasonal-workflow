from calendar import month_name
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import xarray
from cartopy.mpl.geoaxes import GeoAxes
from custom_colors import smooth_anomaly_cmap
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


def main(static, forecasts):
    nlead = len(forecasts.lead)
    valid_month = int(forecasts.init.month) + forecasts.lead
    valid_month = ((valid_month - 1) % 12) + 1
    year0 = int(forecasts['init.year'])
    mon0 = int(forecasts['init.month'])

    for lead in range(nlead + 1):
        # Repeat the last frame so that the animation pauses at the end
        plot_lead = lead
        if plot_lead >= nlead:
            plot_lead = nlead - 1
        print(lead)
        fig = plt.figure(figsize=(10, 9.7))
        grid = AxesGrid(
            fig,
            111,
            nrows_ncols=(1, 1),
            axes_class=(GeoAxes, {'projection': ccrs.PlateCarree()}),
            axes_pad=0.3,
            cbar_location='bottom',
            cbar_mode='single',
            cbar_size='3%',
            label_mode='keep',
        )
        ax = grid[0]
        ax.set_facecolor('#dddde0')
        ax.add_feature(states_lo, zorder=1, linewidth=0.5, edgecolor='#9999a0')
        ax.add_feature(countries_lo, zorder=1, linewidth=0.5, edgecolor='#9999a0')
        ax.add_feature(cfeature.LAKES, zorder=0, linewidth=0.5, color='#9999a0')
        ax.add_feature(cfeature.OCEAN, zorder=0, linewidth=0.5, color='#9999a0')
        plot_data = forecasts.isel(lead=plot_lead)
        h = ax.pcolormesh(
            static.geolon_c,
            static.geolat_c,
            plot_data,
            vmin=-4,
            vmax=4,
            cmap=smooth_anomaly_cmap,
        )
        mon = int(valid_month.isel(lead=plot_lead))
        yr = year0 + 1 if mon < mon0 else year0
        ax.set_title(f'{month_name[mon]} {yr}', pad=6, fontsize=16)
        ax.set_extent([-100, -34, 3, 56])
        for s in ax.spines.values():
            s.set_visible(False)

        cbar = grid.cbar_axes[0].colorbar(h, extend='both')
        cbar.ax.set_xlabel(
            'Sea surface temperature anomaly (°C) relative to 1994-2023 average',
            fontsize=12,
        )

        fig.suptitle(
            'Experimental sea surface temperature forecast',
            y=0.96,
            fontweight='bold',
            fontsize=18,
        )
        fig.text(
            0.5,
            0.91,
            f'MOM6-NWA12 model initialized {month_name[mon0][0:3]} 1 2026',
            fontsize=16,
            ha='center',
        )

        plt.savefig(
            HERE / 'figures' / f'forecast_tos_anom_202604_frame_{lead:02d}.png',
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
    ensmean = forecasts['tos_anom'].mean('member')
    main(static, ensmean)
