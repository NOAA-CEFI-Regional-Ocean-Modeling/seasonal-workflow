# seasonal-workflow

## Overview

This repository contains scripts and workflow files for setting up and running seasonal
forecasts for NOAA's Changing Ecosystems and Fisheries Initiative (CEFI).
The repository is primarily intended for CEFI team members working on NOAA's
Research and Development HPC systems, but it is available here for anyone to reference and use
(see disclaimer below). However, large parts of this readme and most filesystem references
in the scripts are specific to CEFI HPC resources, and no support will be provided
for using these workflows outside of the NOAA/CEFI environment.

The repository is organized as follows:
+ **analysis_postprocess:** contains a script for combining and region-averaging one or
more chunks of the nudged analysis simulation.
+ **analysis_setup:** scripts for creating the forcing files for the nudged analysis simulation.
+ **docs:** documents written about the workflow. Currently contains one document describing
the extended logistic regression post-processing method.
+ **examples:** contains examples of how to analyze and plot the forecast output.
+ **forecast_postprocess:** contains several scripts for combining and post-processing the retrospective and real-time forecasts
    + postprocess_extract_fields.py extracts netcdf files from raw history tar files and
     adds some additional coordinates and metadata.
    + postprocess_combine_fields.py takes the extracted netcdf files, merges them together,
     and calculates climatology and anomalies.
    + postprocess_combine_new_forecasts.py does the same but only for ensemble members from
     one real-time forecast. It depends on the climatology calculated previously.
    + postprocess_region_average.py takes the combined model output and calculates
     averages over predefined region masks.
    + postprocess_logreg.py calculates coefficients for extended logistic regression
     to estimate the forecast probability distribution.
    + postprocess_cleanup.py removes raw model data cached by other post-processing scipts
    + postprocess_extracted_to_region_average.py takes each extracted model data file
     and calculates the region average. In some cases this is less computationally
     expensive.
    + postprocess_combine_region_average.py combines the above regional averages.
+ **forecast_setup:** contains scripts for setting up the forecast forcing, including
boundary and runoff daily climatologies, global model forecast atmosphere, and
snapshot initial conditions.
+ **logs:** empty directory where some logs could be placed.
+ **src:** contains the `workflow_tools` python module that is used by many scripts.
+ **workflows:** contains UFS yaml-style workflows for setting up and post-processing the
retrospective and real-time forecasts.
+ **xml:** contains FRE xml files used to actually run the model forecasts
+ **top level config files:** includes sample configuration files for the Northwest
Atlantic seasonal forecasts as well as various config files for python tooling.

## Basic retrospective forecast steps (with UFS/rocoto workflow)

Workflow files that were used to create the Northwest Atlantic retrospective and real-time
forecasts are provided in the `workflows` directory. These workflow files are
written in [UFS-style yaml](https://uwtools.readthedocs.io/en/main/sections/user_guide/yaml/rocoto.html),
and are converted to xmls that are run by [Rocoto](https://christopherwharrop.github.io/rocoto/).

0. Setup and run the "analysis" simulation that will provide the initial conditions (see basic forecast steps without workflow below).
1. Create a configuration yaml file (use `config_nwa12_cobalt.yaml` as a template).
2. Modify the UFS yaml in `workflows/retrospective_workflow.yaml`
    + Change the cycledef spec: for example use `"0 0 1 7 1994-2023"` to run on every July 1 from 1994--2023
    + Change all paths referencing `acr` to your username
3. Create the rocoto xml from the yaml:
    + On GFDL analysis: `/home/Andrew.C.Ross/.conda/envs/uwtools/bin/uw rocoto realize --config-file retrospective_workflow.yaml --output-file retrospective_workflow.xml`
    + Load a conda environment if the above doesn't work: `module load miniforge; conda activate /home/Andrew.C.Ross/.conda/envs/uwtools`
4. Start the workflow:
    + On GFDL analysis: `/home/acr/git/rocoto/bin/rocotorun -d retrospective_workflow.db -w retrospective_workflow.xml`
    + Repeat the above command to check on the workflow and launch newly possible jobs
    + Or use `watch -n 300 "paste command above here"` to automatically run every 300 s
5. Check on the workflow:
    + On GFDL analysis:  `/home/acr/git/rocoto/bin/rocotostat -d retrospective_workflow.db -w retrospective_workflow.xml`
6. Launch a forecast run (on Gaea)
    1. Create a common xml using `xml/NWA12_cobalt_forecast_common.xml` as a template
    2. Create a forecast-specific xml
        1. `module load python/3.11`
        2. `python write_forecast_xml.py YOUR_COMMON_XML.xml FORECAST_YEAR FORECAST_MONTH` (fill in all-caps words)
    3. Use fremake to compile the model if you haven't already (all forecasts use the same executable, so this only needs to be done once. If you use the same stem and compile experiment name as the analysis run this can also be skipped.)
    4. Run ensemble members from the xml as usual using `frerun`.

## Basic forecast steps (without UFS/rocoto workflow)

Steps:

0. Create a configuration yaml file.

1. Create data for the nudged analysis run
    + Set up other data (ERA5, GLORYS boundary conditions, etc) as usual. Use the tools in `analysis_setup` or from other sources.
    + Nudging time scale: `write_damping_file.py`
    + Monthly average T and S to nudge to: `write_nudging_data.py`

2. Run the nudged analysis simulation
    + See [this link](https://github.com/NOAA-CEFI-Regional-Ocean-Modeling/regional-mom6-xml/blob/5969a267989f7f661d8e604cc2f666011a3f582a/NWA12/NWA12_physics.xml#L636) for an example physics-only XML experiment with nudging
    + See xml/diag_table_snapshots for an example diag table to use to save monthly snapshots from the nudged simulation that can be used as initial conditions.

4. Set up a forecast simulation
    + Atmospheric forcing from a SPEAR forecast: `write_spear_atmos.py`
    + River climatology: `write_river_climo.py`
    + Boundary condition climatology: `write_boundary_climo.py`
    + Initial conditions derived from the nudged run: `write_ics_from_snapshot.py`

5. Run many forecast simulations
    + Build a template XML based on NWA12_forecast_common.xml
        - The template XML contains XML data that is common to all experiments, with places to fill in the experiment start year and month.
        - Each ensemble member is its own experiment. Each member inherits shared data from a base experiment and adds its own unique files.
        - The example NWA12_forecast_common.xml file contains experiments using both climatological open boundary conditions and SPEAR-derived OBCs.
        - The template XML is included by the forecast XMLs. Any change to the template XML will automatically propagate to the forecast XMLs.
    + Generate an XML for the forecast start year and month.
        - `python write_forecast_xml.py NWA12_forecast_common.xml 1993 03` will create NWA12_forecast_1993_03.xml which contains data for a forecast starting on 1993-03-01, using the template file NWA12_forecast_common.xml.
        - The ensemble member experiments in the generated XML can be frerun-ed.
        - The generated XML can also be used to compile the model if needed (only needs to be done once).

6. Post-process the forecast data
    + Extract some 2D fields from all available history tar files: `postprocess_extract_fields.py`
    + Combine the extracted data files together and calculate lead-dependent climatologies and anomalies: `postprocess_combine_fields.py`

### Custom python setup (on GFDL analysis)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and add it to your path.

Then,
```sh
module load python/3.13
module load esmf/8.8.1
uv sync
source .venv/bin/activate.csh # or without the .csh depending on shell
```

### Loading python and required modules (on GFDL analysis)

```sh
module load nco/5.3.3
module load cdo/2.5.2
module load gcp hsm/1.3.0
module load python/3.13
module load esmf/8.8.1
source .venv/bin/activate.csh # or without the .csh depending on shell
```

## Disclaimer

The United States Department of Commerce (DOC) GitHub project code is provided on an 'as is' basis and the user assumes responsibility for its use. The DOC has relinquished control of the information and no longer has responsibility to protect the integrity, confidentiality, or availability of the information. Any claims against the Department of Commerce stemming from the use of its GitHub project will be governed by all applicable Federal law. Any reference to specific commercial products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or imply their endorsement, recommendation or favoring by the Department of Commerce. The Department of Commerce seal and logo, or the seal and logo of a DOC bureau, shall not be used in any manner to imply endorsement of any commercial product or activity by DOC or the United States Government.

This project code is made available through GitHub but is managed by NOAA-GFDL at [https://www.gfdl.noaa.gov](https://www.gfdl.noaa.gov).
