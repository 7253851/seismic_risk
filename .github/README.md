# Building-level seismic risk assessment in Kunming with PS-InSAR

Code, cartographic projects and public result tables for the manuscript
*Integrating PS-InSAR and multi-source geospatial data for condition-aware building-level seismic risk assessment*
(W. Huang, M. Yang, Y. Zhang, H. Wu, Y. Yu, H. Yu and T. Wang; submitted to *GIScience & Remote Sensing*).

The framework combines scenario-based seismic hazard (PGA), an InSAR-informed building vulnerability index
(InSAR Building State Index, IBSI) and building exposure within a hazard–vulnerability–exposure (H–V–E) structure,
and was applied to 40,000 buildings in Kunming, China, using TerraSAR-X observations from 2017–2019.

A Chinese version of this README is available in [docs/README_zh.md](../docs/README_zh.md).

## Repository contents

| Path | Contents |
| --- | --- |
| `project/code/` | Numerical model: `Hazard/` seismic hazard, `Vulnerability/` vulnerability and IBSI, `Exposure/` exposure, `Risk/` risk integration, `Validation/` GNSS validation, `12_insar_contribution/` InSAR contribution experiment, `13_event_validation/` earthquake damage cases |
| `project/code/export_public_results.py` | Script that produces `data_release/` from the local model results |
| `project/experiments/` | Section-ordered entry points (symbolic links) to the code above; `experiment_index.json` is the machine-readable index |
| `data_release/` | Public building-level result tables and summary statistics (see [data_release/README.md](../data_release/README.md)) |
| `plot/NN_*/` | Figure code (`code/`) and QGIS projects and layouts (`qgis/`, `layout/`) for each figure |
| `plot/shared/` | Shared analysis functions, PyQGIS scripts and runners, layer styles |
| `figures/` | Compressed PNGs of the final figures (Figures 1–13 and S1–S2) |
| `docs/` | Input-data requirements ([DATA.md](../docs/DATA.md)) and Chinese documentation |

## Data availability

- **Released here** (`data_release/`, CC BY 4.0): building-level hazard, vulnerability (including IBSI components),
  exposure and risk attributes keyed by building ID, the InSAR contribution comparison, transect allocations,
  model parameters (scenario registry, class breaks, CRITIC weights, normalization bounds) and the summary
  statistics reported in the paper.
- **Not released**: TerraSAR-X images and derived persistent-scatterer products (DLR licence, TSX-Archive AO
  projects MTH4018 and MTH3869); building footprint geometries and building coordinates (vectorised from Tianditu
  imagery and subject to Chinese surveying-and-mapping regulations); raw housing-price records (collected from
  online housing-market listings, not redistributable). Building geometries are available from the corresponding
  author on reasonable request where regulations permit.
- **Public inputs**: active faults, Vs30, building heights (CNBH-10m), WorldPop population and the other public
  sources listed in Table 1 of the paper and in [docs/DATA.md](../docs/DATA.md).

## Third-party images

The damage photographs of the two campus buildings in Figure 13 (`figures/figure13.png`) were obtained from the
internet: they are reproduced from the article *2026.9昆明4.3级震害特征与成因解析* (“Damage characteristics and causes
of the September 2026 Kunming M4.3 earthquake”) published by the WeChat official account 震防那些事儿 on
8 October 2026. Copyright of these photographs remains with their original owners; they are not covered by the
licences of this repository. Satellite image insets use Esri World Imagery (© Esri and its data providers).

## Running the code

1. Create a Python environment (Python ≥ 3.10 with geopandas, pandas, numpy, rasterio, shapely, pyproj,
   matplotlib and reportlab). QGIS 3.x is needed for the map layouts.
2. Prepare the input data in `data/` as described in [docs/DATA.md](../docs/DATA.md).
3. Run the model chain (hazard → vulnerability → exposure → risk) from the repository root:

   ```bash
   python project/code/Hazard/pipeline.py
   python project/code/Vulnerability/pipeline.py
   python project/code/Exposure/pipeline.py
   python project/code/Risk/pipeline.py
   ```

   Paths are defined relative to the repository root in `project/code/paths.py`; parameters are in each
   module's `config.json`; results are written to a local `result/` folder.
4. Validation and discussion experiments: `project/code/Validation/`,
   `project/code/12_insar_contribution/run_static_baseline.py` and `project/code/13_event_validation/`.
5. Figures: run the scripts in `plot/NN_*/code/`; open the QGIS projects in `plot/NN_*/qgis/` for map figures.
   `plot/figure_index.json` lists the entry script of each figure. QGIS projects use paths relative to the project
   file; the optional `basemaps` plugin layers refer to the QGIS user profile and may need to be re-added.
   `plot/shared/run_protected.sh` optionally runs figure scripts in a macOS write-protection sandbox.

## Figures

| Figure | Contents |
| --- | --- |
| 1 | Study area and data |
| 2 | Conceptual framework |
| 3 | Processing workflow |
| 4 | Building-level seismic hazard |
| 5 | Distance and site-response controls on PGA |
| 6 | PS-InSAR deformation and GNSS comparison |
| 7 | Building displacement-rate indicators and IBSI |
| 8 | Vulnerability and exposure maps |
| 9 | Class composition of hazard, exposure, vulnerability and risk |
| 10 | Risk along two urban transects |
| 11 | Subdistrict-scale risk patterns |
| 12 | InSAR contribution under a fixed static baseline |
| 13 | Event-based evaluation with two damaged campus buildings |
| S1–S2 | Supplementary figures |

## Licence

Code is released under the [MIT License](../LICENSE). The tables in `data_release/` are released under
[CC BY 4.0](../data_release/LICENSE). Third-party data and images keep their original licences.

## Citation

Please cite the paper (details will be added on publication) and the archived release of this repository
(Zenodo DOI to be added).
