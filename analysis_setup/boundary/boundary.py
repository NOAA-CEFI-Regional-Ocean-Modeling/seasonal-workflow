import warnings
from os import path

import numpy as np
import xarray
from loguru import logger

from workflow_tools.grid import reuse_regrid

# ignore pandas FutureWarnings raised multiple times by xarray
warnings.simplefilter(action='ignore', category=FutureWarning)


def check_angle_range(angle):
    amax = float(angle.max())
    amin = float(angle.min())
    if amax > (2 * np.pi) or amin < (-2 * np.pi):
        raise ValueError(f'Grid angle ranges from [{amin}, {amax}]. \
            Expected from [-2pi, 2pi]. Are the units correct?')


def rotate_uv(u, v, angle):
    """Rotate velocities from earth-relative to model-relative.

    Args:
        u: west-east component of velocity.
        v: south-north component of velocity.
        angle: angle of rotation from true north to model north.

    Returns:
        Model-relative west-east and south-north components of velocity.
    """
    urot = np.cos(angle) * u - np.sin(angle) * v
    vrot = np.sin(angle) * u + np.cos(angle) * v
    return urot, vrot


def fill_missing(arr, xdim='locations', zdim='z', fill='b'):
    """Fill missing data along the boundaries.
    Extrapolates horizontally first, then vertically.

    Args:
        arr: xarray DataArray or Dataset to be fillled.
        xdim: horizontal dimension of the dataset.
        zdim: vertical dimension of the dataset.
        fill (str, optional): Method to use for filling data horizontally
            (b for bfill or f for ffill).

    Returns:
        Filled DataArray or Dataset.
    """
    if fill == 'f':
        filled = arr.ffill(dim=xdim, limit=None)
    elif fill == 'b':
        filled = arr.bfill(dim=xdim, limit=None)
    if zdim is not None:
        filled = filled.ffill(dim=zdim, limit=None).fillna(0)
    return filled


def find_datavar(ds):
    """
    Given an xarray Dataset containing one data variable of interest
    and possibly extra variables for lat and lon,
    return just the name of the variable of interest.

    Args:
        ds (xarray.Dataset): Dataset potentially containing variables 'lat' and 'lon',
            plus one and only one other variable of interest.

    Raises:
        Exception: if there are multiple potential variables of interest
            (more than one variable not named lat or lon).

    Returns:
        str: Name of variable of interest from Dataset.
    """
    names = [x for x in ds if x not in ['lon', 'lat']]
    if len(names) > 1:
        raise Exception('Found multiple potential data variables')
    return names[0]


def ap2ep(uc, vc):
    """Convert complex tidal u and v to tidal ellipse.
    Adapted from ap2ep.m for matlab
    Original copyright notice:
    %Authorship Copyright:
    %
    %    The author retains the copyright of this program, while  you are welcome
    % to use and distribute it as long as you credit the author properly and respect
    % the program name itself. Particularly, you are expected to retain the original
    % author's name in this original version or any of its modified version that
    % you might make. You are also expected not to essentially change the name of
    % the programs except for adding possible extension for your own version you
    % might create, e.g. ap2ep_xx is acceptable.  Any suggestions are welcome and
    % enjoy my program(s)!
    %
    %
    %Author Info:
    %_______________________________________________________________________
    %  Zhigang Xu, Ph.D.
    %  (pronounced as Tsi Gahng Hsu)
    %  Research Scientist
    %  Coastal Circulation
    %  Bedford Institute of Oceanography
    %  1 Challenge Dr.
    %  P.O. Box 1006                    Phone  (902) 426-2307 (o)
    %  Dartmouth, Nova Scotia           Fax    (902) 426-7827
    %  CANADA B2Y 4A2                   email xuz@dfo-mpo.gc.ca
    %_______________________________________________________________________
    %
    % Release Date: Nov. 2000, Revised on May. 2002 to adopt Foreman's northern semi
    % major axis convention.

    Args:
        uc: complex tidal u velocity
        vc: complex tidal v velocity

    Returns:
        (semi-major axis, eccentricity, inclination [radians], phase [radians])
    """
    wp = (uc + 1j * vc) / 2.0
    wm = np.conj(uc - 1j * vc) / 2.0

    Wp = np.abs(wp)  # noqa: N806
    Wm = np.abs(wm)  # noqa: N806
    THETAp = np.angle(wp)  # noqa: N806
    THETAm = np.angle(wm)  # noqa: N806

    SEMA = Wp + Wm  # noqa: N806
    SEMI = Wp - Wm  # noqa: N806
    ECC = SEMI / SEMA  # noqa: N806
    PHA = (THETAm - THETAp) / 2.0  # noqa: N806
    INC = (THETAm + THETAp) / 2.0  # noqa: N806

    return SEMA, ECC, INC, PHA


def ep2ap(SEMA, ECC, INC, PHA):  # noqa: N803
    """Convert tidal ellipse to real u and v amplitude and phase.
    Adapted from ep2ap.m for matlab.
    Original copyright notice:
    %Authorship Copyright:
    %
    %    The author of this program retains the copyright of this program, while
    % you are welcome to use and distribute this program as long as you credit
    % the author properly and respect the program name itself. Particularly,
    % you are expected to retain the original author's name in this original
    % version of the program or any of its modified version that you might make.
    % You are also expected not to essentially change the name of the programs
    % except for adding possible extension for your own version you might create,
    % e.g. app2ep_xx is acceptable.  Any suggestions are welcome and enjoy my
    % program(s)!
    %
    %
    %Author Info:
    %_______________________________________________________________________
    %  Zhigang Xu, Ph.D.
    %  (pronounced as Tsi Gahng Hsu)
    %  Research Scientist
    %  Coastal Circulation
    %  Bedford Institute of Oceanography
    %  1 Challenge Dr.
    %  P.O. Box 1006                    Phone  (902) 426-2307 (o)
    %  Dartmouth, Nova Scotia           Fax    (902) 426-7827
    %  CANADA B2Y 4A2                   email xuz@dfo-mpo.gc.ca
    %_______________________________________________________________________
    %
    %Release Date: Nov. 2000

    Args:
        SEMA: semi-major axis
        ECC: eccentricity
        INC: inclination [radians]
        PHA: phase [radians]

    Returns:
        (u amplitude, u phase [radians], v amplitude, v phase [radians])

    """
    Wp = (1 + ECC) / 2. * SEMA # noqa: N806
    Wm = (1 - ECC) / 2. * SEMA # noqa: N806
    THETAp = INC - PHA # noqa: N806
    THETAm = INC + PHA # noqa: N806

    wp = Wp * np.exp(1j * THETAp)
    wm = Wm * np.exp(1j * THETAm)

    cu = wp + np.conj(wm)
    cv = -1j * (wp - np.conj(wm))

    ua = np.abs(cu)
    va = np.abs(cv)
    up = -np.angle(cu)
    vp = -np.angle(cv)

    return ua, va, up, vp


def z_to_dz(ds, max_depth=6500.):
    """Given depths of layer centers, get layer thicknesses.
    This works for output after regridding to a model boundary using xesmf.
    Derived from https://github.com/ESMG/regionalMOM6_notebooks/blob/master/creating_obc_input_files/panArctic_OBC_from_global_MOM6.ipynb
    Hardcoding all dimension names here...
    Args:
        ds: xarray.DataArray or xarray.Dataset containing variables 'time', 'z',
            and 'locations'.
        max_depth: Depth of model bottom. Thickness of bottom layer will be stretched
            to reach this depth.

    Returns:
        xarray.DataArray: 3D <time, z, locations> array of thicknesses.
    """
    zi = 0.5 * (np.roll(ds['z'], shift=-1) + ds['z'])
    zi[-1] = max_depth
    dz = zi - np.roll(zi, shift=1)
    dz[0] = zi[0]
    nt = len(ds['time'])
    nx = len(ds['locations'])
    dz = np.tile(dz.data[np.newaxis, :, np.newaxis], (nt, 1, nx))
    da_dz = xarray.DataArray(
        dz,
        coords=[
            ('time', ds['time'].data),
            ('z', ds['z'].data),
            ('locations', ds['locations'].data)]
    )
    # attributes seem to not copy over when creating the new array
    for v in ['time', 'z', 'locations']:
        da_dz[v].attrs = ds[v].attrs
    return da_dz


class Segment:
    """One segment of a MOM6 open boundary.

    Note that MOM6 supports segments of any length,
    but here it is assumed that the segment spans an
    entire north, south, east, or west border.

    Attributes:
        num (int): segment identification number following MOM6 order (1-4).
        border (str): which border of the model grid the segment represents
            (north, south, east, or west).
        hgrid: (xarray.Dataset) dataset from opening ocean_hgrid.nc.
            Contains 'x', 'y', and 'angle_dx'.
        in_degrees: (bool): is angle_dx in hgrid in units of degrees (True)
            or radians (False)?
        segstr (str): string identifying the segment, used in variable and file names.
        output_dir (str): location to write data for the segment, and location to store
            xesmf weight files.
        regrid_dir (str): location to save xesmf Regridders. Defaults to output_dir.
        coords (xarray.Dataset): segment coordinates derived from hgrid
            (lon, lat, angle relative to true north).
        nx (int): Number of data points in the x direction.
        ny (int): Number of data points in the y direction.
    """

    def __init__(self, num, border, hgrid, in_degrees=True, output_dir='.',
                 regrid_dir=None):
        self.num = num
        self.border = border
        self.hgrid = hgrid.copy(deep=True)
        if in_degrees:
            self.hgrid['angle_dx'] = np.radians(self.hgrid['angle_dx'])
        check_angle_range(self.hgrid['angle_dx'])
        self.segstr = f'segment_{self.num:03d}'
        self.output_dir = output_dir

        if regrid_dir is None:
            self.regrid_dir = self.output_dir
        else:
            self.regrid_dir = regrid_dir

    @property
    def coords(self):
        if self.border == 'south':
            return xarray.Dataset({
                'lon': self.hgrid['x'].isel(nyp=0),
                'lat': self.hgrid['y'].isel(nyp=0),
                'angle': self.hgrid['angle_dx'].isel(nyp=0)
            })
        elif self.border == 'north':
            return xarray.Dataset({
                'lon': self.hgrid['x'].isel(nyp=-1),
                'lat': self.hgrid['y'].isel(nyp=-1),
                'angle': self.hgrid['angle_dx'].isel(nyp=-1)
            })
        elif self.border == 'west':
            return xarray.Dataset({
                'lon': self.hgrid['x'].isel(nxp=0),
                'lat': self.hgrid['y'].isel(nxp=0),
                'angle': self.hgrid['angle_dx'].isel(nxp=0)
            })
        elif self.border == 'east':
            return xarray.Dataset({
                'lon': self.hgrid['x'].isel(nxp=-1),
                'lat': self.hgrid['y'].isel(nxp=-1),
                'angle': self.hgrid['angle_dx'].isel(nxp=-1)
            })

    @property
    def nx(self):
        """Number of data points in the x-direction"""
        if self.border in ['south', 'north']:
            return len(self.coords['lon'])
        elif self.border in ['west', 'east']:
            return 1

    @property
    def ny(self):
        """Number of data points in the y-direction"""
        if self.border in ['south', 'north']:
            return 1
        elif self.border in ['west', 'east']:
            return len(self.coords['lat'])

    def to_netcdf(self, ds, varnames, suffix=None, additional_encoding=None):
        """Write data for the segment to file.

        Args:
            ds (xarray.Dataset): Segment dataset.
            varnames (str): Name to give the file (e.g. 'temp', 'salt').
            suffix (str, optional): Optional suffix to append to the filename
                (before .nc). Defaults to None.
        """
        for v in ds:
            ds[v].encoding['_FillValue']= 1.0e20
        fname = f'{varnames}_{self.num:03d}_{suffix}.nc' if suffix is not None else \
            f'{varnames}_{self.num:03d}.nc'
        # Set format and attributes for coordinates, including time if it does not
        # already have calendar attribute
        # (may change this to detect whether time is a time type or a float).
        # Need to include the fillvalue or it will be back to nan
        # encoding = {
        #     'time': dict(_FillValue=1.0e20),
        #     f'lon_{self.segstr}': dict(dtype='float64', _FillValue=1.0e20),
        #     f'lat_{self.segstr}': dict(dtype='float64', _FillValue=1.0e20)
        # }
        encoding = {}
        ds[f'lon_{self.segstr}'].encoding['dtype'] = 'float64'
        ds[f'lat_{self.segstr}'].encoding['dtype'] = 'float64'

        if 'calendar' not in ds['time'].attrs and 'modulo' not in ds['time'].attrs:
            # ds['time'].attrs['calendar'] = 'gregorian'
            # encoding.update({'time': dict(dtype='float64', _FillValue=1.0e20)})
            ds.time.encoding['calendar']='gregorian'
            ds.time.encoding['dtype'] = 'float64'
            ds.time.encoding['_FillValue'] = 1.0e20
        if additional_encoding is not None:
            encoding.update(additional_encoding)

        ds.to_netcdf(
            path.join(self.output_dir, fname),
            format='NETCDF3_64BIT',
            engine='netcdf4',
            encoding=encoding,
            unlimited_dims='time'
        )

    def expand_dims(self, ds):
        """Add a length-1 dimension to the variables in a boundary dataset or array.
        Named 'ny_segment_{self.segstr}' if the border runs west to east
            (a south or north boundary),
        or 'nx_segment_{self.segstr}' if the border runs north to south
            (an east or west boundary).

        Args:
            ds: boundary array with dimensions <time, (z or constituent), y, x>

        Returns:
            modified array with new length-1 dimension.
        """
        # having z or constituent as second dimension is optional,
        # so offset determines where to place
        # added dim
        if 'z' in ds.coords or 'constituent' in ds.dims:
            offset = 0
        else:
            offset = 1
        if self.border in ['south', 'north']:
            return ds.expand_dims(f'ny_{self.segstr}', 2-offset)
        elif self.border in ['west', 'east']:
            return ds.expand_dims(f'nx_{self.segstr}', 3-offset)

    def rename_dims(self, ds):
        """Rename dimensions to be unique to the segment.

        Args:
            ds (xarray.Dataset): Dataset that might contain 'lon', 'lat', 'z',
                and/or 'locations'.

        Returns:
            xarray.Dataset: Dataset with dimensions renamed to include the segment
                identifier and to match MOM6 expectations.
        """
        ds = ds.rename({
            'lon': f'lon_{self.segstr}',
            'lat': f'lat_{self.segstr}'
        })
        if 'z' in ds.coords:
            ds = ds.rename({
                'z': f'nz_{self.segstr}'
            })
        if self.border in ['south', 'north']:
            return ds.rename({'locations': f'nx_{self.segstr}'})
        elif self.border in ['west', 'east']:
            return ds.rename({'locations': f'ny_{self.segstr}'})

    def zeros(self, time, nz=0):
        """Create an appropriately shaped DataArray of zeros.
        Useful for things where the boundary is set to a constant.

        Args:
            time: Time coordinate to give the array.
            nz (int, optional): Length of the vertical dimension to give the array,
                if greater than 0. Defaults to 0.

        Returns:
            xarray.DataArray: Array of zeros.
        """
        nt = len(time)
        if nz > 0:
            return xarray.DataArray(
                np.zeros((nt, nz, self.ny, self.nx)),
                coords=[time, np.arange(nz), np.arange(self.ny), np.arange(self.nx)],
                dims=['time', f'nz_{self.segstr}',
                      f'ny_{self.segstr}', f'nx_{self.segstr}']
            )
        else:
            return xarray.DataArray(
                np.zeros((nt, self.ny, self.nx)),
                coords=[time, np.arange(self.ny), np.arange(self.nx)],
                dims=['time', f'ny_{self.segstr}', f'nx_{self.segstr}']
            )

    def add_coords(self, ds):
        """Add segment lat and lon coordinates to a dataset."""
        if self.border in ['south', 'north']:
            ds[f'lon_{self.segstr}'] = (
                (f'nx_{self.segstr}', ), self.coords['lon'].data
            )
            ds[f'lat_{self.segstr}'] = (
                (f'nx_{self.segstr}', ), self.coords['lat'].data
            )
        elif self.border in ['west', 'east']:
            ds[f'lon_{self.segstr}'] = (
                (f'ny_{self.segstr}', ), self.coords['lon'].data
            )
            ds[f'lat_{self.segstr}'] = (
                (f'ny_{self.segstr}', ), self.coords['lat'].data
            )
        return ds

    def regrid_velocity(
                self, usource, vsource,
                method='nearest_s2d', periodic=False, write=True,
                fill='b', rotate=True,
                uvar=None, vvar=None, **kwargs):
        """Interpolate velocity onto segment and (optionally) write to file.

        Args:
            usource (xarray.DataArray): Earth-relative u velocity on source grid.
            vsource (xarray.DataArray): Earth-relative v velocity on source grid.
            method (str, optional): Method recognized by xesmf to use to regrid.
                Defaults to 'nearest_s2d'.
            periodic (bool, optional): Whether the source grid is periodic
                (passed to xesmf). Defaults to False.
            write (bool, optional): After regridding, write the results to file.
                Defaults to True.
            fill (str, optional): Method to use for filling data horizontally
                (b for bfill or f for ffill).
            rotate(bool, optional): Rotate to the model grid, assuming input is
                on earth grid.
            uvar (str, optional): If provided, use this var from usource, and assume
                that coordinates are also provided in usource.
            vvar (str, optional): If provided, use this var from vsource, and assume
                that coordinates are also provided in vsource.
        Returns:
            xarray.Dataset: Dataset of regridded boundary data.
        """
        if not isinstance(usource, xarray.Dataset):
            usource = usource.to_dataset()

        if not isinstance(vsource, xarray.Dataset):
            vsource = vsource.to_dataset()

        # Horizontally interpolate velocity to MOM boundary.
        uregrid = reuse_regrid(
            usource,
            self.coords,
            method=method,
            locstream_out=True,
            periodic=periodic,
            filename=path.join(self.regrid_dir, f'regrid_{self.segstr}_u.nc'),
            reuse_weights=True
        )
        vregrid = reuse_regrid(
            vsource,
            self.coords,
            method=method,
            locstream_out=True,
            periodic=periodic,
            filename=path.join(self.regrid_dir, f'regrid_{self.segstr}_v.nc'),
            reuse_weights=True
        )

        if uvar is None:
            udest = uregrid(usource)
        else:
            udest = uregrid(usource[uvar])

        if vvar is None:
            vdest = vregrid(vsource)
        else:
            vdest = vregrid(vsource[vvar])

        # if lat and lon are variables in u/vsource, u/vdest will be dataset
        if isinstance(udest, xarray.Dataset):
            udest = udest.to_array().squeeze()
        if isinstance(vdest, xarray.Dataset):
            vdest = vdest.to_array().squeeze()

        xname = list(udest.dims)[-1]
        udest = udest.rename({xname: 'locations'})
        vdest = vdest.rename({xname: 'locations'})

        # Rotate velocities to be model-relative.
        if rotate:
            if self.border in ['south', 'north']:
                angle = self.coords['angle'].rename({'nxp': 'locations'})
            elif self.border in ['west', 'east']:
                angle = self.coords['angle'].rename({'nyp': 'locations'})
            udest, vdest = rotate_uv(udest, vdest, angle)

        ds_uv = xarray.Dataset({
            f'u_{self.segstr}': udest,
            f'v_{self.segstr}': vdest
        })

        ds_uv = fill_missing(ds_uv, fill=fill)

        # If time is singular, it can be lost from the dimensions, so add it back.
        if 'time' not in ds_uv.dims:
            ds_uv = ds_uv.expand_dims('time')

        # Need to transpose so that time is first,
        # so that it can be the unlimited dimension
        ds_uv = ds_uv.transpose('time', 'z', 'locations')

        # Add thickness
        dz = z_to_dz(ds_uv)
        ds_uv[f'dz_u_{self.segstr}'] = dz
        ds_uv[f'dz_v_{self.segstr}'] = dz

        ds_uv['z'] = np.arange(len(ds_uv['z']))

        ds_uv = self.expand_dims(ds_uv)

        ds_uv['lon'] = (('locations', ), self.coords['lon'].data)
        ds_uv['lat'] = (('locations', ), self.coords['lat'].data)

        ds_uv = self.rename_dims(ds_uv)

        if write:
            self.to_netcdf(ds_uv, 'uv', **kwargs)

        return ds_uv

    def regrid_tracer(
            self, tsource,
            method='nearest_s2d', periodic=False, write=True,
            fill='b', xdim='lon', ydim='lat',
            regrid_suffix='t', source_var=None, **kwargs):
        """Regrid a tracer onto segment and (optionally) write to file.

        Args:
            tsource (xarray.DataArray): Tracer data on source grid.
            method (str, optional): Method recognized by xesmf to use to regrid.
                Defaults to 'nearest_s2d'.
            periodic (bool, optional): Whether the source grid is periodic
                (passed to xesmf). Defaults to False.
            write (bool, optional): After regridding, write the results to file.
                Defaults to True.
            fill (str, optional): Method to use for filling data horizontally
                (b for bfill or f for ffill).
            xdim (str, optional): Name of the horizontal x dimension, defaults to 'lon'.
            ydim (str, optional): Name of the horizontal y dimension, defaults to 'lat'.
            regrid_suffix (str, optional): Suffix to add to xesmf weight file name.
                Useful when regridding multiple tracers from different datasets.
                Defaults to 't'.
            source_var (str, optional): If tsource is a dataset, this is
                the variable to regrid.
            **kwargs: additional keyword arguments passed to Segment.to_netcdf().

        Returns:
            xarray.Dataset: Dataset of regridded boundary data.
        """
        if source_var is None:
            if hasattr(tsource, 'name'):
                name = tsource.name
            elif isinstance(tsource, xarray.Dataset):
                name = find_datavar(tsource)
        else:
            name =  source_var

        if not isinstance(tsource, xarray.Dataset):
            tsource.name = name
            tsource = tsource.to_dataset()

        regrid = reuse_regrid(
            tsource,
            self.coords,
            method=method,
            locstream_out=True,
            periodic=periodic,
            filename=path.join(self.regrid_dir,
                               f'regrid_{self.segstr}_{regrid_suffix}.nc'),
            reuse_weights=True
        )
        tdest = regrid(tsource)

        if not isinstance(tdest, xarray.Dataset):
            tdest.name = name
            tdest = tdest.to_dataset()
        else:
            tdest = tdest.drop_vars([xdim, ydim], errors='ignore')

        xname = list(tdest.dims)[-1]
        tdest = tdest.rename({xname: 'locations'})

        if 'z' in tsource.coords:
            tdest = fill_missing(tdest, fill=fill)
            # Need to transpose so that time is first,
            # so that it can be the unlimited dimension
            tdest = tdest.transpose('time', 'z', 'locations')
            dz = z_to_dz(tdest)
            tdest[f'dz_{name}_{self.segstr}'] = dz
            tdest['z'] = np.arange(len(tdest['z']))
        else:
            tdest = fill_missing(tdest, zdim=None, fill=fill)
            # Need to transpose so that time is first,
            # so that it can be the unlimited dimension
            tdest = tdest.transpose('time', 'locations')

        tdest = self.expand_dims(tdest)

        tdest['lon'] = (('locations', ), self.coords['lon'].data)
        tdest['lat'] = (('locations', ), self.coords['lat'].data)

        tdest = self.rename_dims(tdest)
        tdest = tdest.rename({name: f'{name}_{self.segstr}'})

        if write:
            self.to_netcdf(tdest, name, **kwargs)

        return tdest

    def regrid_tidal_elevation(
                self, resource, imsource, time,
                method='nearest_s2d', periodic=False, write=True,
                **kwargs):
        """Regrid tidal elevation onto segment and (optionally) write to file.
        It is assumed that real (resource) and imaginary (imsource) components of the
        constituents have the same coordinates.

        Args:
            resource (xarray.DataArray): Real component of tidal elevation on
                source grid.
            imsource (xarray.DataArray): Imaginary component of tidal elevation on
                source grid.
            time: Time to add to dataset. Pass a length-1 array to keep it constant
                in time.
            method (str, optional): Method recognized by xesmf to use
                to regrid. Defaults to 'nearest_s2d'.
            periodic (bool, optional): Whether the source grid is periodic
                (passed to xesmf). Defaults to False.
            write (bool, optional): After regridding, write the results to file.
                Defaults to True.
            fill (str, optional): Method to use for filling data horizontally
                (b for bfill or f for ffill).
            **kwargs: additional keyword arguments passed to Segment.to_netcdf().

        Returns:
            xarray.Dataset: Dataset of regridded boundary data.
        """
        # Horizontally interpolate elevation components
        regrid = reuse_regrid(
            resource,
            self.coords,
            method=method,
            locstream_out=True,
            periodic=periodic,
            filename=path.join(self.regrid_dir, f'regrid_{self.segstr}_tidal_elev.nc'),
            reuse_weights=True
        )
        redest = regrid(resource)
        imdest = regrid(imsource)

        # Fill missing data.
        # Need to do this first because complex would get converted to real
        redest = fill_missing(redest, zdim=None)['hRe']
        imdest = fill_missing(imdest, zdim=None)['hIm']

        # todo: consolidate this
        xname = list(redest.dims)[-1]
        redest = redest.rename({xname: 'locations'})
        imdest = imdest.rename({xname: 'locations'})

        # Convert complex
        cplex = redest + 1j * imdest

        # Convert to real amplitude and phase.
        ds_ap = xarray.Dataset({
            f'zamp_{self.segstr}': np.abs(cplex)
        })
        # np.angle doesn't return dataarray
        ds_ap[f'zphase_{self.segstr}'] =  (
            ('constituent', 'locations'), -1 * np.angle(cplex) # radians
        )

        # Add time coordinate and transpose so that time is first,
        # so that it can be the unlimited dimension
        ds_ap, _ = xarray.broadcast(ds_ap, time)
        ds_ap = ds_ap.transpose('time', 'constituent', 'locations')

        ds_ap = self.expand_dims(ds_ap)

        ds_ap['lon'] = (('locations', ), self.coords['lon'].data)
        ds_ap['lat'] = (('locations', ), self.coords['lat'].data)

        ds_ap = self.rename_dims(ds_ap)

        if write:
            self.to_netcdf(ds_ap, 'tz', **kwargs)

        return ds_ap

    def regrid_tidal_velocity(
            self, uresource, uimsource, vresource, vimsource, time,
            method='nearest_s2d', periodic=False, write=True,
            **kwargs):
        """Regrid tidal velocity onto segment and (optionally) write to file.
        It is assumed that real and imaginary components of the
        individual u or v velocities have the same coordinates,
        but the u and v components may have separate coordinates.

        Args:
            uresource (xarray.DataArray): Real component of tidal u velocity on
                source grid.
            uimsource (xarray.DataArray): Imaginary component of tidal u velocity on
                source grid.
            vresource (xarray.DataArray): Real component of tidal v velocity on
                source grid.
            vimsource (xarray.DataArray): Imaginary component of tidal v velocity on
                source grid.
            time: Time to add to dataset. Pass a length-1 array to keep it constant
                in time.
            method (str, optional): Method recognized by xesmf to use
                to regrid. Defaults to 'nearest_s2d'.
            periodic (bool, optional): Whether the source grid is periodic
                (passed to xesmf). Defaults to False.
            write (bool, optional): After regridding, write the results to file.
                Defaults to True.
            fill (str, optional): Method to use for filling data horizontally
                (b for bfill or f for ffill).
            **kwargs: additional keyword arguments passed to Segment.to_netcdf().

        Returns:
            xarray.Dataset: Dataset of regridded boundary data.
        """
        urename = find_datavar(uresource)
        uimname = find_datavar(uimsource)
        vrename = find_datavar(vresource)
        vimname = find_datavar(vimsource)

        logger.info('Setting up regridders')
        regrid_u = reuse_regrid(
            uresource,
            self.coords,
            method=method,
            locstream_out=True,
            periodic=periodic,
            filename=path.join(self.regrid_dir, f'regrid_{self.segstr}_tidal_u.nc'),
            reuse_weights=True
        )

        regrid_v = reuse_regrid(
            vresource,
            self.coords,
            method=method,
            locstream_out=True,
            periodic=periodic,
            filename=path.join(
                self.regrid_dir, f'regrid_{self.segstr}_tidal_v.nc'),
            reuse_weights=True
        )

        logger.info('Regridding')
        # Interpolate each real and imaginary parts to segment.
        uredest = regrid_u(uresource)[urename]
        uimdest = regrid_u(uimsource)[uimname]
        vredest = regrid_v(vresource)[vrename]
        vimdest = regrid_v(vimsource)[vimname]

        # todo: consolidate this
        xname = list(uredest.dims)[-1]
        uredest = uredest.rename({xname: 'locations'})
        uimdest = uimdest.rename({xname: 'locations'})
        vredest = vredest.rename({xname: 'locations'})
        vimdest = vimdest.rename({xname: 'locations'})

        logger.info('Refilling missing data')
        # Fill missing data.
        # Need to do this first because complex would get converted to real
        uredest = fill_missing(uredest, zdim=None)
        uimdest = fill_missing(uimdest, zdim=None)
        vredest = fill_missing(vredest, zdim=None)
        vimdest = fill_missing(vimdest, zdim=None)

        # Convert to complex, remaining separate for u and v.
        ucplex = uredest + 1j * uimdest
        vcplex = vredest + 1j * vimdest

        logger.info('Rotating')
        # Convert complex u and v to ellipse,
        # rotate ellipse from earth-relative to model-relative,
        # and convert ellipse back to amplitude and phase.
        # There is probably a complicated trig identity for this? But
        # this works too.
        if self.border in ['south', 'north']:
            angle = self.coords['angle'].rename({'nxp': 'locations'})
        elif self.border in ['west', 'east']:
            angle = self.coords['angle'].rename({'nyp': 'locations'})
        SEMA, ECC, INC, PHA = ap2ep(ucplex, vcplex)  # noqa: N806

        # Rotate to the model grid by adjusting the inclination.
        # Requries that angle is in radians.
        # INC is np array but angle is xarray
        INC -= angle.data[np.newaxis, :]  # noqa: N806
        ua, va, up, vp = ep2ap(SEMA, ECC, INC, PHA)

        ds_ap = xarray.Dataset({
            f'uamp_{self.segstr}': ua,
            f'vamp_{self.segstr}': va
        })
        # up, vp aren't dataarrays
        ds_ap[f'uphase_{self.segstr}'] =  (('constituent', 'locations'), up)  # radians
        ds_ap[f'vphase_{self.segstr}'] =  (('constituent', 'locations'), vp)  # radians

        ds_ap, _ = xarray.broadcast(ds_ap, time)

        # Need to transpose so that time is first,
        # so that it can be the unlimited dimension
        ds_ap = ds_ap.transpose('time', 'constituent', 'locations')

        # Some things may have become missing during the transformation
        ds_ap = fill_missing(ds_ap, zdim=None)

        ds_ap = self.expand_dims(ds_ap)
        ds_ap['lon'] = (('locations', ), self.coords['lon'].data)
        ds_ap['lat'] = (('locations', ), self.coords['lat'].data)

        ds_ap = self.rename_dims(ds_ap)

        if write:
            logger.info('Writing')
            self.to_netcdf(ds_ap, 'tu', **kwargs)

        return ds_ap
