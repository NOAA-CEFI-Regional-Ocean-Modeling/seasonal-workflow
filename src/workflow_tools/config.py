from pathlib import Path
from typing import Annotated, Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from yaml import safe_load


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

    def model_post_init(self, _: Any) -> None:
        for k, v in vars(self).items():
            # Note this does not check lists of paths
            if isinstance(v, Path):
                # Warn if path doesn't exist, as long as it's
                # also not expected to be on Gaea:
                if not v.exists() and not v.is_relative_to('/gpfs'):
                    logger.warning('path {v} for setting {k} does not exist', k=k, v=v)


class RetrospectiveForecasts(StrictModel):
    first_year: int
    last_year: int
    months: list[int]
    ensemble_size: Annotated[int, Field(ge=1)]


class NewForecasts(StrictModel):
    ensemble_size: int


class Climatology(StrictModel):
    first_year: int
    last_year: int


class Domain(StrictModel):
    south_lat: Annotated[float, Field(ge=-90.0)]
    north_lat: Annotated[float, Field(le=90.0)]
    west_lon: Annotated[float, Field(ge=-360.0)]
    east_lon: Annotated[float, Field(le=360.0)]
    hgrid_file: Path
    ocean_mask_file: Path
    ocean_static_file: Path
    boundaries: dict[int, str]
    hgrid_angle_is_degrees: bool


class Regions(StrictModel):
    mask_file: Path
    names: list[str]


class InterimData(StrictModel):
    ERA5: Path
    GLORYS_reanalysis: Path
    GLORYS_analysis: Path
    GloFAS_ldd: Path
    GloFAS_v4: str
    GloFAS_interim: str
    GloFAS_interim_monthly: str
    GloFAS_extension_climatology: Path


class Filesystem(StrictModel):
    forecast_input_data: Path
    nowcast_input_data: Path
    forecast_output_data: Path
    gaea_input_data: Path
    yearly_river_files: str
    open_boundary_files: Path
    glorys_interpolated: Path
    interim_data: InterimData
    analysis_history: Path
    analysis_extensions: list[Path] | None = []
    nowcast_history: str
    forecast_history: str
    combined_name: str


class Config(StrictModel):
    name: str
    retrospective_forecasts: RetrospectiveForecasts
    new_forecasts: NewForecasts
    snapshots: list[str]
    climatology: Climatology
    domain: Domain
    regions: Regions
    variables: dict[str, list[str]]
    filesystem: Filesystem
    model_config = ConfigDict(extra='forbid')


def load_config(config_path: str | Path) -> Config:
    """Load and parse the YAML configuration file."""
    with open(config_path) as f:
        data = safe_load(f)
    return Config.model_validate(data)


if __name__ == '__main__':
    config = load_config('config_nwa12_cobalt.yaml')
    print(config.model_dump_json(indent=2))
