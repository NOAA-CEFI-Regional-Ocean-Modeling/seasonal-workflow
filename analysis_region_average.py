from pathlib import Path

import numpy as np
import xarray

from utils import open_var

if __name__ == '__main__':
    import argparse

    from yaml import safe_load

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    parser.add_argument('-v', '--var', type=str, required=True)
    args = parser.parse_args()
    with open(args.config, 'r') as file:
        config = safe_load(file)

    outdir = Path(config['filesystem']['forecast_output_data']) / 'analysis'
    outdir.mkdir(exist_ok=True)
    first_year = config['climatology']['first_year']
    last_year = config['climatology']['last_year']
    masks = xarray.open_dataset(config['regions']['mask_file'])
    pp = Path(config['filesystem']['analysis_history']).parents[0]
    ds = open_var(pp, args.domain, args.var)
    if 'yh_sub01' in ds and 'xh_sub01' in ds:
        ds = ds.rename({f'{v}_sub01': v for v in ['yh', 'xh']})

    averages = []
    climos = []
    anoms = []
    persists = []
    persist_vals = []
    for reg in config['regions']['names']:
        print(reg)
        weights = masks['areacello'].where(masks[reg]).fillna(0)
        average = ds.weighted(weights).mean(['yh', 'xh'])
        climo = (
            average.sel(time=slice(f'{first_year}-01-01', f'{last_year}-12-31'))
            .groupby('time.month')
            .mean('time')
        )
        anom = average.groupby('time.month') - climo
        anom.name = args.var
        persist = anom.shift(time=1)
        persist_lead = persist.expand_dims(lead=np.arange(12)).rename({'time': 'init'})
        persist_lead = persist_lead.transpose('init', 'lead', ...)
        persist_lead['lead'].attrs['units'] = 'months'
        persist_lead.name = args.var
        # Same but with actual values instead of anomalies
        pv = average.shift(time=1)
        pv_lead = pv.expand_dims(lead=np.arange(12)).rename({'time': 'init'})
        pv_lead = pv_lead.transpose('init', 'lead', ...)
        pv_lead['lead'].attrs['units'] = 'months'
        pv_lead.name = args.var
        # This needs to be last
        average['region'] = reg
        averages.append(average)
        climo['region'] = reg
        climos.append(climo)
        anom['region'] = reg
        anoms.append(anom)
        persist_lead['region'] = reg
        persists.append(persist_lead)
        pv_lead['region'] = reg
        persist_vals.append(pv_lead)

    averages = xarray.concat(averages, dim='region')
    averages.to_netcdf(outdir / f'analysis_{args.domain}_{args.var}_regionmean.nc')
    climos = xarray.concat(climos, dim='region')
    climos.to_netcdf(outdir / f'analysis_{args.domain}_{args.var}_climo_regionmean.nc')
    anoms = xarray.concat(anoms, dim='region')
    anoms.to_netcdf(outdir / f'analysis_{args.domain}_{args.var}_anom_regionmean.nc')
    persists = xarray.concat(persists, dim='region')
    persists.to_netcdf(
        outdir / f'analysis_{args.domain}_{args.var}_persist_anom_regionmean.nc'
    )
    persist_vals = xarray.concat(persist_vals, dim='region')
    persist_vals.to_netcdf(
        outdir / f'analysis_{args.domain}_{args.var}_persist_value_regionmean.nc'
    )
