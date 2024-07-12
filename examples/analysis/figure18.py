import cartopy.crs as ccrs
import datetime as dt
from filecmp import cmp as compare_file
from glob import glob
from matplotlib import colormaps
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from shutil import copyfile
import xarray


# Save data that is being used in the plots here
# for uploading to Zenodo
data_out_dir = Path('/work/acr/mom6/nwa12/published_data/gmd_2024')

def log_open_dataset(src_name, make_copy=True, copy_to=data_out_dir, **kwargs):
    """
    Wrap xarray.open_dataset with the addition of printing
    information about the last modified time of the file being opened.
    If make_copy=True, the file being opened is also copied
    to data_out_dir if it doesn't exist there or 
    the file is there but different.
    """
    if isinstance(src_name, str):
        src_name = Path(src_name)
    # https://stackoverflow.com/a/52858040
    modtime = dt.datetime.fromtimestamp(src_name.stat().st_mtime, tz=dt.timezone.utc)
    print(f'Loading {src_name.as_posix()}')
    print(f'  Modified {modtime.strftime("%Y-%m-%d %H:%M")}')
    if make_copy:
        dst_name = copy_to / src_name.name
        if not dst_name.exists() or not compare_file(src_name, dst_name):
            if dst_name.exists():
                print(f'  OVERWRITING to {data_out_dir.as_posix()}')
            else:
                print(f'  Copying to {data_out_dir.as_posix()}')
            copyfile(src_name, dst_name)
    return xarray.open_dataset(src_name, **kwargs)


def log_open_mfdataset(wildcard_or_filenames, **kwargs):
    """
    Similar to log_open_dataset, wraps xarray.open_mfdataset but only prints the last modified times
    as long as the argument being passed is a string.
    """
    if isinstance(wildcard_or_filenames, str):
        files = list(glob(wildcard_or_filenames))
        for f in files:
            filename = Path(f)
            modtime = dt.datetime.fromtimestamp(filename.stat().st_mtime, tz=dt.timezone.utc)
            print(f'Loading {filename.as_posix()}')
            print(f'  Modified {modtime.strftime("%Y-%m-%d %H:%M")}')
    return xarray.open_mfdataset(wildcard_or_filenames, **kwargs)


# X and Y coords of points to plot T/S diagrams for
# (in model space
xs = [-66.4, -59]
ys = [42.4, 43.5]

# layer z levels to plot on T/S plots 
zlevels = [2.5, 32.5,  75, 105]

# Colormap to use for lines in T/S plots
cmap = colormaps['rainbow_r']
nlev = len(zlevels)
cols = list(cmap(np.linspace(0, 1, nlev)))

# Markers to use for certain months on T/S plots
markers = ['+', 'o', 's']

# Plot forecast values in this slice of time
timeslice = slice('2020-09-01', '2021-02-01')

# Map projection
PC = ccrs.PlateCarree()

# Common options for SST maps
temp_common = dict(vmin=-4, vmax=4, cmap='coolwarm')

# Common options for SSH maps
ssh_common = dict(vmin=-0.8, vmax=0.8, cmap='seismic')
static = xarray.open_dataset('/archive/acr/mom6_input/nwa12/ocean_static.nc')

print('Loading 2D and 3D forecast data')
members = log_open_mfdataset('/work/acr/mom6/nwa12/raw_forecasts/20200901.e??.ocean_month_z.nc', combine='nested', concat_dim='member')
# Temperature and salinity forecast values at points
forecast = members[['so', 'thetao']].sel(xh=xs, yh=ys, method='nearest').sel(time=timeslice, z_l=zlevels).load()
# Ensemble mean of forecast values at points
ensmean = forecast.mean('member')
members_2d = log_open_mfdataset('/work/acr/mom6/nwa12/raw_forecasts/20200901.e??.ocean_month.nc', combine='nested', concat_dim='member')
zosmean = members_2d['zos'].mean('member').load()
tosmean = members_2d['tos'].mean('member').load()
zosmean.to_netcdf(data_out_dir / '20200901.ensmean.zos.nc')

# Forecast at points
ft = ensmean.thetao.sel(z_l=slice(0, 150)).load()
fs = ensmean.so.sel(z_l=slice(0, 150)).load()
ft.to_netcdf(data_out_dir / '20200901.ensmean.thetao_points.nc')
fs.to_netcdf(data_out_dir / '20200901.ensmean.so_points.nc')

print('Loading forecast climatology')
forecast_climo = log_open_dataset('/work/acr/mom6/nwa12/processed_forecasts/climo_monthlymean_i9.nc', make_copy=False).squeeze()
# Use time as dimension instead of lead. 
# Borrow time from the SST forecasts above.
forecast_climo['time'] = (('lead', ), tosmean.time.data)
forecast_climo = forecast_climo.swap_dims({'lead': 'time'})
tosanom = tosmean - forecast_climo.tos
tosanom.to_netcdf(data_out_dir / '20200901.ensmean.tos_anom.nc')

print('Plotting forecast figure')
fig = plt.figure(figsize=(11, 8))
gs = gridspec.GridSpec(4, 5, hspace=.25, wspace=0.25, width_ratios=[1, 1, 1, 1, 0.2])
axs = [fig.add_subplot(gs[i, j], projection=PC) for i in range(2) for j in range(4)]

ax = axs[0]
ax.pcolormesh(static.geolon_c, static.geolat_c, tosanom.sel(time='2020-9').squeeze(), **temp_common)
ax.set_title('Sep 2020')
for i, (x, y) in enumerate(zip(xs, ys)):
    ax.scatter(x, y, c='k', s=8, marker='x')
    ax.text(x, y, f' {i+1}',  fontsize=8)
    
ax = axs[1]
ax.pcolormesh(static.geolon_c, static.geolat_c, tosanom.sel(time='2020-10').squeeze(), **temp_common)
ax.set_title('Oct 2020')

ax = axs[2]
ax.pcolormesh(static.geolon_c, static.geolat_c, tosanom.sel(time='2020-11').squeeze(), **temp_common)
ax.set_title('Nov 2020')

ax = axs[3]
p = ax.pcolormesh(static.geolon_c, static.geolat_c, tosanom.sel(time='2020-12').squeeze(), **temp_common)
ax.set_title('Dec 2020')

cbax = fig.add_subplot(gs[0, 4])
cb = plt.colorbar(p, cax=cbax, extend='both')
cb.set_label('T anom. (°C)', rotation=270, labelpad=10.7)

ax = axs[4]
ax.pcolormesh(static.geolon_c, static.geolat_c, zosmean.sel(time='2020-9').squeeze(), **ssh_common)
ax.contour(static.geolon, static.geolat, forecast_climo.zos.sel(time='2020-9').squeeze(), colors='k', levels=[0])
ax.set_title('Sep 2020')

ax = axs[5]
ax.pcolormesh(static.geolon_c, static.geolat_c, zosmean.sel(time='2020-10').squeeze(), **ssh_common)
ax.contour(static.geolon, static.geolat, forecast_climo.zos.sel(time='2020-10').squeeze(), colors='k', levels=[0])
ax.set_title('Oct 2020')

ax = axs[6]
ax.pcolormesh(static.geolon_c, static.geolat_c, zosmean.sel(time='2020-11').squeeze(), **ssh_common)
ax.contour(static.geolon, static.geolat, forecast_climo.zos.sel(time='2020-11').squeeze(), colors='k', levels=[0])
ax.set_title('Nov 2020')

ax = axs[7]
p = ax.pcolormesh(static.geolon_c, static.geolat_c, zosmean.sel(time='2020-12').squeeze(), **ssh_common)
ax.contour(static.geolon, static.geolat, forecast_climo.zos.sel(time='2020-12').squeeze(), colors='k', levels=[0])
ax.set_title('Dec 2020')

cbax = fig.add_subplot(gs[1, 4])
cb = plt.colorbar(p, cax=cbax)
cb.set_label('SSH (m)', rotation=270, labelpad=10.7)

for ax in axs:
    ax.set_extent([-76, -48, 33, 50])

# Two bigger T/S plots at bottom
axs = [
    fig.add_subplot(gs[2:4, 0:2]),
    fig.add_subplot(gs[2:4, 2:4])
]
for i, (xh, yh, ax) in enumerate(zip(ft.xh, ft.yh, axs)):
    for c, z in zip(cols, zlevels):
        x = fs.sel(time=timeslice, xh=xh, yh=yh, z_l=z)
        y = ft.sel(time=timeslice, xh=xh, yh=yh, z_l=z)
        ax.plot(x, y, c=c, label=z)
        ax.set_title(f'[{i+1}]')
        if i in [0, 2]:
            ax.set_ylabel('Potential temperature (°C)')
        if i in [0]:
            ax.set_xlim(32, 35)
            ax.set_ylim(6, 20)
        elif i in [1]:
            ax.set_xlim(31.8, 36)
            ax.set_ylim(6, 20)
            ax.text(36, 16, 'GS', horizontalalignment='center')
        ax.set_xlabel('Salinity')
        for ind, marker in zip([0, 1, 3], markers):
            ax.plot(x[ind], y[ind], color=c, marker=marker)

fig.subplots_adjust(right=0.8)

# Make a custom legend for depth            
handles = []
for c in cols:
    handles.append(Line2D([0], [0], color=c))
l1 = plt.legend(handles, zlevels, frameon=False, title='Depth:', bbox_to_anchor=(0.4, 0.1, 1, 1), loc='upper right')

# Make a custom legend for month
handles = []
for shp in markers:
    handles.append(Line2D([0], [0], color='#999999', marker=shp))
labels = ['Sep', 'Oct', 'Dec']
plt.legend(handles, labels, frameon=False, title='Time:', bbox_to_anchor=(0.4, -0.4, 1, 1), loc='upper right')
ax.add_artist(l1)

fig.suptitle('Downscaled forecasts for late 2020', fontweight='bold', y=0.96)
plt.savefig('figures/forecast_warm_intrusion.png', dpi=200, bbox_inches='tight')





