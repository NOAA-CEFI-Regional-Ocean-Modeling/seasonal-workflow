"""
Can also do something like:
sbatch --export=ALL --wrap="python postprocess_extract_fields.py
    -c config_nwa12_physics.yaml -d ocean_daily -y 2019 -m 3
"""

import datetime as dt
import subprocess
from argparse import ArgumentParser, Namespace
from getpass import getuser
from os import environ
from pathlib import Path

import numpy as np
import xarray
from loguru import logger

from workflow_tools.config import load_config
from workflow_tools.forecast import ForecastRun


def process_file(
    forecast: ForecastRun,
    variables: list[str] | None = None,
    infile: Path | str | None = None,
    outfile: Path | str | None = None,
) -> None:
    if infile is None:
        infile = forecast.vftmp_dir / forecast.file_name
    if outfile is None:
        outfile = forecast.outdir / forecast.out_name
    logger.info(f'process_file({infile})')
    with xarray.open_dataset(infile, decode_timedelta=False) as ds:
        logger.trace('Opened {f}', f=infile)
        if variables is None:
            variables = list(ds.data_vars)
        dsv = ds[variables]
        logger.trace('Adding coordinates')
        dsv['member'] = int(forecast.ens)
        dsv['init'] = dt.datetime(int(forecast.ystart), int(forecast.mstart), 1)
        dsv['lead'] = (('time',), np.arange(len(dsv['time'])))
        if 'daily' in forecast.domain or len(dsv['lead']) > 12:
            dsv['lead'].attrs['units'] = 'days'
        else:
            dsv['lead'].attrs['units'] = 'months'
        logger.trace('Setting dims')
        dsv = dsv.swap_dims({'time': 'lead'}).set_coords(['init', 'member'])
        dsv = dsv.expand_dims('init')
        logger.trace('Transpose')
        dsv = dsv.transpose('init', 'lead', ...)
        dsv = dsv.drop_vars('time')
        dsv.attrs[f'cefi_archive_version_ens{forecast.ens:02d}'] = str(
            forecast.archive_dir.parent
        )
        # Compress output to significantly reduce space
        encoding = {var: {'zlib': True, 'complevel': 3} for var in variables}
        logger.trace('Starting writing to {f}', f=outfile)
        dsv.to_netcdf(outfile, unlimited_dims='init', encoding=encoding)
        logger.trace('Finished writing to {f}', f=outfile)


def process_run(
    forecast: ForecastRun,
    variables: list[str],
    rerun: bool = False,
    clean: bool = False,
) -> None:
    # Check if a processed file exists
    if not (forecast.outdir / forecast.out_name).is_file() or rerun:
        vftmp_file = forecast.vftmp_dir / forecast.file_name
        # Check if an extracted data file exists
        if vftmp_file.is_file():
            logger.trace('File {f} already exists on vftmp', f=vftmp_file)
            process_file(forecast, variables=variables)
        # Check if a cached tar file exists
        elif (forecast.ptmp_dir / forecast.file_name).is_file():
            logger.trace('File is not on vftmp but is on ptmp')
            forecast.copy_from_ptmp()
            process_file(forecast, variables=variables)
        elif forecast.exists:
            logger.trace('File is on archive but not on vftmp or ptmp')
            forecast.copy_from_archive()
            forecast.copy_from_ptmp()
            process_file(forecast, variables=variables)
        else:
            logger.info(
                f'{forecast.archive_dir / forecast.tar_file} not found; skipping.'
            )
            return
        if clean:
            logger.info('Cleaning file')
            vftmp_file.unlink()


def main(args: Namespace) -> None:
    config = load_config(args.config)
    if args.new:
        nens = config.new_forecasts.ensemble_size
        if args.year is None or args.month is None:
            raise Exception(
                'Must provide year and month for the new forecast to extract'
            )
        first_year = last_year = args.year
        months = [args.month]
    else:
        first_year = (
            args.year
            if args.year is not None
            else config.retrospective_forecasts.first_year
        )
        last_year = (
            args.year
            if args.year is not None
            else config.retrospective_forecasts.last_year
        )
        months = (
            [args.month]
            if args.month is not None
            else config.retrospective_forecasts.months
        )
        nens = config.retrospective_forecasts.ensemble_size
    outdir = config.filesystem.forecast_output_data / 'extracted' / args.domain
    outdir.mkdir(exist_ok=True, parents=True)
    variables = config.variables[args.domain]
    if args.tmp:
        vftmp = Path(environ['TMPDIR'])
    else:
        vftmp = Path('/vftmp') / getuser()
    all_runs = [
        ForecastRun(
            ystart=ystart,
            mstart=mstart,
            ens=ens,
            name=config.name,
            template=config.filesystem.forecast_history,
            domain=args.domain,
            outdir=outdir,
            vftmp=vftmp,
        )
        for ystart in range(first_year, last_year + 1)
        for mstart in months
        for ens in range(1, nens + 1)
    ]
    # Prefer to dmget all files that need it in one command, if possible.
    runs_to_dmget = []
    for run in all_runs:
        if not (run.outdir / run.out_name).is_file() or args.rerun:
            if run.needs_dmget:
                runs_to_dmget.append(run)  # (run.archive_dir / run.tar_file))

    # Try running one dmget command for all files.
    if len(runs_to_dmget) > 0:
        logger.info(f'dmgetting {len(runs_to_dmget)} files')
        file_names = [str(run.archive_dir / run.tar_file) for run in runs_to_dmget]
        dmget = subprocess.run(
            [f'dmget {" ".join(file_names)}'],
            shell=True,
            capture_output=True,
            text=True,
            check=True,
        )
        # If a tape is bad, the single dmget will fail.
        # Try running dmget separately for each individual file.
        # If the dmget fails, remove the run from the all_runs list
        # so that it is not extracted or worked on later.
        if dmget.returncode > 0:
            if 'unable to recall the requested file' in dmget.stderr:
                logger.warning('dmget failed. Running dmget separately for each file.')
                for run in runs_to_dmget:
                    try:
                        subprocess.run(
                            [f'dmget {run.archive_dir / run.tar_file}'],
                            shell=True,
                            check=True,
                        )
                    except subprocess.CalledProcessError:
                        logger.error(
                            f'Could not dmget {run.archive_dir / run.tar_file}. \
                                Removing from list of files to extract.'
                        )
                        all_runs.remove(run)
            else:
                # dmget failed, but not with the usual error
                # associated with a bad file/tape.
                raise subprocess.CalledProcessError(
                    dmget.returncode,
                    str(dmget.args),
                    output=dmget.stdout,
                    stderr=dmget.stderr,
                )
    else:
        logger.info('No files to dmget')

    for run in all_runs:
        process_run(run, variables, rerun=args.rerun, clean=args.tmp)


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    parser.add_argument(
        '-y',
        '--year',
        type=int,
        help='Only extract from this year, instead of all years in config',
    )
    parser.add_argument(
        '-m',
        '--month',
        type=int,
        help='Only extract from this month, instead of all months in config',
    )
    parser.add_argument('-r', '--rerun', action='store_true')
    parser.add_argument(
        '-n',
        '--new',
        action='store_true',
        help='Flag if this is a new near-real-time forecast instead of a retrospective',
    )
    parser.add_argument(
        '--tmp',
        action='store_true',
        help='Store data in $TMPDIR instead of top level /vftmp/$USER',
    )
    args = parser.parse_args()
    main(args)
