import xarray
import numpy as np

ds = xarray.open_dataset("/work/acr/mom6/nwa12/forecast_output_data/climatology_ocean_month_1993_2019.nc")
dates = ["2020-9","2020-10","2020-11","2020-12","2021-1","2021-2","2021-3","2021-4","2021-5","2021-6","2021-7","2021-8"]
ds['time'] = (('lead'),dates)
ds = ds.swap_dims({'time':'lead'})
ds = ds.sel(month=1, drop=True)
ds.to_netcdf('/work/Utheri.Wagura/extracted/climatology_ocean_month_1993_2019.nc', unlimited_dims='time')
