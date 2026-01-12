import os
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import xarray
from loguru import logger
from numpy.lib.stride_tricks import sliding_window_view

from workflow_tools.grid import center_to_outer, reuse_regrid, round_coords
from workflow_tools.utils import XarrayData, flatten


def get_coast_mask(mask: xarray.DataArray) -> np.ndarray:
    # Alistair's method of finding coastal cells
    ocn_mask = mask.values
    cst_mask = 0 * ocn_mask  # All land should be 0
    is_ocean = ocn_mask > 0
    cst_mask[(is_ocean) & (np.roll(ocn_mask, 1, axis=1) == 0)] = 1  # Land to the west
    cst_mask[(is_ocean) & (np.roll(ocn_mask, -1, axis=1) == 0)] = 1  # Land to the east
    cst_mask[(is_ocean) & (np.roll(ocn_mask, 1, axis=0) == 0)] = 1  # Land to the south
    cst_mask[(is_ocean) & (np.roll(ocn_mask, -1, axis=0) == 0)] = 1  # Land to the north

    # Model boundaries are not coasts
    cst_mask[0, :] = 0
    cst_mask[:, 0] = 0
    cst_mask[-1, :] = 0
    cst_mask[:, -1] = 0

    return cst_mask


def expand_mask_true(mask: xarray.DataArray, window: int) -> np.ndarray:
    """Given a 2D bool mask, expand the true values of the
    mask so that at a given point, the mask becomes true
    if any point within a window x window box is true.
    Note, points near the edges of the mask, where the
    box would expand beyond the mask, are always set to false.

    Args:
        mask: 2D boolean numpy array
        window: width of the square box used to expand the mask

    """
    wind = sliding_window_view(mask, (window, window))
    wind_mask = wind.any(axis=(2, 3))
    final_mask = np.zeros_like(mask)
    i = int((window - 1) / 2)  # width of edges that can't fit a full box
    final_mask[i:-i, i:-i] = wind_mask
    return final_mask.astype('bool')


def get_encodings(ds: xarray.Dataset) -> xarray.Dataset:
    # Drop '_FillValue' from all variables when writing out
    all_vars = list(ds.data_vars.keys()) + list(ds.coords.keys())
    encodings = {v: {'_FillValue': None} for v in all_vars}

    # Make sure time has the right units and datatype
    # otherwise it will become an int and MOM will fail.
    encodings['time'].update(
        {'units': 'days since 1950-01-01', 'dtype': 'float', 'calendar': 'gregorian'}
    )
    return encodings


def drop_dup_time(ds: XarrayData) -> XarrayData:
    return ds.drop_duplicates('time', keep='first')


def regrid_runoff(  # noqa: PLR0915
    glofas: xarray.DataArray,
    glofas_mask: np.ndarray,
    hgrid: xarray.Dataset,
    coast_mask: np.ndarray,
    modify: bool = True,
) -> xarray.Dataset:
    # Assuming grid spacing of 0.05 deg here and below;
    # eventually should detect from file (there are attributes for this)
    dlon = dlat = 0.05  # GloFAS grid spacing
    glofas_latb = center_to_outer(glofas['lat'])
    glofas_lonb = center_to_outer(glofas['lon'])

    lon = hgrid.x[1::2, 1::2]
    lonb = hgrid.x[::2, ::2]
    lat = hgrid.y[1::2, 1::2]
    latb = hgrid.y[::2, ::2]
    # From Alistair
    area = (hgrid.area[::2, ::2] + hgrid.area[1::2, 1::2]) + (
        hgrid.area[1::2, ::2] + hgrid.area[::2, 1::2]
    )

    # Convert m3/s to kg/m2/s
    # Borrowed from
    # https://xgcm.readthedocs.io/en/latest/xgcm-examples/05_autogenerate.html
    distance_1deg_equator = 111000.0
    dx = dlon * np.cos(np.deg2rad(glofas.lat)) * distance_1deg_equator
    dy = xarray.ones_like(glofas.lon) * dlat * distance_1deg_equator
    glofas_area = dx * dy
    glofas_kg = glofas * 1000.0 / glofas_area

    # Conservatively interpolate runoff onto MOM grid
    glofas_to_mom_con = reuse_regrid(
        {
            'lon': glofas.lon,
            'lat': glofas.lat,
            'lon_b': glofas_lonb,
            'lat_b': glofas_latb,
        },
        {'lat': lat, 'lon': lon, 'lat_b': latb, 'lon_b': lonb},
        method='conservative',
        periodic=True,
        reuse_weights=True,
        filename=os.path.join(os.environ['TMPDIR'], 'glofas_to_mom.nc'),
    )
    # Interpolate only from GloFAS points that are river end points.
    glofas_regridded = glofas_to_mom_con(glofas_kg.where(glofas_mask > 0).fillna(0.0))

    glofas_regridded = glofas_regridded.rename({'nyp': 'ny', 'nxp': 'nx'}).values

    # For NWA12 only: remove runoff from west coast of Guatemala
    # and El Salvador that actually drains into the Pacific.
    glofas_regridded[:, 0:190, 0:10] = 0.0
    glofas_regridded[:, 0:150, 0:100] = 0.0
    glofas_regridded[:, 0:125, 100:170] = 0.0
    glofas_regridded[:, 0:60, 170:182] = 0.0
    glofas_regridded[:, 0:45, 180:200] = 0.0
    glofas_regridded[:, 0:40, 200:220] = 0.0
    glofas_regridded[:, 0:45, 220:251] = 0.0
    glofas_regridded[:, 0:50, 227:247] = 0.0
    glofas_regridded[:, 0:35, 250:270] = 0.0

    # Remove runoff along the southern boundary to avoid double counting
    glofas_regridded[:, 0:1, :] = 0.0

    # For NWA12 only: remove runoff from Hudson Bay
    glofas_regridded[:, 700:, 150:300] = 0.0

    if modify:
        # For NWA12 only and GloFAS v4 only: Mississippi River adjustment.
        # Adjust to be approximately the same as the USGS station at Belle Chasse, LA
        # and relocate closer to the end of the delta.
        ms_total_kg = glofas_regridded[:, 312:314, 108]
        # Convert to m3/s
        ms_total_cms = (
            ms_total_kg * np.broadcast_to(area[312:314, 108], ms_total_kg.shape)
        ).sum(axis=1) / 1000.0
        ms_corrected = 0.5800588699054435 * ms_total_cms + 3842.60956525417
        glofas_regridded[:, 312:314, 108] = 0.0
        new_ms_coords = [(314, 108), (315, 107), (317, 112)]
        for c in new_ms_coords:
            y, x = c
            glofas_regridded[:, y, x] = (
                (1 / len(new_ms_coords)) * ms_corrected * 1000.0 / float(area[y, x])
            )

    # Flatten mask and coordinates to 1D
    flat_mask = coast_mask.ravel().astype('bool')
    coast_lon = lon.values.ravel()[flat_mask]
    coast_lat = lat.values.ravel()[flat_mask]
    mom_id = np.arange(np.prod(coast_mask.shape))

    # Use xesmf to find the index of the nearest coastal cell
    # for every grid cell in the MOM domain
    coast_to_mom = reuse_regrid(
        {'lat': coast_lat, 'lon': coast_lon},
        {'lat': lat, 'lon': lon},
        method='nearest_s2d',
        locstream_in=True,
        reuse_weights=True,
        filename=os.path.join(os.environ['TMPDIR'], 'coast_to_mom.nc'),
    )
    coast_id = mom_id[flat_mask]
    nearest_coast = coast_to_mom(coast_id)

    if modify:
        # For NWA12 only and GloFAS v4 only: the Susquehanna gets mapped to the Delaware
        # because NWA12 only has the lower half of the Chesapeake.
        # Move the nearest grid point for the Susquehanna Region
        # to the one for the lower bay.
        # see notebooks/check_glofas_susq.ipynb
        target = nearest_coast[455, 271]
        nearest_coast[460:480, 265:280] = target

    nearest_coast = nearest_coast.ravel()

    # Raw runoff on MOM grid, reshaped to 2D (time, grid_id)
    raw = glofas_regridded.reshape([glofas_regridded.shape[0], -1])

    # Zero array that will be filled with runoff at coastal cells
    filled = np.zeros_like(raw)

    # Loop over each coastal cell and fill the result array
    # with the sum of runoff for every grid cell that
    # has this coastal cell as its closest coastal cell
    for i in coast_id:
        filled[:, i] = raw[:, nearest_coast == i].sum(axis=1)

    # Reshape back to 3D
    filled_reshape = filled.reshape(glofas_regridded.shape)

    # Convert to xarray
    ds = xarray.Dataset(
        {
            'runoff': (['time', 'y', 'x'], filled_reshape),
            'area': (['y', 'x'], area.data),
            'lat': (['y', 'x'], lat.data),
            'lon': (['y', 'x'], lon.data),
        },
        coords={
            'time': glofas['time'].data,
            'y': np.arange(filled_reshape.shape[1]),
            'x': np.arange(filled_reshape.shape[2]),
        },
    )
    return ds


def get_glofas_file(
    main_template: str, interim_template: str, monthly_template: str, year: int
) -> Path | list[Path] | None:
    main_file = main_template.format(y=year)
    interim_file = interim_template.format(y=year)
    # Check for a full year of data from the main dataset
    if Path(main_file).is_file():
        return Path(main_file)
    # Check for a full year of data from the interim dataset.
    elif Path(interim_file).is_file():
        return Path(interim_file)
    # Check for files for individual months from the interim dataset.
    # Stop as soon as a month isn't found.
    else:
        monthly_files = []
        for m in range(1, 13):
            mf = monthly_template.format(m=m, y=year)
            # breakpoint()
            if Path(mf).is_file():
                monthly_files.append(mf)
            else:
                break
        if len(monthly_files) > 0:
            return monthly_files
        else:
            return None


def main(  # noqa: PLR0915
    year: int,
    mask_file: Path,
    hgrid_file: Path,
    ldd_file: Path,
    glofas_template: str,
    glofas_interim: str,
    glofas_interim_monthly: str,
    glofas_subset: dict[str, slice],
    extension_climo: Path,
    outdir: Path,
    modify: bool = True,
) -> None:
    ocean_mask = xarray.open_dataarray(mask_file)
    mom_coast_mask = get_coast_mask(ocean_mask)
    hgrid = xarray.open_dataset(hgrid_file)
    # drainage direction already has coords named lat/lon and they are exactly 1/25 deg
    ldd = xarray.open_dataset(ldd_file).ldd.sel(**glofas_subset)
    get_file = partial(
        get_glofas_file, glofas_template, glofas_interim, glofas_interim_monthly
    )

    # Start pour point mask to include points where ldd==5
    # and any surrounding point is ocean (nan in ldd)
    adjacent = np.logical_and(ldd == 5.0, expand_mask_true(np.isnan(ldd), 3))
    imax = 20  # max number of iterations
    for i in range(imax):
        # Number of points previously:
        npoints = int(adjacent.sum())
        # Update pour point mask to include points where ldd==5
        # and any surrounding point was previously identified as a pour point
        adjacent = np.logical_and(ldd == 5.0, expand_mask_true(adjacent, 3))
        # Number of points in updated mask:
        npoints_new = int(adjacent.sum())
        # If the number of points hasn't changed, it has converged.
        if npoints_new == npoints:
            logger.info(f'Converged after {i + 1} iterations')
            break
    else:
        raise Exception('Did not converge')

    # Note; converting from dataarray to numpy, because the
    # glofas ldd coordinates are float32 and the
    # glofas runoff coordinates are float64
    glofas_coast_mask = adjacent.values

    # temporarily deal with 1993 because of a problem with the data for 1992
    if year == 1993:
        files = [get_file(year)]
    else:
        files = [get_file(y) for y in [year - 1, year]]

    # Check if the next year is available
    # (need Jan 1 for padding)
    next_file = get_file(year + 1)
    if next_file is not None:
        files.append(next_file)
        extend = False
    else:
        extend = True

    # If individual months of interim data were found,
    # the result will probably be a list of one or more lists.
    # Flatten to a single list.
    files = flatten(files)

    logger.info('Using files:')
    for f in files:
        logger.info(f)
    if extend:
        logger.info('Extending with climatology')

    glofas = (
        xarray.open_mfdataset(
            files, preprocess=lambda x: drop_dup_time(round_coords(x, to=25))
        )
        .rename({'latitude': 'lat', 'longitude': 'lon'})
        .sel(
            time=slice(f'{year - 1}-12-31 00:00:00', f'{year + 1}-01-01 00:00:00'),
            **glofas_subset,
        )
        .dis24.load()  # avoid chunking issues?
    )
    # Latest glofas is in terms of discharge over previous 24 hours,
    # so subtract 12 hours to center.
    # TODO: the climatology extension below should be modified
    # depending on whether write_river_climo.py modifies the time.
    # TODO: confirm this is still accurate.
    shifted_time = glofas['time'] + pd.Timedelta(hours=12)
    # Temporary fix for bad 1992:
    if year == 1993:
        shifted_time[0] = shifted_time[0] - pd.Timedelta(hours=12)
    glofas['time'] = shifted_time

    res = regrid_runoff(glofas, glofas_coast_mask, hgrid, mom_coast_mask, modify=modify)

    # If the next year is not available for padding,
    # pad using the climatology.
    # If only a partial year of data is available this should
    # also have the effect of filling the missing part
    # with the climatology.
    if extend:
        logger.info('Extending to end of year using climatology')
        # TODO: This is the v3.0 climatology.
        climo = xarray.open_dataset(extension_climo)
        extend = climo.isel(time=slice(int(res['time.dayofyear'][-1]) - 1, None))
        back = climo.isel(time=0)
        extend = xarray.concat((extend, back), dim='time')
        new_times = pd.date_range(
            res.time[-1].values, freq='1D', periods=len(extend.time) + 1
        )[1:]
        extend['time'] = new_times
        res = xarray.merge([res, extend.runoff])

    out_file = outdir / f'glofasv4_runoff_{year}.nc'
    encodings = get_encodings(res)
    res['time'].attrs = {'cartesian_axis': 'T'}
    res['x'].attrs = {'cartesian_axis': 'X'}
    res['y'].attrs = {'cartesian_axis': 'Y'}
    res['lat'].attrs = {'units': 'degrees_north'}
    res['lon'].attrs = {'units': 'degrees_east'}
    res['runoff'].attrs = {'units': 'kg m-2 s-1'}
    # Write out
    res.to_netcdf(
        out_file,
        unlimited_dims=['time'],
        format='NETCDF3_64BIT',
        encoding=encodings,
        engine='netcdf4',
    )
    res.close()


if __name__ == '__main__':
    import argparse
    from pathlib import Path

    from workflow_tools.config import load_config

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True)
    parser.add_argument('-y', '--year', type=int, required=True)
    parser.add_argument(
        '-M',
        '--modify',
        action='store_true',
        help='Apply corrections for location and bias',
    )
    args = parser.parse_args()
    config = load_config(args.config)
    dom = config.domain
    subset = {
        'lat': slice(dom.north_lat, dom.south_lat),
        'lon': slice(dom.west_lon, dom.east_lon),
    }
    main(
        args.year,
        mask_file=dom.ocean_mask_file,
        hgrid_file=dom.hgrid_file,
        ldd_file=config.filesystem.interim_data.GloFAS_ldd,
        glofas_template=config.filesystem.interim_data.GloFAS_v4,
        glofas_interim=config.filesystem.interim_data.GloFAS_interim,
        glofas_interim_monthly=config.filesystem.interim_data.GloFAS_interim_monthly,
        glofas_subset=subset,
        extension_climo=config.filesystem.interim_data.GloFAS_extension_climatology,
        outdir=config.filesystem.nowcast_input_data / 'rivers',
        modify=args.modify,
    )
