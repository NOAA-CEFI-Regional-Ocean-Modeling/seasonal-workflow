#!/bin/tcsh -f
#SBATCH --job-name=combine_files_last_ensemble
#SBATCH --partition=analysis
#SBATCH --output=%x.o%j
#SBATCH --time=05:00:00
#SBATCH --ntasks=1

##---- VARIABLES SET BY FREPP ----#
set in_data_dir
set argu
set frexml
set descriptor
##---- END VARIABLES SET BY FREPP ----#

# Save command line arguments to argu if running script outside of fre
if ($#argv) set argu = ($argv:q)

# Set vars from command line args
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
	case -f:
	    shift argu
	    set config_file = "$argu[1]"
	    breaksw
	case -r
	    shift argu
	    set scripts_dir = "$argu[1]"
	    breaksw
        default:
            echo "Invalid option: $argu[1]" >&2
            exit 1
    endsw
    shift argu
end

# Get ensemble number from in_data_dir, get pp script dir from xml path
set ensemble = `echo $descriptor | grep -o -m 1 'e[0-9][0-9]'`
set ens_num = `echo $ensemble | sed 's/e//'`
set xml_dir = ${frexml:h}

# Make a copy of an arbitrary variable to hold data for all the variables. 
module load nco
if ( -f ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc ) then
    rm ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc
endif 
nccopy ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}.${copyvar}.nc ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc
# NOTE: Above line retains the netcdf_classic format that the model outputs. To change the format to netcdf4, add the -4 flag

# Iterate through the other variables, appending their data to file holding time series for all variables
foreach var ($variables) 
    ncks -A -h ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}.${var}.nc ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc
end

# Get rid of extraneous variables and copy data over to extract_dir
if ( ! -d ${extract_dir}/${component} ) then
    echo "ERROR: Make sure all combined netCDF files for previous ensembles exist before running last ensemble"
    exit 1
endif

# NOTE: ncks will fail if output file already exists, so rm file before running it
if ( -f ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}.nc ) then
    rm ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}.nc
endif 

ncks -x -h -v average_DT,average_T1,average_T2,nv,time_bnds ${in_data_dir}${component}.${start_y}${start_m}-${end_y}${end_m}-${ensemble}.nc ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc

# Add necessary dimensions to file
ncap2 -A -h -s 'defdim("lead",$time.size) ; lead[$time]=array(0,1,$time)' ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc
ncap2 -A -h -s 'defdim("member",1)' ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc
ncap2 -A -h -s "member=${ens_num}" ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc
ncap2 -A -h -s 'defdim("init",1)' ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc
ncap2 -A -h -s "init = 0 " ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc 
ncatted -h -a units,lead,o,c,"months" ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc 
ncatted -h -a calendar,init,o,c,"proleptic_gregorian" ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc
ncatted -h -a units,init,o,c,"days since ${start_y}-${start_m}-01 00:00:00" ${extract_dir}/${component}/${start_y}-${start_m}-${ensemble}.${component}_wrong_coords.nc 

# Edit metadata across all files to prepare netcdf files for postprocess_combine_fields.py script
module load miniforge
conda activate /nbhome/Utheri.Wagura/.conda/envs/seasonalenv
python ${scripts_dir}/edit_coordinates.py -c ${config_file} -m ${start_m} -d ${component} 
rm ${extract_dir}/${component}/*_wrong_coords.nc

# Create forecast and climatology after waiting for files to take on full dimensions
python ${xml_dir:h}/postprocess_combine_fields.py -c ${config_file}
