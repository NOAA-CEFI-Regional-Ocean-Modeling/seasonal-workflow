import xarray
from loguru import logger

from workflow_tools.config import Config, load_config


def process_var(var: str, config: Config, domain: str, ensemble_mean: bool) -> None:
    model_output_data = config.filesystem.forecast_output_data

    fname = (
        f'forecasts_{domain}_{var}_ensmean.nc'
        if ensemble_mean
        else f'forecasts_{domain}_{var}.nc'
    )
    ds = xarray.open_dataset(model_output_data / fname)

    masks = xarray.open_dataset(config.regions.mask_file)
    if 'yh_sub01' in ds and 'xh_sub01' in ds:
        logger.debug('Renaming xh and yh coordinates')
        ds = ds.rename({f'{v}_sub01': v for v in ['yh', 'xh']})

    averages = []
    for reg in config.regions.names:
        logger.info('Mean for region {reg}', reg=reg)
        weights = masks['areacello'].where(masks[reg]).fillna(0)
        ave = ds.weighted(weights).mean(['yh', 'xh']).load()
        ave['region'] = reg
        ave = ave.set_coords('region')
        averages.append(ave)

    averages = xarray.concat(averages, dim='region')
    outname = (
        f'forecasts_{domain}_{var}_ensmean_regionmean.nc'
        if ensemble_mean
        else f'forecasts_{domain}_{var}_regionmean.nc'
    )
    averages.to_netcdf(model_output_data / outname)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    parser.add_argument('-v', '--var', type=str, required=True)
    parser.add_argument(
        '-m',
        '--mean',
        action='store_true',
        help='Include only ensemble mean in combined result, \
            dropping individual members.',
    )
    args = parser.parse_args()
    config = load_config(args.config)
    if ',' in args.var:
        cmdvar = args.var.split(',')
        for v in cmdvar:
            process_var(v, config, args.domain, args.mean)
    else:
        process_var(args.var, config, args.domain, args.mean)
