import datetime as dt

import matlab.engine
import numpy as np
import xarray

print('Starting matlab')
eng = matlab.engine.start_matlab()
s = eng.genpath('/home/Andrew.C.Ross/git/nwa12/setup/boundary/ESPER-main')
eng.addpath(s, nargout=0)

glorys_z = xarray.open_dataset(
    '/work/acr/glorys/GLOBAL_MULTIYEAR_PHY_001_030/depths.nc'
).depth[0:-1]  # last depth is dropped when writing BCs
nz = len(glorys_z.values)

desired_vars = np.array([1, 2], dtype='int')
eng.workspace['desired_vars'] = desired_vars
predictor_types = np.array([1, 2], dtype='int')
eng.workspace['predictor_types'] = predictor_types
equations = np.array([8], dtype='int')
eng.workspace['equations'] = equations

for segment in [1, 2, 3]:
    print(f'Segment {segment:03d}')
    segstr = f'_segment_{segment:03d}'
    year_data = []
    for yr in range(1992, 2027):
        print(yr)
        # temporary fix for partial years
        fileyear = int(np.clip(yr, 1993, 2025))
        timeslice = slice(f'{fileyear}-01-01', f'{fileyear}-12-31')
        print('Loading data')
        salt = xarray.open_dataset(
            f'/work/acr/mom6/nwa12/analysis_input_data/boundary/so_{segment:03d}_{fileyear}.nc'
        )
        temp = xarray.open_dataset(
            f'/work/acr/mom6/nwa12/analysis_input_data/boundary/thetao_{segment:03d}_{fileyear}.nc'
        )
        ave_salt = salt['so' + segstr].sel(time=timeslice).mean('time')
        ave_temp = temp['thetao' + segstr].sel(time=timeslice).mean('time')
        lat = salt['lat' + segstr]
        lon = salt['lon' + segstr]
        ny = len(lat)
        nx = len(lon)
        out_coords = np.vstack(
            [
                np.vstack([lon.values, lat.values, np.repeat(z, nx)]).T
                for z in glorys_z.values
            ]
        )
        pred_vars = np.vstack(
            [
                np.vstack([ave_salt.squeeze()[i, :], ave_temp.squeeze()[i, :]]).T
                for i in range(nz)
            ]
        )
        eng.workspace['output_coords'] = out_coords
        eng.workspace['pred_vars'] = pred_vars

        est_dates = np.array([[yr + 0.5]], dtype='float64')
        eng.workspace['est_dates'] = est_dates
        esper_result = eng.eval(
            "ESPER_LIR(desired_vars, output_coords, pred_vars, predictor_types, 'Equations', equations, 'EstDates', est_dates)"  # noqa: E501
        )

        alk = np.array(esper_result['TA']).reshape([-1, nz], order='F') * 1e-6
        dic = np.array(esper_result['DIC']).reshape([-1, nz], order='F') * 1e-6

        h_dims = ['nx' + segstr, 'ny' + segstr]
        long_dim = (
            h_dims[0]
            if ave_temp.sizes[h_dims[0]] > ave_temp.sizes[h_dims[1]]
            else h_dims[1]
        )
        short_dim = next(d for d in h_dims if d != long_dim)
        z_dim = 'nz' + segstr

        ds = xarray.Dataset(
            {
                'alk' + segstr: ((long_dim, z_dim), alk),
                'dic' + segstr: ((long_dim, z_dim), dic),
            },
            coords={long_dim: ave_temp[long_dim], z_dim: ave_temp[z_dim]},
        )
        ds = ds.ffill(z_dim)
        ds = ds.expand_dims(dim=['time', short_dim])
        ds['lat' + segstr] = temp['lat' + segstr]
        ds['lon' + segstr] = temp['lon' + segstr]
        ds['dz_alk' + segstr] = (
            temp['dz_thetao' + segstr].isel(time=0).drop_vars('time')
        )
        ds['dz_dic' + segstr] = (
            temp['dz_thetao' + segstr].isel(time=0).drop_vars('time')
        )
        ds['time'] = [dt.datetime(yr, 7, 2)]
        year_data.append(ds)
        salt.close()
        temp.close()

    all_years = xarray.concat(year_data, dim='time')
    all_years = all_years.transpose('time', 'nz' + segstr, 'ny' + segstr, 'nx' + segstr)
    if 'calendar' in all_years['time'].attrs:
        del all_years['time'].attrs['calendar']
    encoding = {
        'time': {'calendar': 'gregorian', 'dtype': 'float64', '_FillValue': 1.0e20}
    }
    all_years.to_netcdf(
        f'/work/acr/mom6/nwa12/analysis_input_data/boundary/esper_glorys_{segment:03d}.nc',
        unlimited_dims='time',
        encoding=encoding,
    )

eng.quit()
# TODO: merge using something like:
# cp esper_glorys_001.nc esper_glorys_vyyyymmdd.nc
# ncks -A esper_glorys_002.nc esper_glorys_vyyyymmdd.nc
# ncks -A esper_glorys_003.nc esper_glorys_vyyyymmdd.nc
