#!/bin/tcsh -f
#SBATCH --job-name=combine_files
#SBATCH --partition=analysis
#SBATCH --output=%x.o%j
#SBATCH --time=05:00:00
#SBATCH --ntasks=1
#SBATCH --chdir=$HOME

##---- VARIABLES SET BY FREPP ----#
set in_data_dir
##---- END VARIABLES SET BY FREPP ----#
set component='ocean_month'
set copyvar='MLD_003'
set start_y='2020'
set start_m='09'
set end_y='2021'
set end_m='08'
set extract_dir='/work/Utheri.Wagura/extracted'

# Get ensemble number from location of data dir
set ensemble = `echo $in_data_dir | awk '{split($0,a,"/"); print a[7]}' | awk '{split($0,b,"-"); print b[3]}'`

# Make a copy of an arbitrary variable to hold data for all the variables. 
module load nco
nccopy ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}.${copyvar}.nc ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc
# NOTE: Above line retains the netcdf_classic format that the model outputs. To change the format to netcdf4, add the -4 flag

# Iterate through the other variables, appending their data to file holding time series for all variables
set variables=(tob tos sos ssh)
foreach var ($variables) 
    ncks -A -h ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}.${var}.nc ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc
end

# Get rid of extraneous variables before copying data over
#ncks -C -O -x -h -v average_DT,average_T1,average_T2,nv,time_bnds ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc

# Place all files in a single extracted directory in order to facilitate combining data across ensembles
nccopy ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc ${extract_dir}/${start_y}-${start_m}-${ensemble}.${component}.nc
