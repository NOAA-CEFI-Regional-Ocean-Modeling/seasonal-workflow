import os
from pathlib import Path
import shutil
from subprocess import run
import xarray


if __name__ == '__main__':
    import argparse
    from yaml import safe_load
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    parser.add_argument('-r','--rerun', action='store_true')
    parser.add_argument('-m', '--mean', action='store_true', help='Include only ensemble mean in combined result, dropping individual members.')
    args = parser.parse_args()
    with open(args.config, 'r') as file: 
        config = safe_load(file)
    tmp = Path(os.environ['TMPDIR'])

    model_output_data = Path(config['filesystem']['model_output_data'])
    model_output_data.mkdir(exist_ok=True)
    first_year = config['climatology']['first_year']
    last_year = config['climatology']['last_year']
    nens = config['forecasts']['ensemble_size']

    members = []

    if args.mean:
        # Large files: ensemble average, then concatenate averages
        for m in config['forecasts']['months']:
            for y in range(config['forecasts']['first_year'], config['forecasts']['last_year']+1):
                month_file = tmp / f'{args.domain}_{y}_{m:02d}_ensmean.nc'
                files = list((model_output_data / 'extracted' / args.domain).glob(f'{y}-{m:02d}-e??.{args.domain}.nc'))
                if len(files) == 1:
                    shutil.copy(files[0], month_file)
                    members.append(month_file)
                    print(month_file)
                elif len(files) > 1: 
                    file_str = ' '.join(map(lambda x: x.as_posix(), files))
                    run(f'ncea -h {file_str} -O {month_file}', shell=True, check=True)
                    members.append(month_file)  
                    print(month_file)
    else:
        # Regular files: concatenate initializations together
        for e in range(1, nens+1):
            out_file = tmp / f'{args.domain}_e{e:02d}.nc'
            if not out_file.exists() or args.rerun:
                # print(f'Loading member {e:02d}')
                files = list((model_output_data / 'extracted' / args.domain).glob(f'????-??-e{e:02d}.{args.domain}.nc'))
                if len(files) > 0:
                    file_str = ' '.join(map(lambda x: x.as_posix(), files))
                    print(f'ncrcat {len(files)} files to {out_file}')
                    run(f'ncrcat -h {file_str} -O {out_file}', shell=True, check=True)
                    members.append(out_file)

    concat_dim = 'init' if args.mean else 'member'
    print(f'Concat by {concat_dim}')
    model_ds = xarray.open_mfdataset(members, combine='nested', concat_dim=concat_dim).sortby('init') # sorting is important for slicing later
    model_ds = model_ds.drop_vars(['ens', 'verif', 'mstart', 'ystart'], errors='ignore')
    print('Ensemble mean and anomalies')
    if args.mean:
        ensmean = model_ds
    else:
        ensmean = model_ds.mean('member')
    climo = ensmean.sel(init=slice(f'{first_year}-01-01', f'{last_year}-12-31')).groupby('init.month').mean('init').load()
    anom = model_ds.groupby('init.month') - climo
    anom = anom.rename({v: f'{v}_anom' for v in anom.data_vars})
    model_ds = xarray.merge([model_ds, anom])
    # Write the climatology, being sure that appropriate coords are ints.
    # Also trying to remove the empty dimension "time" from the output.
    encoding = {v: {'dtype': 'int32'} for v in ['lead', 'month']}
    climo.encoding = {}
    print('Writing climatology')
    climo.to_netcdf(model_output_data / f'climatology_{args.domain}_{first_year}_{last_year}.nc',
        encoding=encoding)
    # Do the same for the full set of forecasts
    encoding = {v: {'dtype': 'int32'} for v in ['lead', 'member', 'month']}
    print('Writing forecasts')
    model_ds.to_netcdf(model_output_data / f'forecasts_{args.domain}.nc', encoding=encoding)
