"""Export the public building-level result tables to ``data_release/``.

The release contains attribute tables only. Building geometries, building
coordinates, raw housing prices and TerraSAR-X point products are removed,
because they are subject to licence or data-access restrictions.
Run from any directory: ``python project/code/export_public_results.py``.
"""

from pathlib import Path
import shutil

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "result"
OUT = ROOT / "data_release"

# Columns removed from every building table.
RESTRICTED = {
    "geometry",
    # building coordinates
    "longitude_wgs84", "latitude_wgs84", "centroid_x_utm48n_m", "centroid_y_utm48n_m",
    # raw housing-price information (web-collected, not redistributable)
    "UnitPrice", "AvgPrice", "PriceSrc", "PriceFill", "HasPrice", "Econ_Val",
}

BUILDING_LAYERS = {
    "building_hazard.csv": "hazard/scs_pipeline/06_building_hazard.gpkg",
    "building_vulnerability.csv": "vulnerability/scs_paper_method/01_building_vulnerability_metrics.gpkg",
    "building_exposure.csv": "exposure/scs_paper_method/building_exposure.gpkg",
    "building_risk.csv": "risk/scs_paper_method/building_risk.gpkg",
}

BUILDING_TABLES = {
    "insar_contribution_static_baseline.csv":
        "discussion/12_insar_contribution/static_baseline/data/all_40000_buildings.csv",
    "transect_building_allocation.csv": "statistics/Risk/transect/building_allocation.csv",
}

# Small parameter and summary tables copied unchanged.
COPY = {
    "parameters": [
        "hazard/scs_pipeline/02_scenario_registry.csv",
        "hazard/scs_pipeline/pga_class_breaks.csv",
        "vulnerability/scs_paper_method/critic_weights.csv",
        "vulnerability/scs_paper_method/normalization_parameters.csv",
        "vulnerability/scs_paper_method/quality_screening.csv",
        "vulnerability/scs_paper_method/vulnerability_class_breaks.csv",
        "exposure/scs_paper_method/exposure_class_breaks.csv",
        "risk/scs_paper_method/risk_class_breaks.csv",
        "statistics/FourIndicators/jenks_class_breaks.csv",
    ],
    "statistics": [
        "statistics/FourIndicators/class_counts_data.csv",
        "statistics/Deformation/deformation_rate_classes.csv",
        "statistics/Deformation/deformation_rate_summary.csv",
        "statistics/Deformation/deformation_rate_histogram.csv",
        "statistics/Hazard/scs_pipeline/scenario_statistics.csv",
        "statistics/Hazard/analysis/fault_scenario_contributions.csv",
        "statistics/Hazard/analysis/dominant_fault_building_counts.csv",
        "statistics/Hazard/analysis/pga_class_statistics.csv",
        "statistics/Hazard/analysis/pga_descriptive_statistics.csv",
        "statistics/Hazard/analysis/pga_by_county_level_unit.csv",
        "statistics/Hazard/analysis/pga_by_street_level_unit.csv",
        "statistics/Hazard/analysis/pga_class_by_county_level_unit.csv",
        "statistics/Hazard/analysis/pga_class_by_street_level_unit.csv",
        "statistics/Hazard/analysis/pga_by_controlling_fault_distance_quantile_by_scenario.csv",
        "statistics/Vulnerability/analysis/vulnerability_class_statistics.csv",
        "statistics/Vulnerability/analysis/vulnerability_indicator_statistics.csv",
        "statistics/Vulnerability/analysis/vulnerability_by_county.csv",
        "statistics/Vulnerability/analysis/vulnerability_by_street.csv",
        "statistics/Exposure/analysis/exposure_class_statistics.csv",
        "statistics/Exposure/analysis/exposure_descriptive_statistics.csv",
        "statistics/Exposure/analysis/exposure_by_county.csv",
        "statistics/Exposure/analysis/exposure_by_street.csv",
        "statistics/Risk/analysis/risk_class_statistics.csv",
        "statistics/Risk/analysis/risk_descriptive_statistics.csv",
        "statistics/Risk/analysis/risk_by_county.csv",
        "statistics/Risk/analysis/risk_by_street.csv",
        "statistics/Risk/transect/segment_statistics.csv",
        "statistics/Risk/transect/all_segment_grade_statistics.csv",
        "statistics/Risk/transect/grade_summary.csv",
        "statistics/Risk/transect/adjacent_segment_changes.csv",
        "statistics/Risk/transect/buffer_width_sensitivity.csv",
        "discussion/12_insar_contribution/static_baseline/data/risk_class_transition_summary.csv",
        "discussion/12_insar_contribution/static_baseline/data/district_upgrade_rates.csv",
        "discussion/12_insar_contribution/static_baseline/data/changed_unchanged_indicator_comparison.csv",
        "discussion/12_insar_contribution/static_baseline/data/block_matched_pairs.csv",
        "discussion/12_insar_contribution/static_baseline/data/primary_pair_reassessment.csv",
        "validation/gnss_velocity/current/validation_summary.csv",
    ],
}


def write(frame, path):
    frame = frame.drop(columns=[c for c in frame.columns if c in RESTRICTED])
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    print(f"{path.relative_to(ROOT)}: {len(frame)} rows, {frame.shape[1]} columns")


def main():
    buildings = OUT / "buildings"
    for name, source in BUILDING_LAYERS.items():
        write(pd.DataFrame(gpd.read_file(RESULT / source, ignore_geometry=True)), buildings / name)
    for name, source in BUILDING_TABLES.items():
        write(pd.read_csv(RESULT / source, encoding="utf-8-sig"), buildings / name)
    for folder, sources in COPY.items():
        target = OUT / folder
        target.mkdir(parents=True, exist_ok=True)
        for source in sources:
            frame = pd.read_csv(RESULT / source, encoding="utf-8-sig")
            if "indicator" in frame.columns:
                frame = frame[~frame["indicator"].isin(RESTRICTED)]
            if RESTRICTED.intersection(frame.columns) or "indicator" in frame.columns:
                write(frame, target / Path(source).name)
            else:
                shutil.copyfile(RESULT / source, target / Path(source).name)


if __name__ == "__main__":
    main()
