import xarray
import argparse
from pathlib import Path
from yaml import safe_load

parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', type=str, required=True)
parser.add_argument('-d', '--domain', type=str, default='ocean_month')
args = parser.parse_args()
with open(args.config, 'r') as file: 
    config = safe_load(file)
    
nens = config['forecasts']['ensemble_size']
model_output_data = Path(config['filesystem']['model_output_data'])

for i in range(1,nens+1):
	print(f"Working on ensemble member e{i:02d}")
	ds = xarray.open_dataset(model_output_data / 'extracted'/ args.domain / f'2020-09-e{i:02d}.{args.domain}_wrong_coords.nc')
	ds = ds.set_coords(['init', 'member'])
	ds = ds.expand_dims('init')
	ds = ds.transpose(*(['init', 'time'] + [d for d in ds.dims if d not in ['init', 'lead']]))
	ds.to_netcdf(model_output_data / 'extracted'/ args.domain / f'2020-09-e{i:02d}.{args.domain}.nc', unlimited_dims='init')
