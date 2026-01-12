import errno
from dataclasses import dataclass
from functools import singledispatchmethod
from getpass import getuser
from os import environ
from pathlib import Path
from shutil import which
from typing import Any

import xarray
from loguru import logger

from .utils import run_cmd


def _run_cmd_silently(cmd: str) -> None:
    """
    Runs a command, with the output of the job sent to
    the logger instead of printed out.
    """
    res = run_cmd(cmd, text=True, capture_output=True)
    logger.debug(res.stdout)


@dataclass
class HSMGet:
    archive: Path = Path('/')  # hopefully this will duplicate paths used by frepp
    ptmp: Path = Path('/ptmp') / getuser()
    tmp: Path = Path(environ.get('TMPDIR', ptmp))

    @singledispatchmethod
    def __call__(self, path_or_paths: Any) -> Any:
        raise TypeError(
            'Unsupported type for path to hsmget. Expected str, Path, or list[Path]'
        )

    @__call__.register
    def _call_str(self, path: str) -> Path:
        cast_path = Path(path)
        return self.__call__(cast_path)

    @__call__.register
    def _call_path(self, path: Path) -> Path:
        if which('hsmget') is None:
            logger.info('Not using hsmget')
            return path
        relative = path.relative_to(self.archive)
        # hsmget will do the dmget first and this is fine since it's one file
        cmd = f'hsmget -q -a {self.archive} -w {self.tmp} -p {self.ptmp} {relative}'
        _run_cmd_silently(cmd)
        return self.tmp / relative

    @__call__.register
    def _call_paths(self, paths: list) -> list[Path]:
        if which('hsmget') is None:
            logger.info('Not using hsmget')
            return paths
        p_str = ' '.join([p.as_posix() for p in paths])
        _run_cmd_silently(f'dmget {p_str}')
        relative = [p.relative_to(self.archive) for p in paths]
        rel_str = ' '.join([r.as_posix() for r in relative])
        cmd = f'hsmget -q -a {self.archive} -w {self.tmp} -p {self.ptmp} {rel_str}'
        _run_cmd_silently(cmd)
        return [self.tmp / r for r in relative]


def open_var(
    pp_root: Path, kind: str, var: str, hsmget: HSMGet | None = None
) -> xarray.DataArray:
    if hsmget is None:
        hsmget = HSMGet()
    freq = 'daily' if 'daily' in kind else 'monthly'
    pp_dir = pp_root / 'pp' / kind / 'ts' / freq
    if not pp_dir.is_dir():
        raise FileNotFoundError(
            errno.ENOENT, 'Could not find post-processed directory', str(pp_dir)
        )
    # Get all of the available post-processing chunk directories
    # (assuming chunks in units of years)
    available_chunks = list(pp_dir.glob('*yr'))
    if len(available_chunks) == 0:
        raise FileNotFoundError(
            errno.ENOENT, 'Could not find post-processed chunk subdirectory'
        )
    # Sort from longest to shortest chunk
    sorted_chunks = sorted(
        available_chunks, key=lambda x: int(x.name[0:-2]), reverse=True
    )
    for chunk in sorted_chunks:
        # Look through the available chunks and return for the
        # largest chunk that has file(s).
        matching_files = list(chunk.glob(f'{kind}.*.{var}.nc'))
        # Treat 1 and > 1 files separately,
        # though the > 1 case could probably handle both.
        if len(matching_files) > 1:
            tmpfiles = hsmget(sorted(matching_files))
            return xarray.open_mfdataset(tmpfiles, decode_timedelta=True)[
                var
            ]  # Avoid FutureWarning about decode_timedelta
        elif len(matching_files) == 1:
            tmpfile = hsmget(matching_files[0])
            return xarray.open_dataset(tmpfile, decode_timedelta=True)[
                var
            ]  # Avoid FutureWarning about decode_timedelta
    raise FileNotFoundError(
        errno.ENOENT,
        'Could not find any post-processed files. Check if frepp failed.',
    )


def write_ds(ds: xarray.Dataset, fout: str | Path) -> None:
    for v in ds:
        if ds[v].dtype == 'float64':
            ds[v].encoding['_FillValue'] = 1.0e20
    ds.to_netcdf(
        fout,
        format='NETCDF3_64BIT',
        engine='netcdf4',
        encoding={'time': {'dtype': 'float64', 'calendar': 'gregorian'}},
        unlimited_dims=['time'],
    )
