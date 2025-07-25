import os
import subprocess
from pathlib import Path

import numpy as np
import xarray
from loguru import logger

from workflow_tools.io import HSMGet, write_ds
from workflow_tools.spear import SPEAR_ROOT, get_spear_paths
from workflow_tools.utils import pad_ds

hsmget = HSMGet(archive=SPEAR_ROOT)


def get_files_to_extract(ystart: int, mstart: int, ens: int) -> list[Path]:
    files = get_spear_paths(
        ['slp', 't_ref', 'q_ref', 'lwdn_sfc', 'swdn_sfc', 'precip'],
        ystart,
        mstart,
        'atmos_daily',
        'daily',
        ens=ens,
    )
    files += get_spear_paths(
        ['u_ref', 'v_ref'], ystart, mstart, 'atmos_4xdaily', '6hr', ens=ens
    )
    return files


def write_atmos(
    ystart: int,
    mstart: int,
    ens: int,
    work_dir: Path,
    lat_slice,
    lon_slice,
    rerun: bool = False
) -> None:
    out_dir = work_dir / f'{ystart}-{mstart:02d}-e{ens:02d}'
    if rerun or not out_dir.is_dir():
        # Read mask for flooding
        static = xarray.open_dataset('/work/acr/spear/atmos.static.nc')
        is_ocean = np.invert(static.land_mask.astype('bool'))
        logger.info('extract from archive or ptmp')
        extracted_files = hsmget(get_files_to_extract(ystart, mstart, ens))
        logger.info('pad and save')
        tmpdir = (
            Path(os.environ['TMPDIR'])
            / 'atmos_raw'
            / f'{ystart}-{mstart:02d}-e{ens:02d}'
        )
        tmpdir.mkdir(exist_ok=True, parents=True)
        for f in extracted_files:
            logger.info('    ' + str(f))
            # open
            ds = xarray.open_dataset(f).sel(lat=lat_slice, lon=lon_slice)
            # Need to mask just the variable of interest and not the
            # coordinate/metadata variables
            main_var = next(x for x in ds.data_vars if len(ds[x].dims) == 3)
            ds[main_var] = ds[main_var].where(is_ocean)
            padded = pad_ds(ds)
            fout = tmpdir / f.name
            write_ds(padded, fout)
            # cdo doesn't like if the input is also the output here
            subprocess.run(
                [
                    f'cdo -O replace {fout} -setmisstodis,3 -selvar,{main_var} {fout} {fout}.new'  # noqa: E501
                ],
                shell=True,
                check=True,
            )
            # Rename the file generated by cdo to the output file
            fout.with_suffix(fout.suffix + '.new').rename(fout)

        logger.info('vftmp -> work')
        out_dir.mkdir(exist_ok=True)
        subprocess.run([f'gcp {tmpdir}/atmos*.nc {out_dir}'], shell=True, check=True)
    else:
        logger.warning(f'Already found data for {out_dir.as_posix()}')


def write_atmos_all_members(
    ystart: int,
    mstart: int,
    nens: int,
    work_dir: Path,
    lat_slice,
    lon_slice,
    rerun: bool = False
) -> None:
    # Read mask for flooding
    static = xarray.open_dataset('/work/acr/spear/atmos.static.nc')
    is_ocean = np.invert(static.land_mask.astype('bool'))
    members = {}
    for ens in range(1, nens + 1):
        out_dir = work_dir / f'{ystart}-{mstart:02d}-e{ens:02d}'
        if rerun or not out_dir.is_dir():
            members.update({ens: get_files_to_extract(ystart, mstart, ens)})

    if len(members) == 0:
        return None

    # dmget everything at once instead of separately by member
    # to reduce the change of dmget failing
    logger.info(f' dmget {len(members)} members')
    all_file_strs = ' '.join(x.as_posix() for x in sum(members.values(), []))  # noqa: RUF017
    subprocess.run(['dmget ' + all_file_strs], shell=True, check=True)
    tmpdir = (
        Path(os.environ['TMPDIR']) / 'atmos_raw' / f'{ystart}-{mstart:02d}-e{ens:02d}'
    )
    tmpdir.mkdir(exist_ok=True, parents=True)

    for ens, source_files in members.items():
        logger.info(f'---{ens:02d}---')
        logger.info('extract from archive or ptmp')
        extracted_files = hsmget(source_files)
        logger.info('pad and save')
        out_dir = work_dir / f'{ystart}-{mstart:02d}-e{ens:02d}'
        for f in extracted_files:
            logger.info('    ' + str(f))
            ds = xarray.open_dataset(f).sel(lat=lat_slice, lon=lon_slice)
            # Need to mask just the variable of interest and not the
            # coordinate/metadata variables
            main_var = next(x for x in ds.data_vars if len(ds[x].dims) == 3)
            ds[main_var] = ds[main_var].where(is_ocean)
            padded = pad_ds(ds)
            fout = tmpdir / f.name
            write_ds(padded, fout)
            # cdo doesn't like if the input is also the output here
            subprocess.run(
                [
                    f'cdo -O replace {fout} -setmisstodis,3 -selvar,{main_var} '
                    f'{fout} {fout}.new'
                ],
                shell=True,
                check=True,
            )
            # Rename the file generated by cdo to the output file
            fout.with_suffix(fout.suffix + '.new').rename(fout)
            logger.info('vftmp -> work')
            out_dir.mkdir(exist_ok=True)
            subprocess.run(
                [f'gcp {tmpdir}/atmos*.nc {out_dir}'], shell=True, check=True
            )


if __name__ == '__main__':
    import argparse

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-y', '--year', type=int)
    parser.add_argument('-m', '--month', type=int)
    parser.add_argument('-n', '--new', action='store_true')
    parser.add_argument(
        '-e',
        '--ensemble',
        type=int,
        default=-1,
        help='Ensemble member to extract \
            (default -1 extracts all members set by config)',
    )
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument(
        '-r',
        '--rerun',
        action='store_true',
        help='Write even if the files for this run already exist',
    )
    args = parser.parse_args()
    config = load_config(args.config)
    # Note conversion from [-180, 180] to [0, 360]
    xslice = slice(config.domain.west_lon % 360, config.domain.east_lon % 360)
    yslice = slice(config.domain.south_lat, config.domain.north_lat)
    work_dir = config.filesystem.forecast_input_data / 'atmos'
    work_dir.mkdir(exist_ok=True)

    if args.ensemble == -1:
        nens = config.new_forecasts.ensemble_size if args.new \
            else config.retrospective_forecasts.ensemble_size
        write_atmos_all_members(
            args.year, args.month, nens, work_dir, yslice, xslice, rerun=args.rerun
        )
    elif args.ensemble > 0:
        write_atmos(
            args.year,
            args.month,
            args.ensemble,
            work_dir,
            yslice,
            xslice,
            rerun=args.rerun,
        )
