from calendar import monthrange
from concurrent import futures
from functools import partial
from pathlib import Path

import xarray
from loguru import logger

from workflow_tools.boundary import Segment
from workflow_tools.grid import round_coords
from workflow_tools.io import HSMGet
from workflow_tools.utils import run_cmd

hsmget = HSMGet()
TMP = hsmget.tmp


def find_best_files(
    year: int, mon: int, var: str, reanalysis_path: Path, analysis_path: Path
) -> list[Path]:
    if var == 'uv':
        # For velocity, find the individual components separately.
        # Since u and v are in the same file for the analysis,
        # analysis files will be duplicated; remove them.
        files = find_best_files(year, mon, 'uo', reanalysis_path, analysis_path)
        files += find_best_files(year, mon, 'vo', reanalysis_path, analysis_path)
        files = sorted(set(files))
    else:
        # Use reanalysis files when they are available,
        # and find and use the analysis files when not.
        files = []
        for day in range(1, monthrange(year, mon)[1] + 1):
            # Search for reanalysis file for the day.
            # If there are multiple files with different R* for the day,
            # choose the last one by sorted order.
            reanalysis_file = sorted(
                (reanalysis_path / var / str(year)).glob(
                    f'*_{year}{mon:02d}{day:02d}_R????????.nc'
                )
            )
            if len(reanalysis_file) > 0:
                files.append(reanalysis_file[-1])
            else:
                # The variable naming for the analysis is complicated.
                # Assuming that the 202406 in
                # cmems_mod_glo_phy_anfc_0.083deg_P1D-m_202406 will never change.
                # The ???? before _R* could be hcst or nwct or fcst.
                # Currently there is no checking if both are matched;
                # the last one by sorted order will be returned.
                if var == 'zos':
                    # Path like:
                    # /archive/uda/CEFI/GLOBAL_ANALYSISFORECAST_PHY_001_024/
                    # cmems_mod_glo_phy_anfc_0.083deg_P1D-m_202406/2024/09/
                    # glo12_rg_1d-m_20240920-20240920_2D_hcst_R20241002.nc
                    analysis_file = sorted(
                        (
                            analysis_path
                            / 'cmems_mod_glo_phy_anfc_0.083deg_P1D-m_202406'
                            / str(year)
                            / f'{mon:02d}'
                        ).glob(
                            f'glo12_rg_1d-m_{year}{mon:02d}{day:02d}-{year}{mon:02d}{day:02d}_2D_????_R*.nc'
                        )
                    )
                elif var in ['thetao', 'so']:
                    analysis_file = sorted(
                        (
                            analysis_path
                            / f'cmems_mod_glo_phy-{var}_anfc_0.083deg_P1D-m_202406'
                            / str(year)
                            / f'{mon:02d}'
                        ).glob(
                            f'glo12_rg_1d-m_{year}{mon:02d}{day:02d}-{year}{mon:02d}{day:02d}_3D-{var}_????_R*.nc'
                        )
                    )
                elif var in ['uo', 'vo']:
                    # Path like:
                    # /archive/uda/CEFI/GLOBAL_ANALYSISFORECAST_PHY_001_024/
                    # cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m_202406/2024/09/
                    # glo12_rg_1d-m_20240920-20240920_3D-uovo_hcst_R20241002.nc
                    analysis_file = sorted(
                        (
                            analysis_path
                            / 'cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m_202406'
                            / str(year)
                            / f'{mon:02d}'
                        ).glob(
                            f'glo12_rg_1d-m_{year}{mon:02d}{day:02d}-{year}{mon:02d}{day:02d}_3D-uovo_????_R*.nc'
                        )
                    )
                else:
                    raise Exception('Unknown variable')
                if len(analysis_file) > 0:
                    files.append(analysis_file[-1])
                else:
                    logger.error(
                        f'Did not a find a file for {year}-{mon:02d}-{day:02d} {var}'
                    )
    return files


def thread_worker(
    in_file: Path, out_dir: Path, lon_lat_box: tuple[float, float, float, float]
) -> Path:
    out_file = out_dir / in_file.name
    lonmin, lonmax, latmin, latmax = lon_lat_box
    if '_2D_' in in_file.name:
        run_cmd(
            f'cdo setmisstonn '
            f'-sellonlatbox,{lonmin},{lonmax},{latmin},{latmax} '
            f'{in_file.as_posix()} {out_file.as_posix()}',
            escape=True,
        )
    else:
        run_cmd(
            f'cdo setmisstonn -sellevidx,1/49 '
            f'-sellonlatbox,{lonmin},{lonmax},{latmin},{latmax} '
            f'{in_file.as_posix()} {out_file.as_posix()}',
            escape=True,
        )
    # out_file.with_suffix('.tmp').rename(out_file)
    return out_file


def main(
    year: int,
    mon: int,
    var: str,
    threads: int,
    analysis_path: Path,
    reanalysis_path: Path,
    lon_lat_box: tuple[float, float, float, float],
    segments: list[Segment],
    update: bool = False,
    dry: bool = False,
):
    if mon == 'all' or update:
        last_month = 12 if mon == 'all' else int(mon)
        for m in range(1, last_month + 1):
            logger.trace(m)
            main(
                year,
                m,
                var,
                threads,
                analysis_path,
                reanalysis_path,
                lon_lat_box,
                segments,
                dry=dry,
            )
    else:
        mon = int(mon)
        if var == 'all':
            for v in ['so', 'thetao', 'uv', 'zos']:
                main(
                    year,
                    mon,
                    v,
                    threads,
                    analysis_path,
                    reanalysis_path,
                    lon_lat_box,
                    segments,
                    dry=dry,
                )
        else:
            logger.info(var)
            files = find_best_files(
                year,
                mon,
                var,
                analysis_path=analysis_path,
                reanalysis_path=reanalysis_path,
            )
            if dry:
                logger.info(f'Found {len(files)} files')
                for f in files:
                    logger.info(f.as_posix())
            else:
                # Make sure that data was found for every day of the month.
                n_expected = monthrange(year, mon)[1]
                if len(files) != n_expected:
                    logger.warning(
                        f'Number of files found ({len(files)}) is not '
                        'the same as expected ({n_expected})'
                    )
                copied_files = hsmget(files)

                with futures.ThreadPoolExecutor(max_workers=threads) as executor:
                    processed_files = sorted(
                        executor.map(
                            partial(
                                thread_worker, out_dir=TMP, lon_lat_box=lon_lat_box
                            ),
                            copied_files,
                        )
                    )

                # Save data for use with sponge. TODO: config output path
                if var in ['so', 'thetao']:
                    file_strs = ' '.join(x.as_posix() for x in processed_files)
                    run_cmd(
                        f'cdo timavg -cat {file_strs} '
                        f'/work/acr/mom6/nwa12/analysis_input_data/sponge/monthly_filled/glorys_{var}_{year}-{mon:02d}.nc',
                        escape=True,
                    )
                ds = xarray.open_mfdataset(
                    processed_files, preprocess=partial(round_coords, to=12)
                ).rename({'latitude': 'lat', 'longitude': 'lon'})
                if 'depth' in ds.coords:
                    ds = ds.rename({'depth': 'z'})
                for seg in segments:
                    logger.info('Regridding segment {num:03d}', num=seg.num)
                    if var == 'uv':
                        seg.regrid_velocity(
                            ds['uo'],
                            ds['vo'],
                            suffix=f'{year}-{mon:02d}',
                            additional_encoding={
                                'time': {'units': 'hours since 1990-01-01 00:00:00'}
                            },
                        )
                    else:
                        seg.regrid_tracer(
                            ds[var],
                            suffix=f'{year}-{mon:02d}',
                            additional_encoding={
                                'time': {'units': 'hours since 1990-01-01 00:00:00'}
                            },
                        )
                for f in processed_files:
                    f.unlink()


if __name__ == '__main__':
    import argparse

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-y', '--year', type=int, required=True)
    parser.add_argument('-m', '--month', default='all')
    parser.add_argument('-v', '--var', default='all')
    parser.add_argument('-t', '--threads', type=int, default=4)
    parser.add_argument(
        '-u',
        '--update',
        action='store_true',
        help='Update/rerun all months leading up to the current month.',
    )
    parser.add_argument(
        '-D',
        '--dry',
        action='store_true',
        help='Dry run: print out the files that would be worked on.',
    )
    args = parser.parse_args()
    config = load_config(args.config)
    dom = config.domain
    hgrid = xarray.open_dataset(dom.hgrid_file)
    output_dir = config.filesystem.nowcast_input_data / 'boundary' / 'monthly'
    angle_units = 'degrees' if dom.hgrid_angle_is_degrees else 'radians'
    logger.debug(f'Using hgrid angle units: {angle_units}')
    segments = [
        Segment(num, edge, hgrid, output_dir=output_dir,
                in_degrees=dom.hgrid_angle_is_degrees)
        for num, edge in dom.boundaries.items()
    ]
    main(
        args.year,
        args.month,
        args.var,
        args.threads,
        segments=segments,
        lon_lat_box=(dom.west_lon, dom.east_lon, dom.south_lat, dom.north_lat),
        reanalysis_path=config.filesystem.interim_data.GLORYS_reanalysis,
        analysis_path=config.filesystem.interim_data.GLORYS_analysis,
        update=args.update,
        dry=args.dry,
    )
