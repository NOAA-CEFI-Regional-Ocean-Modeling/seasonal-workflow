import os
from pathlib import Path

from workflow_tools.utils import run_cmd


def main(
    d2m_file: Path, sp_file: Path, tmpdir: Path, outdir: Path | str | None = None
) -> None:
    if outdir is None:
        outdir = d2m_file.parent
    # Not critical but ensures str can be represented as a path
    elif isinstance(outdir, str):
        outdir = Path(outdir)
    svp_file = tmpdir / 'svp_tmp.nc'
    sphum_file = d2m_file.name.replace('d2m', 'sphum')  # assuming d2m in name
    run_cmd(f'gcp {d2m_file} {tmpdir}')
    run_cmd(f'gcp {sp_file} {tmpdir}')
    run_cmd(
        f'cdo expr,"svp=611.2*exp(17.67*(d2m-273.15)/(d2m-29.65))" \
            {tmpdir / d2m_file.name} {svp_file}'
    )
    run_cmd(
        f'cdo -expr,"_mr=0.622*svp/(msl-svp);sphum=_mr/(1+_mr);" -merge \
              {svp_file} {tmpdir / sp_file.name} {tmpdir / sphum_file}'
    )
    run_cmd(f'gcp {tmpdir / sphum_file} {outdir}')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--d2m', required=True)
    parser.add_argument('-p', '--sp', required=True)
    parser.add_argument('-o', '--out', default=None)
    args = parser.parse_args()
    tmp = Path(os.environ['TMPDIR'])
    main(Path(args.d2m), Path(args.sp), tmp, args.out)
