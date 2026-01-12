import argparse

from workflow_tools.config import load_config
from workflow_tools.forecast import ForecastRun


def colorprint(msg, color):
    colors = {
        'ok': '\033[92m',
        'warning': '\033[93m',
        'fail': '\033[91m',
        'end': '\033[0m',
    }
    print(colors[color] + msg + colors['end'])


parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', type=str, required=True)
args = parser.parse_args()
config = load_config(args.config)

first_year = config.retrospective_forecasts.first_year
last_year = config.retrospective_forecasts.last_year
nens = config.retrospective_forecasts.ensemble_size
template = config.filesystem.forecast_history

for ystart in range(first_year, last_year + 1):
    for mstart in config.retrospective_forecasts.months:
        for ens in range(1, nens + 1):
            run = ForecastRun(ystart=ystart, mstart=mstart, ens=ens, template=template)
            tar = run.archive_dir / run.tar_file
            if tar.is_file():
                colorprint(f'{run.tar_file} e{ens:02d}: found', 'ok')
            elif tar.with_suffix(tar.suffix + '.gcp').is_file():
                colorprint(f'{run.tar_file} e{ens:02d}: partial transfer', 'warning')
            else:
                colorprint(f'{run.tar_file} e{ens:02d}: not found', 'fail')
