#!/bin/bash
source $MODULESHOME/init/sh
module load python/3.13
module load esmf/8.8.1
module load nco/5.3.3
module load cdo/2.5.2
module load gcp hsm/1.3.0
source /home/acr/git/seasonal-workflow/.venv/bin/activate

# Use the current date for guessing the forecast initialization date
# when the cyclestr is offset.
export now_month=`date +%m`
export now_year=`date +%Y`

# conda activate /nbhome/acr/python/envs/medpy311_20241024