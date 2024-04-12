from dataclasses import dataclass
import datetime as dt
from getpass import getuser
import numpy as np
from pathlib import Path
import subprocess
import xarray


# Expect, and only extract, these variables from the given domain
_DOMAIN_VARIABLES = {
    'ocean_month': ['tos', 'tob', 'sos', 'MLD_003'] # ssh or zos
}

# Using /vftmp/$USER as a cache
VFTMP = Path('/vftmp') / getuser()

@dataclass
class ForecastRun:
    ystart: int
    mstart: int
    ens: int
    domain: str = 'ocean_month'

    @property
    def archive_name(self):
        """
        Name of the tar file stored on archive.
        """
        return f'{self.ystart}{self.mstart:02d}01.nc.tar'
    
    @property 
    def tmp_dir(self):
        """
        Location on vftmp to cache extracted data.
        """
        return VFTMP / 'forecast_data' / f'e{self.ens:02d}'

    @property
    def tar_name(self):
        """
        Name of the file in the tar file to extract.
        """
        return f'{self.ystart}{self.mstart:02d}01.{self.domain}.nc'

    @property
    def out_name(self):
        """
        Name to give the final processed file.
        """
        return f'{self.ystart}-{self.mstart:02d}-e{self.ens:02d}.{self.domain}.nc'
    
    def format_history(self, template):
        """
        Take a string giving a template for the name of a single forecast's
        history directory on archive, and format it with the current forecast's
        year, month, and ensemble member.
        """
        return Path(template.format(year=self.ystart, month=self.mstart, ensemble=self.ens))
    
    def extract_from_archive(self, history):
        """
        Given the formatted location of the history directory,
        extract the desired file from the tar file.
        """
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        cmd = f'tar xf {(history / self.archive_name).as_posix()} -C {self.tmp_dir.as_posix()} ./{self.tar_name}'
        print(cmd)
        subprocess.run([cmd], shell=True, check=True)

    def process_file(self, outfile, infile=None):
        if infile is None:
            infile = self.tmp_dir / self.tar_name
        print(f'process_file({infile})')
        ds = xarray.open_dataset(infile)[_DOMAIN_VARIABLES[self.domain]]
        ds['ens'] = int(self.ens)
        ds['mstart'] = int(self.mstart)
        ds['ystart'] = int(self.ystart)
        ds['init'] = dt.datetime(int(self.ystart), int(self.mstart), 1)   
        ds['lead'] = (('time', ), np.arange(len(ds['time'])))
        ds.to_netcdf(outfile)
        ds.close()


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    from yaml import safe_load
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config')
    parser.add_argument('-d', '--domain', type=str, default='ocean_month')
    parser.add_argument('-r','--rerun', action='store_true')
    args = parser.parse_args()
    with open(args.config, 'r') as file: 
        config = safe_load(file)

    first_year = config['forecasts']['first_year']
    last_year = config['forecasts']['last_year']
    nens = config['forecasts']['ensemble_size']
    outdir = Path(config['filesystem']['model_output_data']) / 'extracted' / args.domain
    outdir.mkdir(exist_ok=True, parents=True)

    files_to_dmget = []

    for ystart in range(first_year, last_year+1):
        for mstart in config['forecasts']['months']:
            for ens in range(1, nens+1):
                run = ForecastRun(
                    ystart=ystart, 
                    mstart=mstart, 
                    ens=ens,
                    domain=args.domain
                )
                # Check if a processed file exists
                if not (outdir / run.out_name).is_file() or args.rerun:
                    # Check if an extracted data file exists
                    if not (run.tmp_dir / run.tar_name).is_file():
                        # Check if the raw data exists in archive
                        archive = run.format_history(config['filesystem']['forecast_history'])
                        if (archive / run.archive_name).is_file():
                            files_to_dmget.append((archive / run.archive_name).as_posix())
                        else:
                            print(f'{(archive / run.archive_name).as_posix()} not found in archive')

    if len(files_to_dmget) > 0:
        print(f'dmgetting {len(files_to_dmget)} files')
        subprocess.run([f'dmget {" ".join(files_to_dmget)}'], shell=True, check=True)
    else:
        print('No files to dmget')

    for ystart in range(first_year, last_year+1):
        for mstart in config['forecasts']['months']:
            for ens in range(1, nens+1):
                run = ForecastRun(
                    ystart=ystart, 
                    mstart=mstart, 
                    ens=ens,
                    domain=args.domain
                )
                outfile = outdir / run.out_name
                # Check if a processed file exists
                if not outfile.is_file() or args.rerun:
                    # Check if an extracted data file exists
                    if (run.tmp_dir / run.tar_name).is_file():
                        run.process_file(outfile)
                    else:
                        # Check if the raw data exists in archive
                        archive = run.format_history(config['filesystem']['forecast_history'])
                        tarpath = archive / run.archive_name
                        if (archive / run.archive_name).is_file():
                            run.extract_from_archive(archive)
                            run.process_file(outfile)
                        else:
                            print(f'{(archive / run.archive_name).as_posix()} not found in archive')
