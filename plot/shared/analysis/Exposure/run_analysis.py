#!/usr/bin/env python3
"""Summarize current SCS building exposure and its spatial distribution."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "project/code"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "plot/shared"))

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic_risk_mplconfig")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic_risk_cache")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
STAT_SCRIPT_DIR = SCRIPT_DIR.parent
PROJECT_SCRIPT_DIR = Path(__file__).resolve().parents[4] / "project/code"
if str(PROJECT_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_SCRIPT_DIR))
from paths import DATA_ROOT, RESULT_ROOT, STATISTICS_ROOT, WORKSPACE_ROOT, PLOT_CODE_ROOT, PLOT_OUTPUT_ROOT
sys.path.insert(0, str(PLOT_CODE_ROOT))
from classification import jenks_breaks, classify, CLASS_NAMES, CLASS_COLORS as WARM_COLORS, JENKS_METHOD
from analysis.common import CLASS_COLORS, assign_admin, describe, summarize_admin  # noqa: E402

INPUT_PATH = RESULT_ROOT / "exposure/scs_paper_method/building_exposure.gpkg"
INPUT_LAYER = "building_exposure_scs"
COUNTY_PATH = DATA_ROOT / "administrative/kunming_districts.shp"
STREET_PATH = DATA_ROOT / "administrative/kunming_streets.shp"
OUTPUT_DIR = STATISTICS_ROOT / "Exposure/analysis"
FIGURE_DIR = PLOT_OUTPUT_ROOT / "shared/output/statistics/Exposure/analysis/figures"
CLASS_ORDER = CLASS_NAMES
CLASS_COLORS_5 = WARM_COLORS
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 13, "axes.labelsize": 10,
                     "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
                     "savefig.bbox": "tight", "axes.spines.top": False, "axes.spines.right": False})


def save_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUTPUT_DIR / name, index=False, encoding="utf-8-sig")




def exposure_classes(values: pd.Series) -> tuple[pd.Series, list[float]]:
    breaks = jenks_breaks(values)
    return classify(values, breaks), breaks


def class_summary(frame: pd.DataFrame, breaks: list[float]) -> pd.DataFrame:
    rows = []
    thresholds = [f"[{breaks[0]:.17g}, {breaks[1]:.17g}]"] + [f"({breaks[i]:.17g}, {breaks[i+1]:.17g}]" for i in range(1, 5)]
    for i, name in enumerate(CLASS_ORDER):
        subset = frame.loc[frame.Exposure_Class.eq(name)]
        rows.append({"exposure_class": name, "rule": thresholds[i], "lower_break": breaks[i], "upper_break": breaks[i + 1],
                     "building_count": int(len(subset)), "percentage": float(len(subset) / len(frame) * 100),
                     "mean_exposure": float(subset.Exp_Final.mean()) if len(subset) else np.nan,
                     "mean_population_index": float(subset.Idx_Pop.mean()) if len(subset) else np.nan,
                     "mean_economic_index": float(subset.Idx_Econ.mean()) if len(subset) else np.nan})
    return pd.DataFrame(rows)






def main() -> None:
    for path in [INPUT_PATH, COUNTY_PATH, STREET_PATH]:
        if not path.is_file():
            raise FileNotFoundError(path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    frame = gpd.read_file(INPUT_PATH, layer=INPUT_LAYER)
    if frame.Build_ID.duplicated().any() or frame.Exp_Final.isna().any() or not frame.Exp_Final.between(0, 1).all():
        raise ValueError("Exposure result must contain unique IDs and complete [0, 1] Exp_Final values")
    frame["Exposure_Class"], breaks = exposure_classes(frame.Exp_Final)

    fields = ["Pop_Value", "Area_m2", "Height_m", "Height_Factor", "UnitPrice", "Econ_Area", "Econ_Val", "Idx_Pop", "Idx_Econ", "Exp_Final"]
    desc = describe(frame, fields)
    save_csv(desc, "exposure_descriptive_statistics.csv")
    classes = class_summary(frame, breaks)
    save_csv(classes, "exposure_class_statistics.csv")
    county_joined, county_admin, county_match = assign_admin(frame, str(COUNTY_PATH), "county", "Exp_Final", "Exposure_Class")
    street_joined, street_admin, street_match = assign_admin(frame, str(STREET_PATH), "street", "Exp_Final", "Exposure_Class")
    county_geo, county_stats = summarize_admin(county_joined, county_admin, "Exp_Final", "Exposure_Class", "county")
    street_geo, street_stats = summarize_admin(street_joined, street_admin, "Exp_Final", "Exposure_Class", "street")
    save_csv(county_stats.sort_values("Mean_Exp_Final", ascending=False), "exposure_by_county.csv")
    save_csv(street_stats.sort_values("Mean_Exp_Final", ascending=False), "exposure_by_street.csv")
    for path in [OUTPUT_DIR / "county_exposure_statistics.gpkg", OUTPUT_DIR / "street_exposure_statistics.gpkg"]:
        if path.exists():
            path.unlink()
    county_geo.to_file(OUTPUT_DIR / "county_exposure_statistics.gpkg", layer="county_level_units", driver="GPKG", index=False)
    street_geo.to_file(OUTPUT_DIR / "street_exposure_statistics.gpkg", layer="street_level_units", driver="GPKG", index=False)

    metadata = {"analysis": "Current manuscript class and administrative tables", "module": "Exposure",
                "input": str(INPUT_PATH), "building_count": len(frame),
                "county_allocation": county_match, "street_allocation": street_match}
    (OUTPUT_DIR / "analysis_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"Exposure: {len(frame):,} buildings; paper tables updated")



if __name__ == "__main__":
    main()
