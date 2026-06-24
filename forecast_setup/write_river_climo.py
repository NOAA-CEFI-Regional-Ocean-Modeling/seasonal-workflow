from pathlib import Path

import numpy as np
import xarray
from loguru import logger

from workflow_tools.utils import modulo, smooth_climatology


def process_climatology(
    years: np.ndarray, input_files: list[Path], output_dir: Path
) -> None:
    logger.info('Opening dataset')
    rivers = xarray.open_mfdataset(
        input_files,
        preprocess=lambda x: x.isel(
            time=slice(1, -1)
        ),  # skip padded days (both ends are padded in glofas v4)
    )
    vardata = rivers.runoff
    logger.info('Calculating climatology by day')
    ave = (
        vardata.groupby('time.dayofyear')
        .mean('time')
        .sel(dayofyear=slice(1, 365))
        .load()
    )
    logger.info('Smoothing daily climatology')
    smoothed = smooth_climatology(ave).rename({'dayofyear': 'time'}).load()
    logger.info('Preparing to write')
    smoothed = modulo(smoothed)
    # time gets inserted when using open_mfdataset
    res = rivers[['area', 'lat', 'lon']].isel(time=0).drop_vars('time')
    # add smoothed result to res
    res['runoff'] = smoothed
    output_fname = output_dir / f'glofas_runoff_climo_{years[0]:d}_{years[-1]:d}.nc'
    logger.info('Writing to {f}', f=output_fname)
    res.to_netcdf(output_fname, unlimited_dims='time')


if __name__ == '__main__':
    import argparse

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', required=True)
    args = parser.parse_args()
    config = load_config(args.config)

    years = np.arange(config.climatology.first_year, config.climatology.last_year + 1)
    input_files = [
        Path(config.filesystem.yearly_river_files.format(year=y)) for y in years
    ]
    logger.info('Using input files: \n' + '\n'.join(map(str, input_files)))
    work_dir = config.filesystem.forecast_input_data / 'rivers'
    logger.info('Will write results to: {work_dir}', work_dir=work_dir)
    work_dir.mkdir(exist_ok=True)
    process_climatology(years, input_files, work_dir)
