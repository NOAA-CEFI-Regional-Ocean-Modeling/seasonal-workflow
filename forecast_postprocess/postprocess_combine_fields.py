import concurrent.futures
import os
from argparse import ArgumentParser, Namespace
from functools import partial
from pathlib import Path
from subprocess import CompletedProcess, run

import numpy as np
import xarray
from loguru import logger

from workflow_tools.config import Config, load_config
from workflow_tools.utils import smooth_climatology


def run_nco(nco_tool: str, var: str, in_files: str, out_file: Path) -> CompletedProcess:
    cmd = f'{nco_tool} -v {var} -h {in_files} -O {out_file}'
    logger.debug(cmd)
    return run(cmd, shell=True, check=True)


def check_futures(futures: list[concurrent.futures.Future]) -> None:
    for future in futures:
        try:
            _ = future.result()
        except Exception as e:
            logger.error(f'Task generated an exception: {e}')


def process_ensmean(
    config: Config,
    cmdargs: Namespace,
    var: str,
    mon: int = 0
) -> list[Path]:
    # Large files: ensemble average, then concatenate averages
    tmp = Path(os.environ['TMPDIR'])
    model_output_data = config.filesystem.forecast_output_data
    threads = cmdargs.threads
    members = []
    futures = []
    months = config.retrospective_forecasts.months if mon == 0 else [mon]
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        for m in months:
            for y in range(
                config.retrospective_forecasts.first_year,
                config.retrospective_forecasts.last_year + 1,
            ):
                month_file = tmp / f'{cmdargs.domain}_{var}_{y}_{m:02d}_ensmean.nc'
                logger.trace('Will write to {f}', f=month_file)
                files = list(
                    (model_output_data / 'extracted' / cmdargs.domain).glob(
                        f'{y}-{m:02d}-e??.{cmdargs.domain}.nc'
                    )
                )
                if len(files) == 1:  # single ensemble member
                    futures.append(
                        executor.submit(run_nco, 'ncks', var, str(files[0]), month_file)
                    )
                    members.append(month_file)
                elif len(files) > 1:
                    logger.trace(
                        'Found {l} files for {y}-{m:02d}', l=len(files), y=y, m=m
                    )
                    file_str = ' '.join(x.as_posix() for x in files)
                    futures.append(
                        executor.submit(run_nco, 'ncea', var, file_str, month_file)
                    )
                    members.append(month_file)
                else:
                    logger.info('No files found for {y}-{m:02d}', y=y, m=m)
    check_futures(futures)
    return members


def process_all_members(
    config: Config,
    cmdargs: Namespace,
    var: str,
    mon: int = 0
) -> list[Path]:
    nens = config.retrospective_forecasts.ensemble_size
    tmp = Path(os.environ['TMPDIR'])
    model_output_data = config.filesystem.forecast_output_data
    threads = cmdargs.threads
    members = []
    futures = []
    months = config.retrospective_forecasts.months if mon == 0 else [mon]
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        # Regular files: concatenate initializations together
        for e in range(1, nens + 1):
            out_file = tmp / f'{cmdargs.domain}_{var}_e{e:02d}.nc'
            if not out_file.exists() or cmdargs.rerun:
                files = []
                for y in range(
                    config.retrospective_forecasts.first_year,
                    config.retrospective_forecasts.last_year + 1,
                ):
                    for m in months:
                        tentative = (
                            model_output_data
                            / 'extracted'
                            / cmdargs.domain
                            / f'{y}-{m:02d}-e{e:02d}.{cmdargs.domain}.nc'
                        )
                        if tentative.is_file():
                            files.append(tentative)
                if len(files) > 0:
                    file_str = ' '.join(x.as_posix() for x in files)
                    futures.append(
                        executor.submit(
                            run_nco, 'ncrcat', f'{var},member', file_str, out_file
                        )
                    )
            members.append(out_file)
    check_futures(futures)
    return members


def combine(
    file_list: list[Path],
    var: str,
    first_year: int,
    last_year: int,
    domain: str,
    output_path: Path,
    mean: bool = False,
    mon: int = 0,
) -> None:
    concat_dim = 'init' if mean else 'member'
    logger.info(f'Concat by {concat_dim}')
    model_ds = xarray.open_mfdataset(
        file_list, combine='nested', concat_dim=concat_dim, decode_timedelta=False
    ).sortby('init')  # sorting is important for slicing later
    model_ds = model_ds.drop_vars(
        ['ens', 'verif', 'mstart', 'ystart'], errors='ignore'
    ).load()
    model_ds['lead'] = np.arange(len(model_ds['lead']))
    logger.info('Ensemble mean and anomalies')
    if mean:
        ensmean = model_ds
    else:
        ensmean = model_ds.mean('member')
    climo = (
        ensmean[var]
        .sel(init=slice(f'{first_year}-01-01', f'{last_year}-12-31'))
        .groupby('init.month')
        .mean('init')
    )
    if 'daily' in domain or len(model_ds.lead) >= 365:
        logger.info('Smoothing daily climatology')
        climo = smooth_climatology(climo, dim='lead')
    anom = model_ds.groupby('init.month') - climo
    anom = anom.rename({v: f'{v}_anom' for v in anom.data_vars})
    model_ds = xarray.merge([model_ds, anom])
    # Write the climatology, being sure that appropriate coords are ints.
    # Also trying to remove the empty dimension "time" from the output.
    encoding = {v: {'dtype': 'int32'} for v in ['month']}
    climo.encoding = {}
    m_str = '' if mon == 0 else f'_mon{mon:02d}'
    logger.info('Writing climatology')
    climo.to_netcdf(
        output_path / f'climatology_{domain}_{var}_{first_year}_{last_year}{m_str}.nc',
        encoding=encoding,
    )
    # Do the same for the full set of forecasts
    encoding = {v: {'dtype': 'int32'} for v in ['member', 'month'] if v in model_ds}
    encoding.update({var: {'zlib': True, 'complevel': 3} for var in model_ds.data_vars})
    logger.info('Writing forecasts')
    fname = (
        f'forecasts_{domain}_{var}{m_str}_ensmean.nc'
        if mean
        else f'forecasts_{domain}_{var}{m_str}.nc'
    )
    model_ds.to_netcdf(output_path / fname, encoding=encoding)


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    parser.add_argument('-v', '--var', type=str, required=True)
    parser.add_argument('-r', '--rerun', action='store_true')
    parser.add_argument(
        '-m',
        '--mean',
        action='store_true',
        help='Include only ensemble mean in combined result, \
            dropping individual members.',
    )
    parser.add_argument('-M', '--month', type=int, default=0)
    parser.add_argument('-t', '--threads', type=int, default=1)
    args = parser.parse_args()
    config = load_config(args.config)
    model_output_data = config.filesystem.forecast_output_data
    first_year = config.climatology.first_year
    last_year = config.climatology.last_year
    if args.mean:
        logger.info('Calculating ensemble mean and using for output.')
        processor = partial(process_ensmean, config, args, mon=args.month)
    else:
        logger.info('Including all ensemble members in output.')
        processor = partial(process_all_members, config, args, mon=args.month)
    if ',' in args.var:
        cmdvar = args.var.split(',')
        for v in cmdvar:
            files = processor(v)
            combine(
                files,
                args.var,
                first_year,
                last_year,
                args.domain,
                model_output_data,
                mean=args.mean,
                mon=args.month
            )
    else:
        files = processor(args.var)
        combine(
            files,
            args.var,
            first_year,
            last_year,
            args.domain,
            model_output_data,
            mean=args.mean,
            mon=args.month
        )
