#!/usr/bin/env python3
"""Summarize integrated building earthquake risk and its spatial distribution."""

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
PROJECT_SCRIPT_DIR = Path(__file__).resolve().parents[4] / "project/code"
if str(PROJECT_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_SCRIPT_DIR))
from paths import DATA_ROOT, RESULT_ROOT, STATISTICS_ROOT, WORKSPACE_ROOT, PLOT_CODE_ROOT, PLOT_OUTPUT_ROOT
sys.path.insert(0, str(PLOT_CODE_ROOT))
from analysis.common import CLASS_COLORS, CLASS_ORDER, assign_admin, describe, summarize_admin  # noqa: E402

INPUT_PATH = RESULT_ROOT / "risk/scs_paper_method/building_risk.gpkg"
INPUT_LAYER = "building_risk_scs"
COUNTY_PATH = DATA_ROOT / "administrative/kunming_districts.shp"
STREET_PATH = DATA_ROOT / "administrative/kunming_streets.shp"
OUTPUT_DIR = STATISTICS_ROOT / "Risk/analysis"
FIGURE_DIR = PLOT_OUTPUT_ROOT / "shared/output/statistics/Risk/analysis/figures"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 13, "axes.labelsize": 10,
                     "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
                     "savefig.bbox": "tight", "axes.spines.top": False, "axes.spines.right": False})


def save_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUTPUT_DIR / name, index=False, encoding="utf-8-sig")




def risk_class_statistics(frame: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for label in CLASS_ORDER:
        group = frame.loc[frame.Risk_Class.eq(label)]
        rows.append({
            "risk_class": label, "building_count": int(len(group)), "percentage": float(len(group) / len(frame) * 100),
            "mean_hazard_index": float(group.H_Index.mean()), "mean_vulnerability_index": float(group.V_Index.mean()),
            "mean_exposure_index": float(group.E_Index.mean()), "mean_raw_risk": float(group.R_raw.mean()),
            "mean_final_risk": float(group.Risk_Final.mean()), "median_final_risk": float(group.Risk_Final.median()),
        })
    return pd.DataFrame(rows)






def main() -> None:
    for path in [INPUT_PATH, COUNTY_PATH, STREET_PATH]:
        if not path.is_file():
            raise FileNotFoundError(path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    frame = gpd.read_file(INPUT_PATH, layer=INPUT_LAYER)
    required = ["Build_ID", "PGA_g", "H_Index", "V_Index", "E_Index", "R_raw", "Risk_Final", "Risk_Class"]
    missing = [field for field in required if field not in frame]
    if missing or frame.Build_ID.duplicated().any() or frame.Risk_Final.isna().any():
        raise ValueError(f"Risk result failed validation; missing={missing}; duplicate IDs={frame.Build_ID.duplicated().sum()}")
    if not frame.Risk_Final.between(0, 1).all() or frame.Risk_Class.isna().any():
        raise ValueError("Risk_Final must be complete and within [0, 1], with a class assigned to every building")

    desc = describe(frame, ["PGA_g", "H_Index", "V_Index", "E_Index", "R_raw", "Risk_Final"])
    save_csv(desc, "risk_descriptive_statistics.csv")
    classes = risk_class_statistics(frame)
    save_csv(classes, "risk_class_statistics.csv")
    county_joined, county_admin, county_match = assign_admin(frame, str(COUNTY_PATH), "county", "Risk_Final", "Risk_Class")
    street_joined, street_admin, street_match = assign_admin(frame, str(STREET_PATH), "street", "Risk_Final", "Risk_Class")
    county_geo, county_stats = summarize_admin(county_joined, county_admin, "Risk_Final", "Risk_Class", "county")
    street_geo, street_stats = summarize_admin(street_joined, street_admin, "Risk_Final", "Risk_Class", "street")
    save_csv(county_stats.sort_values("Mean_Risk_Final", ascending=False), "risk_by_county.csv")
    save_csv(street_stats.sort_values("Mean_Risk_Final", ascending=False), "risk_by_street.csv")
    for path in [OUTPUT_DIR / "county_risk_statistics.gpkg", OUTPUT_DIR / "street_risk_statistics.gpkg"]:
        if path.exists():
            path.unlink()
    county_geo.to_file(OUTPUT_DIR / "county_risk_statistics.gpkg", layer="county_level_units", driver="GPKG", index=False)
    street_geo.to_file(OUTPUT_DIR / "street_risk_statistics.gpkg", layer="street_level_units", driver="GPKG", index=False)

    metadata = {"analysis": "Current manuscript class and administrative tables", "module": "Risk",
                "input": str(INPUT_PATH), "building_count": len(frame),
                "county_allocation": county_match, "street_allocation": street_match}
    (OUTPUT_DIR / "analysis_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"Risk: {len(frame):,} buildings; paper tables updated")



if __name__ == "__main__":
    main()
