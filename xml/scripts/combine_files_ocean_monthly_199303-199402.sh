#!/bin/tcsh -f
#SBATCH --job-name=combine_files
#SBATCH --partition=analysis
#SBATCH --output=%x.o%j
#SBATCH --time=05:00:00
#SBATCH --ntasks=1
#SBATCH --chdir=$HOME

##---- VARIABLES SET BY FREPP ----#
set in_data_dir='/archive/Utheri.Wagura/fre/NWA/2024_04_update/NWA12_forecast_2024_04_1993-03-e01/gfdl.ncrc5-intel22-prod/pp/ocean_month/ts/monthly/1yr'    
##---- END VARIABLES SET BY FREPP ----#
set component='ocean_month'
set copyvar='MLD_003'

if ( $#argv == 2 ) then
    if ( "$argv[1]" == "-e" ) then
        set ensemble="${argv[2]}"
    endif
else
    set ensemble=0
endif


# Make a copy of an arbitray variable to hold data for all the variables. 
#module load nco
#nccopy ${in_data_dir}/${component}.199303-199402.${copyvar}.nc ${in_data_dir}/${component}.199303-199402-e${ensemble}.nc
echo ${in_data_dir}/${component}.199303-199402.${copyvar}.nc
nccopy ${in_data_dir}/${component}.199303-199402.${copyvar}.nc ${in_data_dir}/${component}.199303-199402.nc
# NOTE: Above line retains the netcdf_classic format that the model outputs. To change the format to netcdf4, add the -4 flag

# Iterate through the other variables, appending their data to file holding time series for all variables
set variables=(tob tos sos ssh)
# TODO: figure out why history is still included inspite of -H flag
foreach var ($variables) 
    #ncks -A -H ${in_data_dir}/${component}.199303-199402.${var}.nc ${in_data_dir}/${component}.199303-199402-e${ensemble}.nc
    ncks -A -h ${in_data_dir}/${component}.199303-199402.${var}.nc ${in_data_dir}/${component}.199303-199402.nc
end

# Place all files in a single extracted directory in order to facilitate combining data across ensembles
#cp ${in_data_dir}/${component}.199303-199402-e${ensemble}.nc /archive/Utheri.Wagura/fre/NWA/2024_04_update/extracted
