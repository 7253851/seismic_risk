# Public result tables

Building-level results and summary statistics supporting the paper
*Integrating PS-InSAR and multi-source geospatial data for condition-aware building-level seismic risk assessment*.
All files are UTF-8 CSV. Licence: CC BY 4.0 (see `LICENSE`).

The tables were generated from the local model results with
`python project/code/export_public_results.py`. To comply with data licences and
Chinese surveying-and-mapping regulations, building geometries, building
coordinates, raw housing prices (`UnitPrice`, `AvgPrice`, `PriceSrc`, `PriceFill`,
`HasPrice`, `Econ_Val`) and TerraSAR-X point products were removed. Buildings are
identified by `Build_ID`, which is consistent across all tables.

## `buildings/`

| File | Rows | Contents |
| --- | ---: | --- |
| `building_hazard.csv` | 57,228 | Vs30, controlling fault scenario (`Dom_Scenario`, `Dom_Fault`, `Dom_Mw`, `Dom_Rrup`), maximum scenario PGA (`PGA_Final_g`, g), normalized hazard (`Hazard_Norm`), Jenks class (`PGA_Class`) and extrapolation flags |
| `building_vulnerability.csv` | 57,228 | Static indicators (`SCI`, `BFOCI`, `BD_200m`, `Fault_Dist_m`), PS support (`PS_Count`, `PS_CohMn`, `PS_Cov`, `PS_Dens`), deformation indicators (`V_RMS` mm/yr, `Tilt_Angle` deg/yr, `DGI`), observation quality (`Q_insar`), `IBSI`, InSAR modification factor (`F_IBSI`), static vulnerability (`V_static`), final index and class (`Vul_Index`, `Vul_Class`); `Vul_Valid = 1` marks the 41,939 buildings used in the analysis |
| `building_exposure.csv` | 53,513 | Population (`Pop_Value`), floor area and height, economic area (`Econ_Area`), population and economic indices (`Idx_Pop`, `Idx_Econ`), final exposure and class (`Exp_Final`, `Exposure_Class`) |
| `building_risk.csv` | 40,000 | Normalized hazard, vulnerability and exposure (`H_Index`, `V_Index`, `E_Index`), integrated risk (`Risk_Final`) and five-level class (`Risk_Class`) |
| `insar_contribution_static_baseline.csv` | 40,000 | Section 5.1 comparison: static-only and InSAR-informed risk under fixed static-baseline normalization and class breaks, class transitions, district/subdistrict and ablation results |
| `transect_building_allocation.csv` | 7,986 | Buildings assigned to transects A–B and C–D, with station, offset and segment |

Suffix `_n` denotes min–max normalized indicators. Classes are Very Low, Low, Moderate, High and Very High.

## `parameters/`

Fault scenario registry (`02_scenario_registry.csv`), class breaks for PGA, vulnerability, exposure and risk,
Jenks breaks, CRITIC weights, normalization bounds and PS quality-screening thresholds.

## `statistics/`

Summary tables reported in the paper: class counts, descriptive statistics, county- and subdistrict-level
statistics, fault-scenario contributions, deformation-rate statistics, transect segment statistics and
sensitivity, InSAR class-transition summaries, matched-pair comparison and the GNSS validation summary.
