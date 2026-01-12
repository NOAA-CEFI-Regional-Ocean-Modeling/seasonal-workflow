import xarray
from loguru import logger

from workflow_tools.utils import modulo, smooth_climatology


def write_boundary(ystart, yend, pathin, pathout, n_segments):
    for var in ['zos', 'thetao', 'so', 'uv']:
        for segment in range(1, n_segments + 1):
            logger.info(f'{var} {segment}')
            boundary = xarray.open_dataset(pathin / f'{var}_{segment:03d}.nc')
            boundary = boundary.sel(time=slice(str(ystart), str(yend)))
            # To be sure
            assert int(boundary['time.year'].min()) == ystart
            assert int(boundary['time.year'].max()) == yend
            if var == 'uv':
                vardata = boundary[
                    [f'u_segment_{segment:03d}', f'v_segment_{segment:03d}']
                ]
            else:
                vardata = boundary[f'{var}_segment_{segment:03d}']
            ave = (
                vardata.groupby('time.dayofyear')
                .mean('time')
                .sel(dayofyear=slice(1, 365))
            )
            smoothed = smooth_climatology(ave).rename({'dayofyear': 'time'})

            encoding = {
                'time': {'_FillValue': 1.0e20},
                f'lon_segment_{segment:03d}': {
                    'dtype': 'float64',
                    '_FillValue': 1.0e20,
                },
                f'lat_segment_{segment:03d}': {
                    'dtype': 'float64',
                    '_FillValue': 1.0e20,
                },
                f'{var}_segment_{segment:03d}': {'_FillValue': 1.0e20},
            }

            if var == 'zos':
                # zos doesn't have z coordinates to worry about
                res = smoothed.to_dataset()
            else:
                # z coordinates don't really vary in time.
                # Use the first coord and expand over time.
                # do it for both u and v if it is a velocity file.
                if var == 'uv':
                    z = (
                        boundary[
                            [
                                f'dz_u_segment_{segment:03d}',
                                f'dz_v_segment_{segment:03d}',
                            ]
                        ]
                        .isel(time=0)
                        .drop('time')
                        .expand_dims(time=365)
                    )
                    encoding = {
                        'time': {'_FillValue': 1.0e20},
                        f'lon_segment_{segment:03d}': {
                            'dtype': 'float64',
                            '_FillValue': 1.0e20,
                        },
                        f'lat_segment_{segment:03d}': {
                            'dtype': 'float64',
                            '_FillValue': 1.0e20,
                        },
                        f'u_segment_{segment:03d}': {'_FillValue': 1.0e20},
                        f'v_segment_{segment:03d}': {'_FillValue': 1.0e20},
                    }
                else:
                    z = (
                        boundary[f'dz_{var}_segment_{segment:03d}']
                        .isel(time=0)
                        .drop('time')
                        .expand_dims(time=365)
                    )

                z['time'] = smoothed['time']
                res = xarray.merge([smoothed, z])

            for coord in ['lat', 'lon']:
                fullcoord = f'{coord}_segment_{segment:03d}'
                if fullcoord not in res:
                    res[fullcoord] = boundary[fullcoord]

            res = modulo(res)
            res.to_netcdf(
                pathout / f'{var}_c_{segment:01d}.nc',
                format='NETCDF3_64BIT',
                engine='netcdf4',
                encoding=encoding,
                unlimited_dims='time',
            )


if __name__ == '__main__':
    import argparse

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config')
    args = parser.parse_args()
    config = load_config(args.config)
    first_year = config.climatology.first_year
    last_year = config.climatology.last_year
    pathin = config.filesystem.open_boundary_files
    pathout = (
        config.filesystem.forecast_input_data
        / 'boundary'
        / f'climatology_{first_year}_{last_year}'
    )
    pathout.mkdir(exist_ok=True, parents=True)
    n_seg = len(config.domain.boundaries)
    write_boundary(first_year, last_year, pathin, pathout, n_segments=n_seg)
