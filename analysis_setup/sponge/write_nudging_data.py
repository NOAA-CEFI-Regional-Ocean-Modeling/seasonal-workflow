from pathlib import Path

import pandas as pd
import xarray
from xesmf import Regridder

from workflow_tools.grid import round_coords

VARIABLES = ['thetao', 'so']


def add_bounds(ds):
    # Add data points at end of month, since time_bnds aren't used
    # All points extend to 23:59:59 at end of month, except
    # for the end of the year which is padded to 00:00:00 the next Jan 1.
    # normalize=True rolls down to midnight
    mstart = [
        d - pd.offsets.MonthBegin(normalize=True) if d.day > 1 else d
        for d in ds['time'].to_pandas()
    ]
    mend = [
        d + pd.DateOffset(months=1)
        if d.month == 12
        else d + pd.DateOffset(months=1) - pd.Timedelta(seconds=1)
        for d in mstart
    ]
    starts = ds.copy()
    starts['time'] = mstart
    ends = ds.copy()
    ends['time'] = mend
    bounded = xarray.concat((starts, ends), dim='time').sortby('time')
    # Ensure that order is correct so that time can be unlimited dim
    bounded = bounded.transpose('time', 'depth', 'yh', 'xh')
    return bounded


def main(
    year: int, target_grid: xarray.Dataset, input_dir: Path, output_dir: Path
) -> None:
    files = list(input_dir.glob(f'glorys_*_{year}-??.nc'))
    glorys = (
        xarray.open_mfdataset(
            files, chunks='auto', preprocess=lambda x: round_coords(x, to=12)
        )  # without auto, chunks will be weird and loading will be slow
        .rename({'latitude': 'lat', 'longitude': 'lon'})
        .sel(depth=slice(None, 5300))[  # make sure empty last depth is excluded
            VARIABLES
        ]
    ).load()
    print('Interpolating')
    glorys_to_t = Regridder(
        glorys,
        target_grid,
        method='nearest_s2d',
        reuse_weights=False,  #! Not reusing
        periodic=False,
    )
    interped = glorys_to_t(glorys).drop_vars(['lon', 'lat'], errors='ignore').compute()
    bounded = add_bounds(interped)
    bounded['xh'] = (('xh',), target_grid.xh.data)
    bounded['yh'] = (('yh',), target_grid.yh.data)
    all_vars = list(bounded.data_vars.keys()) + list(bounded.coords.keys())
    encodings = {v: {'_FillValue': None} for v in all_vars}
    encodings['time'].update(
        {'dtype': 'float64', 'calendar': 'gregorian', 'units': 'days since 1993-01-01'}
    )
    bounded['depth'].attrs = {
        'units': 'meter',
        'cartesian_axis': 'Z',
        'positive': 'down',
    }
    bounded['time'].attrs['cartesian_axis'] = 'T'
    bounded['xh'].attrs = {'cartesian_axis': 'X'}
    bounded['yh'].attrs = {'cartesian_axis': 'Y'}
    print('Writing')
    bounded.to_netcdf(
        output_dir / f'glorys_sponge_monthly_bnd_{year}.nc',
        format='NETCDF3_64BIT',
        engine='netcdf4',
        encoding=encodings,
        unlimited_dims='time',
    )
    glorys.close()


if __name__ == '__main__':
    import argparse

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-y', '--year', type=int, required=True)
    parser.add_argument('-c', '--config', required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    static = xarray.open_dataset(config.domain.ocean_static_file)
    target_grid = static[['geolat', 'geolon']].rename(
        {'geolat': 'lat', 'geolon': 'lon'}
    )
    input_dir = config.filesystem.nowcast_input_data / 'sponge' / 'monthly_filled'
    output_dir = input_dir.parents[0]
    main(args.year, target_grid, input_dir, output_dir)
