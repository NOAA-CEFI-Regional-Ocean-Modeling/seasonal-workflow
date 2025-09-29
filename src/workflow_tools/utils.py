import re
from subprocess import CalledProcessError, CompletedProcess, run
from typing import Any

import numpy as np
import pandas as pd
import xarray
from loguru import logger

type XarrayData = xarray.Dataset | xarray.DataArray


def run_cmd(cmd: str, escape: bool = False, **kwargs: Any) -> CompletedProcess:
    logger.debug(cmd)
    # Some file names contain (1) or similar, which
    # will cause problems if sent directly to dmget.
    # Put a backslash in front of these.
    if escape:
        esc_cmd = re.sub(r'([\(\)])', r'\\\1', cmd)
    else:
        esc_cmd = cmd
    try:
        res = run(esc_cmd, shell=True, check=True, **kwargs)
    except CalledProcessError as err:
        if err.stderr is not None:
            logger.error(err.stderr)
        if err.stdout is not None:
            logger.error(err.stdout)
        raise err
    else:
        return res

def pad_ds(ds: xarray.Dataset) -> xarray.Dataset:
    if not isinstance(ds.time.values[0], np.datetime64):
        # use python datetimes
        ds['time'] = ds['time'].to_index().to_datetimeindex()

    # convert time bounds to days
    if 'time_bnds' in ds:
        ds['time_bnds'] = (ds['time_bnds'].astype('int') / (1e9 * 24 * 60 * 60)).astype(
            'int'
        )

    # Pad by duplicating the first data point and
    # inserting it as one day before the oringal start
    tfirst = ds.isel(time=0).copy()
    for var in ['time', 'average_T1', 'average_T2']:
        if var in tfirst:
            tfirst[var] = tfirst[var] - np.timedelta64(1, 'D')
    if 'time_bnds' in tfirst:
        tfirst['time_bnds'] = tfirst['time_bnds'] - 1

    # Pad by duplicating the last data point and inserting it as one day after the end
    tlast = ds.isel(time=-1).copy()
    for var in ['time', 'average_T1', 'average_T2']:
        if var in tlast:
            tlast[var] = tlast[var] + np.timedelta64(1, 'D')
    if 'time_bnds' in tlast:
        tlast['time_bnds'] = tlast['time_bnds'] + 1

    # Combine the duplicated and original data
    tcomb = xarray.concat((tfirst, ds, tlast), dim='time').transpose(
        'time', 'lat', 'lon', 'bnds'
    )

    if 'time_bnds' in tcomb:
        tcomb['time_bnds'] = tcomb['time_bnds'] + 1

    tcomb['time'].attrs = ds['time'].attrs

    tcomb['lat_bnds'] = (('lat', 'bnds'), tcomb['lat_bnds'].isel(time=0).data)
    tcomb['lon_bnds'] = (('lon', 'bnds'), tcomb['lon_bnds'].isel(time=0).data)
    return tcomb


def modulo(ds: xarray.Dataset) -> xarray.Dataset:
    ds['time'] = np.arange(0, 365, dtype='float')
    ds['time'].attrs['units'] = 'days since 0001-01-01'
    ds['time'].attrs['calendar'] = 'noleap'
    ds['time'].attrs['modulo'] = ' '
    ds['time'].attrs['cartesian_axis'] = 'T'
    return ds


def flatten(lst: list[Any]) -> list[Any]:
    flat_list = []
    for item in lst:
        if isinstance(item, list):
            flat_list.extend(flatten(item))
        else:
            flat_list.append(item)
    return flat_list


def smooth_climatology(
    da: XarrayData, window: int = 5, dim: str = 'dayofyear'
) -> xarray.DataArray:
    smooth = da.copy()
    for _ in range(2):
        smooth = xarray.concat(
            [
                smooth.isel(**{dim: slice(-window, None)}),
                smooth,
                smooth.isel(**{dim: slice(None, window)}),
            ],
            dim,
        )
        smooth = (
            smooth.rolling(**{dim: (window * 2 + 1)}, center=True, min_periods=1)
            .mean()
            .isel(**{dim: slice(window, -window)})
        )
    return smooth


def match_obs_to_forecasts(
    obs: XarrayData,
    forecasts: XarrayData,
    init_dim: str = 'init',
    lead_dim: str = 'lead',
) -> XarrayData:
    matching_obs = []
    for lead in forecasts[lead_dim]:
        # TODO: this is hard-coded to assume monthly data
        target_times = forecasts[init_dim].to_index() + pd.DateOffset(months=lead)
        try:
            match = obs.sel(time=target_times)
        except KeyError as err:
            missing_times = [t for t in target_times if t not in obs['time']]
            logger.info(
                f'These forecast times are not in the observations: {missing_times}'
            )
            raise err
        match['time'] = forecasts['init'].values
        match['lead'] = lead
        matching_obs.append(match)
    matching_obs = xarray.concat(matching_obs, dim='lead').rename({'time': 'init'})
    matching_obs = matching_obs.transpose('init', 'lead', ...)
    return matching_obs
