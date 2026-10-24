#!/usr/bin/env python3
"""Draw exposure, vulnerability and risk street medians in the finalized PGA map style.

Run this file to redraw only the three maps. Existing administrative summaries
and class breaks are checked against current building inputs before drawing.
The full statistical-analysis entry points call the same renderer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "project/code"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plot/shared"))

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-hazard-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic-hazard-cache")
SCRIPT_ROOT = Path(__file__).resolve().parents[3] / "project/code"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colorbar import ColorbarBase
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib import font_manager
from shapely.geometry import box as geometry_box

from classification import JENKS_METHOD
from paths import DATA_ROOT, RESULT_ROOT, STATISTICS_ROOT, WORKSPACE_ROOT, PLOT_CODE_ROOT, PLOT_OUTPUT_ROOT
sys.path.insert(0, str(PLOT_CODE_ROOT))
from analysis.common import assign_admin
from analysis.Hazard import run_analysis as cartography

SPECS = {
    "Exposure": {
        "stem": "exposure", "value": "Exp_Final", "median": "Median_Exp_Final",
        "input": RESULT_ROOT / "exposure/scs_paper_method/building_exposure.gpkg",
        "layer": "building_exposure_scs", "summary": "street_exposure_statistics.gpkg",
        "classes": ["Very Low", "Low", "Moderate", "High", "Very High"],
        "break_table": STATISTICS_ROOT / "Exposure/analysis/exposure_class_statistics.csv",
        "class_column": "Exposure_Class", "classification": JENKS_METHOD,
        "legend": "Median exposure", "legacy": "exposure_mean_by_street_map.png",
    },
    "Vulnerability": {
        "stem": "vulnerability", "value": "Vul_Index", "median": "Median_Vulnerability",
        "input": RESULT_ROOT / "vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg",
        "layer": "building_comprehensive_vulnerability", "summary": "administrative_vulnerability_statistics.gpkg",
        "classes": ["Very Low", "Low", "Moderate", "High", "Very High"],
        "break_table": STATISTICS_ROOT / "Vulnerability/analysis/vulnerability_class_statistics.csv",
        "class_column": "Vul_Class", "classification": "Existing five-class building-level Jenks breaks.",
        "legend": "Median vulnerability", "legend_left": 0.74, "legacy": "street_mean_vulnerability_map.png",
    },
    "Risk": {
        "stem": "risk", "value": "Risk_Final", "median": "Median_Risk_Final",
        "input": RESULT_ROOT / "risk/scs_paper_method/building_risk.gpkg",
        "layer": "building_risk_scs", "summary": "street_risk_statistics.gpkg",
        "classes": ["Very Low", "Low", "Moderate", "High", "Very High"],
        "break_table": RESULT_ROOT / "risk/scs_paper_method/risk_class_breaks.csv",
        "class_column": "Risk_Class", "classification": "Existing five-class building-level Jenks breaks.",
        "legend": "Median risk", "legacy": "risk_mean_by_street_map.png",
    },
}


def read_breaks(module: str) -> list[float]:
    table = pd.read_csv(SPECS[module]["break_table"], float_precision="round_trip")
    breaks = [float(table.lower_break.iloc[0]), *table.upper_break.astype(float).tolist()]
    if len(breaks) != len(SPECS[module]["classes"]) + 1 or not np.all(np.diff(breaks) > 0):
        raise ValueError(f"Invalid {module} class breaks")
    return breaks


def classify(values: pd.Series, breaks: list[float], classes: list[str]) -> pd.Series:
    # All three calculation/analysis modules use upper-inclusive intervals.
    return pd.cut(values, [-np.inf, *breaks[1:-1], np.inf], labels=classes, right=True)










