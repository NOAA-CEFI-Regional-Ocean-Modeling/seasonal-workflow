#!/bin/tcsh
#SBATCH --job-name=combine_files
#SBATCH --partition=analysis
#SBATCH --output=%x.o%j
#SBATCH --time=05:00:00
#SBATCH --ntasks=1
#SBATCH --chdir=$HOME

##---- VARIABLES SET BY FREPP ----#
set in_data_dir    
##---- END VARIABLES SET BY FREPP ----#
set component='ocean_daily'
set copyvar='ssh_max'

# Make a copy of an arbitray variable to hold data for all the variables. 
module load nco
cp ${in_data_dir}/${component}.199303-199402.${copyvar}.nc ${in_data_dir}/${component}.199303-199402.nc
# NOTE: Above line retains the netcdf_classic format that the model outputs. To change the format to netcdf4, add the -4 flag

# Iterate through the other variables, appending their data to file holding time series for all variables
set variables=(tob tos ssh)
# TODO: figure out why history is still included inspite of -H flag
foreach var ($variables) 
	ncks -A -H ${in_data_dir}/${component}.199303-199402.${var}.nc ${in_data_dir}/${component}.199303-199402.nc
end
