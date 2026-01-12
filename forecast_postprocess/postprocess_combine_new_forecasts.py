from pathlib import Path

import numpy as np
import pandas as pd
import xarray
from loguru import logger

from workflow_tools.config import Config, load_config


def process_all_vars(
    y: int, m: int, all_vars: list[str], output_dir: Path, config: Config, domain: str
) -> None:
    model_output_data = config.filesystem.forecast_output_data
    members = (model_output_data / 'extracted' / domain).glob(
        f'{y}-{m:02d}-e??.{domain}.nc'
    )
    model_ds = xarray.open_mfdataset(
        list(members),
        combine='nested',
        concat_dim='member',
        combine_attrs='drop_conflicts',
        decode_timedelta=False,
    )
    model_ds = (
        model_ds.drop_vars(['ens', 'verif', 'mstart', 'ystart'], errors='ignore')
        .squeeze()
        .load()
    )
    first_year = config.climatology.first_year
    last_year = config.climatology.last_year
    if isinstance(model_ds.lead.values[0], np.timedelta64):
        valid_time = (model_ds.init + model_ds.lead).data
        freq = 'daily' if len(valid_time) > 12 else 'monthly'
    elif (
        'units' in model_ds['lead'].attrs and model_ds['lead'].attrs['units'] == 'days'
    ):
        valid_time = [
            model_ds.init.values + pd.Timedelta(days=int(ld)) for ld in model_ds.lead
        ]
        freq = 'daily'
    else:
        valid_time = [
            model_ds.init.values + pd.DateOffset(months=int(ld)) for ld in model_ds.lead
        ]
        freq = 'monthly'
    model_ds['valid_time'] = (('lead',), valid_time)
    for var in all_vars:
        logger.info(var)
        climo_file = (
            model_output_data
            / f'climatology_{domain}_{var}_{first_year}_{last_year}.nc'
        )
        climo_exists = False
        if climo_file.exists():
            climo = xarray.open_dataset(climo_file, decode_timedelta=False)
            if m in climo.month:
                climo_exists = True
                anom = model_ds[var] - climo[var].sel(month=m)
                anom.name = f'{var}_anom'
                res = xarray.merge((model_ds[[var, 'valid_time']], anom))
        if not climo_exists:
            logger.warning(
                f'Climatology not found for month {m}. Setting anomalies to nan'
            )
            res = model_ds[[var, 'valid_time']].copy()
            res[f'{var}_anom'] = res[var] * np.nan
        res = res.transpose('lead', 'member', ...)
        # Could also add this attribute?
        # res.attrs['cefi_climatology_file'] = str(climo_file.name)
        encoding = {
            v: {'dtype': 'int32'}
            for v in ['lead', 'member', 'month', 'valid_time']
            if v in res
        }
        # Compress main variable to reduce space
        encoding.update(
            {v: {'zlib': True, 'complevel': 3} for v in [var, f'{var}_anom']}
        )
        fname = config.filesystem.combined_name.format(
            freq=freq, var=var, year=y, month=m
        )
        res.to_netcdf(output_dir / fname, encoding=encoding)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    parser.add_argument('-v', '--var', type=str, default='all')
    parser.add_argument('-r', '--rerun', action='store_true')
    parser.add_argument(
        '-y', '--year', type=int, required=True, help='Initial year of new forecast'
    )
    parser.add_argument(
        '-m', '--month', type=int, required=True, help='Initial month of new forecast'
    )
    parser.add_argument(
        '-o', '--output', type=str, help='Where to place output files', required=False
    )
    args = parser.parse_args()
    config = load_config(args.config)
    if args.output is None:
        output_dir = config.filesystem.forecast_output_data / 'individual'
    else:
        output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)
    if ',' in args.var:
        all_vars = args.var.split(',')
    elif args.var == 'all':
        all_vars = config.variables[args.domain]
    else:
        all_vars = [args.var]
    process_all_vars(args.year, args.month, all_vars, output_dir, config, args.domain)
