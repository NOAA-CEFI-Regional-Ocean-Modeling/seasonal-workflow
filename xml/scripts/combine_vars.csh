#!/bin/tcsh -f
#SBATCH --job-name=combine_files
#SBATCH --partition=analysis
#SBATCH --output=%x.o%j
#SBATCH --time=05:00:00
#SBATCH --ntasks=1

##---- VARIABLES SET BY FREPP ----#
set in_data_dir
set argu
##---- END VARIABLES SET BY FREPP ----#
# Get options for script
while ($#argu > 0)
    switch ($argu[1])
        case -c:
            shift argu
            set component = "$argu[1]"
            breaksw
        case -v:
            shift argu
            set vars = "$argu[1]"
            set variables  = ($vars:as/,/ /)
            set copyvar = $variables[1] 
            shift variables
            breaksw
        case -s:
            shift argu
            set start_y = "$argu[1]"
            breaksw
        case -m:
            shift argu
            set start_m = "$argu[1]"
            breaksw
        case -e:
            shift argu
            set end_y = "$argu[1]"
            breaksw
        case -n:
            shift argu
            set end_m = "$argu[1]"
            breaksw
        case -d:
            shift argu
            set extract_dir = "$argu[1]"
            breaksw
        default:
            echo "Invalid option: $argu[1]" >&2
            exit 1
    endsw
    shift argu
end

# Get ensemble number from location of data dir
set ensemble = `echo $in_data_dir | awk '{split($0,a,"/"); print a[7]}' | awk '{split($0,b,"-"); print b[3]}'`

# Make a copy of an arbitrary variable to hold data for all the variables. 
module load nco
nccopy ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}.${copyvar}.nc ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc
# NOTE: Above line retains the netcdf_classic format that the model outputs. To change the format to netcdf4, add the -4 flag

# Iterate through the other variables, appending their data to file holding time series for all variables
foreach var ($variables) 
    ncks -A -h ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}.${var}.nc ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc
end

# Get rid of extraneous variables and copy data over to extract_dir
ncks -x -h -v average_DT,average_T1,average_T2,nv,time_bnds ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc ${extract_dir}/${start_y}-${start_m}-${ensemble}.${component}.nc
