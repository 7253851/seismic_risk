# Input data requirements

Input data are not distributed with this repository (see the data-availability section of the main README).
Before running the model, create a `data/` folder in the repository root and place the inputs as listed below.
Paths in the code are relative to the repository root; exact file names are given in `project/code/paths.py`
and in each module's `config.json`. A Chinese version is in [DATA_zh.md](DATA_zh.md).

| Folder | Contents | Used for | Availability |
| --- | --- | --- | --- |
| `data/buildings/` | Building footprint polygons with unique building IDs; building-height grid (CNBH-10m) | Spatial unit for hazard, vulnerability, exposure and risk | Footprints: restricted (vectorised from Tianditu imagery); CNBH-10m: public |
| `data/TSX_PS/` | TerraSAR-X ascending/descending PS points (annual rate and time series) and vertical displacement-rate raster | Building deformation indicators, IBSI, InSAR discussion experiment | Restricted (DLR licence) |
| `data/GNSS/` | Daily N/E/U solutions and position of the continuous GNSS station in the study area | InSAR validation | On request |
| `data/faults/` | Regional active-fault traces and literature attributes | Hazard scenarios, maps | Public (CAFD and cited literature) |
| `data/earthquakes/` | Historical earthquake catalogue | Hazard and study-area maps | Public (China Earthquake Networks Center) |
| `data/vs30/` | Vs30 site-condition raster | Site amplification | Public (Mainland China Vs30 dataset) |
| `data/dem/` | Digital elevation model | Terrain, hillshade | Public (AW3D30) |
| `data/population/` | Population grid | Exposure | Public (WorldPop 2025) |
| `data/administrative/` | City, district and subdistrict boundaries | Statistical units, maps | Public |
| `data/china_administrative_boundaries_gs_2024_0650/` | Standard national administrative boundaries with map approval number | Study-area map | Public |
| `data/cartography/` | Roads, waterways and other basemap features | Maps | Public (OpenStreetMap and others) |
| `data/study_area/` | Study area, InSAR coverage and built-up area | Clipping | Public (ESA WorldCover) |
| `data/water/` | Lake shoreline reference | Maps | Public |
| `data/validation/` | Earthquake damage case points, campus boundaries and candidate buildings | Event-based evaluation | Derived from public reports |

Housing-price data (community or neighbourhood level) were collected from online housing-market listings and are
not redistributed. Intermediate data and model results are written to a local `result/` folder, which is not under
version control; the public subset is in `data_release/`.
