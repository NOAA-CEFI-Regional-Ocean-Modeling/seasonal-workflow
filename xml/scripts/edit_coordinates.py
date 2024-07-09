import xarray
import argparse
from yaml import safe_load

parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', type=str, required=True)
args = parser.parse_args()
with open(args.config, 'r') as file: 
    config = safe_load(file)
    nens = config['forecasts']['ensemble_size']

for i in range(1,nens+1):
	print(f"Working on ensemble member e{i:02d}")
	ds = xarray.open_dataset(f'2020-09-e{i:02d}.ocean_month.nc')
	ds = ds.swap_dims({'time': 'lead'}).set_coords(['init', 'member'])
	ds = ds.expand_dims('init')
	ds = ds.transpose(*(['init', 'lead'] + [d for d in ds.dims if d not in ['init', 'lead']]))
	ds.to_netcdf(f'2020-09-e{i:02d}.ocean_month_correct_metadata.nc', unlimited_dims='init')
