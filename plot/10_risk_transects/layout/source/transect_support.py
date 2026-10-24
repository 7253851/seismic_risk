#!/usr/bin/env python3
"""Draw and validate a reproducible building-risk corridor profile for Kunming."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic_risk_mplconfig")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic_risk_cache")

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
Image.MAX_IMAGE_PIXELS = 200_000_000
import shapely
from shapely.geometry import LineString
from shapely.ops import substring

ROOT = Path('/Users/bin/Projects/seismic_risk')
CONFIG_PATH = Path(__file__).with_name("transect_config.json")
SOURCE = ROOT / "result/risk/scs_paper_method/building_risk.gpkg"
SUMMARY = SOURCE.with_name("calculation_summary.json")
DATA_OUT = ROOT / "result/statistics/Risk/transect"
PLOT_OUT = ROOT / "plot/10_risk_transects/output"
FINAL_OUT = Path('/Users/bin/Projects/seismic_risk/plot/10_risk_transects/layout/work/not_published')
STEM = "Kunming_Risk_Transect_AB"
CLASSES = ["Very Low", "Low", "Moderate", "High", "Very High"]
COLORS = ["#fff1a8", "#ffc247", "#f58a24", "#db3b29", "#7a1018"]
COLOR_BY_CLASS = dict(zip(CLASSES, COLORS))
TEAL = "#006d77"
INK = "#252d33"
GREY = "#69737b"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment_edges(length: float, step: float, min_terminal: float) -> np.ndarray:
    edges = np.arange(0, length, step)
    if length - edges[-1] < min_terminal and len(edges) > 1:
        edges = edges[:-1]
    return np.r_[edges, length]


def calculate(risk, centroids, line, half_width, edges, low_sample):
    buffer = line.buffer(half_width, cap_style="flat", join_style="round")
    mask = shapely.covers(buffer, centroids.array)
    selected = risk.loc[mask].copy().reset_index(drop=True)
    points = centroids.array[mask]
    stations = shapely.line_locate_point(line, points)
    segments = np.clip(np.searchsorted(edges, stations, side="right") - 1, 0, len(edges) - 2)
    selected["station_m"] = stations
    selected["offset_m"] = shapely.distance(points, line)
    selected["segment_id"] = segments + 1
    rows = []
    for i, (start, end) in enumerate(zip(edges[:-1], edges[1:])):
        part = selected.loc[selected.segment_id.eq(i + 1)]
        n = len(part)
        row = {
            "segment_id": i + 1, "start_km": start / 1000, "end_km": end / 1000,
            "mid_km": (start + end) / 2000, "length_km": (end - start) / 1000,
            "building_count": n, "half_width_m": half_width,
            "low_sample": n < low_sample,
            "risk_median": float(part.Risk_Final.median()) if n else np.nan,
            "risk_mean": float(part.Risk_Final.mean()) if n else np.nan,
        }
        for label in CLASSES:
            key = label.lower().replace(" ", "_")
            count = int(part.Risk_Class.eq(label).sum())
            row[f"{key}_count"] = count
            row[f"{key}_pct"] = count / n * 100 if n else np.nan
        row["high_very_high_count"] = row["high_count"] + row["very_high_count"]
        row["high_very_high_pct"] = row["high_very_high_count"] / n * 100 if n else np.nan
        rows.append(row)
    stats = pd.DataFrame(rows)
    assert selected.Build_ID.is_unique
    assert stats.building_count.sum() == len(selected)
    assert selected.offset_m.max() <= half_width + 1e-6
    assert selected.station_m.between(0, line.length).all()
    assert (stats[[label.lower().replace(" ", "_") + "_count" for label in CLASSES]].sum(axis=1)
            == stats.building_count).all()
    valid = stats.building_count.gt(0)
    np.testing.assert_allclose(stats.loc[valid, [label.lower().replace(" ", "_") + "_pct" for label in CLASSES]].sum(axis=1), 100)
    return selected, stats, buffer


def save_geodata(line, buffer, selected, stats, edges, crs, half_width, output_dir=None, route_code="AB"):
    output_dir = Path(output_dir) if output_dir else DATA_OUT
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "risk_transect.gpkg"
    if target.exists():
        target.unlink()
    route = gpd.GeoDataFrame({"name": [f"{route_code[0]}-{route_code[1]} transect"], "length_km": [line.length / 1000]}, geometry=[line], crs=crs)
    route.to_file(target, layer=f"transect_{route_code}", driver="GPKG", index=False)
    gpd.GeoDataFrame({"half_width_m": [half_width], "end_caps": ["flat"]}, geometry=[buffer], crs=crs).to_file(
        target, layer=f"corridor_{half_width}m", driver="GPKG", index=False)
    gpd.GeoDataFrame(stats, geometry=[substring(line, a, b) for a, b in zip(edges[:-1], edges[1:])], crs=crs).to_file(
        target, layer="distance_segments", driver="GPKG", index=False)
    selected.to_file(target, layer="corridor_buildings", driver="GPKG", index=False)
    route.to_crs(4326).to_file(output_dir / f"transect_{route_code}.geojson", driver="GeoJSON", index=False)
    # A compact per-building table makes every allocation independently inspectable.
    selected[["Build_ID", "Risk_Final", "Risk_Class", "station_m", "offset_m", "segment_id"]].to_csv(
        output_dir / "building_allocation.csv", index=False, encoding="utf-8-sig")
    check = gpd.read_file(target, layer="corridor_buildings")
    assert len(check) == len(selected) and check.Build_ID.is_unique
    assert np.array_equal(check.segment_id.to_numpy(), selected.segment_id.to_numpy())




def format_axis(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for name in ["left", "bottom"]:
        ax.spines[name].set_color("#7c858b")
        ax.spines[name].set_linewidth(.55)
    ax.tick_params(length=2.5, width=.55, color="#7c858b", labelsize=7)
    ax.set_axisbelow(True)






