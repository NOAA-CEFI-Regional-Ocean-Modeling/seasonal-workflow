import errno
from calendar import isleap, monthrange
from functools import partial
from pathlib import Path, PurePath

# Top level path to all SPEAR medium reforecast data on archive
SPEAR_ROOT = (
    Path('/archive')
    / 'l1j'
    / 'spear_med'
    / 'rf_hist'
    / 'fcst'
    / 's_j11_OTA_IceAtmRes_L33'
)


def get_spear_file(
    ystart: int, mstart: int, domain: str, freq: str, var: str
) -> PurePath:
    """
    Find the filename for SPEAR post-processed forecast output.
    ystart: forecast start year
    mstart: forecast start month
    domain: diagnostic domain (e.g., ocean, ocean_z)
    freq: output frequency (typically monthly or daily)
    variable: post-processed diagnostic variable
    """
    ystart = int(ystart)
    mstart = int(mstart)
    # March files for leap years are named as if they start in February.
    # Daily files are labeled as Feb 29.
    if isleap(ystart) and mstart == 3:
        mstart_f = 2
        dstart_f = 29
    else:
        mstart_f = mstart
        dstart_f = 1

    if mstart == 1:
        yend = ystart
        mend = 12
    else:
        yend = ystart + 1
        mend = mstart - 1

    dend_f = monthrange(yend, mend)[1]

    # monthly files don't have day in the filename, but daily do
    if freq == 'monthly':
        fname = f'{domain}.{ystart}{mstart_f:02d}-{yend}{mend:02d}.{var}.nc'
    elif freq == 'daily':
        fname = f'{domain}.{ystart}{mstart_f:02d}{dstart_f:02d}-{yend}{mend:02d}{dend_f:02d}.{var}.nc'  # noqa: E501
    elif freq == '6hr':
        fname = f'{domain}.{ystart}{mstart_f:02d}{dstart_f:02d}00-{yend}{mend:02d}{dend_f:02d}23.{var}.nc'  # noqa: E501
    else:
        raise Exception(f'Unknown frequency: {freq}')
    return PurePath(fname)


def get_spear_path(
    ystart: int,
    mstart: int,
    domain: str,
    freq: str,
    var: str,
    ens: int | str = 'pp_ensemble',
    root: Path = SPEAR_ROOT,
) -> Path:
    """
    Find the complete path to SPEAR post-processed forecast output on archive.
    Includes logic to identify which of several re-runs to use where available.
    ystart: forecast start year
    mstart: forecast start month
    domain: diagnostic domain (e.g., ocean, ocean_z)
    freq: output frequency (typically monthly or daily)
    variable: post-processed diagnostic variable
    ens: ensemble member; either an integer, to get a single member,
      or "pp_ensemble" to get the post-processed ensemble mean.
    """
    if ens != 'pp_ensemble':
        ens = f'pp_ens_{int(ens):02d}'

    subdir = f'i{ystart}{mstart:02d}01_OTA_IceAtmRes_L33'
    fname = get_spear_file(ystart, mstart, domain, freq, var)
    subpath = PurePath(str(ens)) / domain / 'ts' / freq / '1yr' / fname

    """
    For year 1991-2014
    iyyyymm01__OTA_IceAtmRes_L33

    For year 2015-2019:
    iyyyymm01__OTA_IceAtmRes_L33_update

    For year 2020:
    iyyyymm01__OTA_IceAtmRes_L33_rerun

    For 2021 (updated Apr 2022)
    iyyyymm01__OTA_IceAtmRes_L33_update

    For 2022 onward
    iyyyymm01__OTA_IceAtmRes_L33
    """

    if ystart == 2020:
        subdir += '_rerun'
    elif ystart in range(2015, 2020) or ystart == 2021:
        subdir += '_update'
    elif ystart == 2025 and mstart == 10:
        # This is likely a special case; an early start
        subdir += '_MED'
    final_path = root / subdir / subpath
    if not final_path.is_file():
        raise FileNotFoundError(
            errno.ENOENT,
            'Could not find right plain directory, _update, or _rerun.',
            final_path.as_posix(),
        )
    return final_path


def get_spear_files(variables: list[str], *args, **kwargs) -> list[PurePath]:
    fun = partial(get_spear_file, *args, **kwargs)
    return [fun(v) for v in variables]


def get_spear_paths(variables: list[str], *args, **kwargs) -> list[Path]:
    fun = partial(get_spear_path, *args, **kwargs)
    return [fun(v) for v in variables]


if __name__ == '__main__':
    import argparse

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--domain')
    parser.add_argument('-f', '--freq')
    parser.add_argument('-v', '--var')
    parser.add_argument('-e', '--ensemble')
    parser.add_argument('-c', '--config')
    args = parser.parse_args()
    config = load_config(args.config)

    fnames = []
    # If called from command line, this will return all files
    # for years and months in the following ranges
    for ystart in range(
        config.retrospective_forecasts.first_year,
        config.retrospective_forecasts.last_year + 1,
    ):
        for mstart in config.retrospective_forecasts.months:
            fname = get_spear_path(
                ystart, mstart, args.domain, args.freq, args.var, ens=args.ensemble
            ).as_posix()
            fnames.append(fname)
    print(' '.join(fnames))
