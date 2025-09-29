import datetime as dt
import os
import tarfile
from pathlib import Path

import numpy as np
import xarray
from loguru import logger

from workflow_tools.config import Config, load_config
from workflow_tools.utils import run_cmd

# Path to store temporary output to:
TMP = Path(os.environ['TMPDIR'])

# Drop these variables from the snapshots:
DROP_VARS = ['mass_wt', 'opottempmint', 'somint', 'uice', 'vice']

_EXPECTED_BGC_VARS = [
    'no3',
    'o2',
    'po4',
    'sio4',
    'alk',
    'dic',
    'cadet_arag',
    'cadet_calc',
    'fed',
    'fedi',
    'felg',
    'fedet',
    'fesm',
    'htotal',
    'ldon',
    'ldop',
    'lith',
    'lithdet',
    'nbact',
    'ndet',
    'ndi',
    'nlg',
    'nsm',
    'nh4',
    'pdet',
    'srdon',
    'srdop',
    'sldon',
    'sldop',
    'sidet',
    'silg',
    'nsmz',
    'nmdz',
    'nlgz',
    'dic14',
    'do14',
    'do14c',
    'di14c',
    'nh3',
    'mu_mem_nsm',
    'mu_mem_nlg',
    'mu_mem_ndi',
    'irr_aclm',
    'fedet_btf',
    'sidet_btf',
    'pdet_btf',
    'ndet_btf',
    'lithdet_btf',
    'cadet_calc_btf',
    'cadet_arag_btf',
    'co3_ion',
    'cased',
    'chl',
    'nsm_btf',
    'nmd_btf',
    'nlg_btf',
    'ndi_btf',
    'fesm_btf',
    'femd_btf',
    'felg_btf',
    'fedi_btf',
    'simd_btf',
    'silg_btf',
    'pdi_btf',
    'plg_btf',
    'pmd_btf',
    'psm_btf',
    'irr_mem_dp',
    'irr_aclm_sfc',
    'irr_aclm_z',
    'mu_mem_nmd',
]


def ics_from_snapshot(component, history, ystart, mstart, force_extract=False):  # noqa: PLR0915
    target_time = f'{ystart}-{mstart:02d}-01'
    if mstart == 1:
        yfile = ystart - 1
    else:
        yfile = ystart

    snapshot_file = history / f'{yfile}0101.nc.tar'

    # extract the snapshot from the tar file to tmp
    if force_extract or not (TMP / f'./{yfile}0101.{component}_snap.nc').exists():
        # dmget the tar file
        run_cmd(f'dmget {snapshot_file.as_posix()}')
        logger.info('extracting')
        tar = tarfile.open(snapshot_file, mode='r:')
        member = tar.getmember(f'./{yfile}0101.{component}_snap.nc')
        tar.extractall(path=TMP, members=[member])

    # open and modify the tmp snapshot file
    logger.info('modifying')
    ds = xarray.open_dataset(
        TMP / f'./{yfile}0101.{component}_snap.nc', decode_cf=False
    )
    ds['time'].attrs['calendar'] = 'gregorian'
    ds = xarray.decode_cf(ds)
    ds = ds.drop_vars(DROP_VARS, errors='ignore')
    if 'uo' in ds and 'vo' in ds:
        ds = ds.rename({'uo': 'u', 'vo': 'v'})
    snapshot = ds.sel(time=target_time)
    snapshot['time'] = dt.datetime(ystart, mstart, 1)
    snapshot = snapshot.expand_dims(time=1)
    snapshot = snapshot.fillna(0.0)
    all_vars = list(snapshot.data_vars.keys()) + list(snapshot.coords.keys())
    encodings = {v: {'_FillValue': None, 'dtype': 'float32'} for v in all_vars}
    snapshot.attrs['source'] = snapshot_file.as_posix()

    if 'cobalt' in component:
        nz = len(snapshot['zl'])
        ny = len(snapshot['yh'])
        nx = len(snapshot['xh'])
        for v in _EXPECTED_BGC_VARS:
            if v not in snapshot:
                logger.info(f'Adding zero {v} to dataset')
                if '_btf' in v:
                    val = 0.0
                else:
                    val = 1e-10
                snapshot[v] = (['zl', 'yh', 'xh'], np.zeros((nz, ny, nx)) + val)

        for v in ['si', 'fe', 'n']:
            new_var = f'{v}md'
            if new_var not in snapshot:
                logger.info(f'Adding approx {new_var} to dataset')
                snapshot[new_var] = snapshot[f'{v}lg']

        for s in ['lg', 'md', 'sm', 'di']:
            if s == 'di' and 'pdi' not in snapshot:
                logger.info('Adding approx pdi to dataset')
                snapshot['pdi'] = snapshot['ndi'] / 40.0
            else:
                new_var = f'p{s}'
                if new_var not in snapshot:
                    logger.info(f'Adding {new_var} to snapshot')
                    snapshot[new_var] = snapshot[f'n{s}'] / 16.0
    elif 'ice' in component:
        # Convert ice and snow thickness from the output units (m)
        # to the units that the model expects for initial conditions
        # (kg m-2) by using the constant densities of ice and snow.
        scaling = {'hice': 905.0, 'hsnow': 330.0}
        for var, scale in scaling.items():
            if var in snapshot:
                logger.info(f'Converting {var} to kg m-2')
                snapshot[var] *= scale

    # write the results to tmp
    logger.info('writing')
    output_name = f'forecast_ics_{component}_{ystart}-{mstart:02d}.nc'
    tmp_output = TMP / output_name
    snapshot.to_netcdf(
        tmp_output,
        format='NETCDF3_64BIT',
        engine='netcdf4',
        encoding=encodings,
        unlimited_dims='time',
    )
    return tmp_output


def main(config: Config, year: int, month: int, now: bool):
    if now:
        history = Path(
            config.filesystem.nowcast_history.format(
                year=year, month=month
            )
        )
    else:
        history = config.filesystem.analysis_history
    outdir = config.filesystem.forecast_input_data / 'initial'
    outdir.mkdir(exist_ok=True)
    tmp_files = [
        ics_from_snapshot(c, history, year, month)
        for c in config.snapshots
    ]
    file_str = ' '.join(x.name for x in tmp_files)
    tarfile = f'{outdir.as_posix()}/forecast_ics_{year}-{month:02d}.tar'
    cmd = f'tar cvf {tarfile} -C {TMP} {file_str}'
    run_cmd(cmd)
    for f in tmp_files:
        f.unlink()
    logger.success(tarfile)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-y', '--year', type=int)
    parser.add_argument('-m', '--month', type=int)
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument(
        '-n',
        '--now',
        help='Use nowcast (extended nudged hindcast)',
        action='store_true',
    )
    # TODO: reusing old files is dangerous and should probably not be default
    parser.add_argument(
        '-r', '--rerun', help='Run even if previous files exist', action='store_true'
    )
    parser.add_argument(
        '-e',
        '--ensemble',
        type=int,
        help='Member number when writing an ensemble of ICs',
        required=False,
    )
    args = parser.parse_args()
    config = load_config(args.config)
    main(config, args.year, args.month, args.now)
