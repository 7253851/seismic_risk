#!/usr/bin/env python3
"""Run descriptive and spatial analyses for the SCS building PGA results.

Inputs are resolved from the shared workspace roots in project/code/paths.py. Tables,
figures, and GIS-ready administrative summaries are written below
result/statistics/Hazard/analysis/.
"""

from __future__ import annotations

import argparse
import os
os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-paper-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic-paper-cache")
import json
import runpy
import sys
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "project/code"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "plot/shared"))
from textwrap import fill

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib.colorbar import ColorbarBase
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Polygon
from matplotlib.transforms import Bbox
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy import stats
from scipy.spatial import cKDTree
from shapely.geometry import box as geometry_box
from shapely.ops import polylabel

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_SCRIPT_DIR = Path(__file__).resolve().parents[4] / "project/code"
if str(PROJECT_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_SCRIPT_DIR))
from paths import DATA_ROOT, RESULT_ROOT, STATISTICS_ROOT, WORKSPACE_ROOT, PLOT_CODE_ROOT, PLOT_OUTPUT_ROOT
sys.path.insert(0, str(PLOT_CODE_ROOT))
from classification import jenks_breaks, range_labels, JENKS_METHOD


HAZARD_RESULT = RESULT_ROOT / "hazard/scs_pipeline/06_building_hazard.gpkg"
SCENARIO_STATS = STATISTICS_ROOT / "Hazard/scs_pipeline/scenario_statistics.csv"
COUNTY_ADMIN = DATA_ROOT / "administrative/kunming_districts.shp"
STREET_ADMIN = DATA_ROOT / "administrative/kunming_streets.shp"
OUTPUT_DIR = STATISTICS_ROOT / "Hazard/analysis"
FIGURE_DIR = PLOT_OUTPUT_ROOT / "04_seismic_hazard/output/statistics/figures"

PGA_FIELD = "PGA_Final_g"
STREET_MAP_MIN_BUILDINGS = 100
STREET_MEDIAN_MAP_NAME = "pga_street_level_median_map.png"
STREET_MAP_COUNTY_LINEWIDTH = 1.7
STREET_MAP_COUNTY_COLOR = "#30363A"
STREET_MAP_STREET_COLOR = "#969696"
STREET_MAP_FONT_FAMILY = "Arial"
STREET_MAP_COUNTY_FONTSIZE = 16
STREET_MAP_STREET_FONTSIZE = 10
STREET_MAP_LEGEND_TITLE_FONTSIZE = 16
STREET_MAP_LEGEND_RANGE_FONTSIZE = 14
STREET_MAP_LEGEND_HEIGHT = 0.20
STREET_MAP_KEY_FONTSIZE = 8
STREET_MAP_NORTH_ARROW_POSITION = (0.61, 0.865)
STREET_MAP_ABBREVIATIONS = {
    "昆明滇池国家旅游度假区": "DCDJQ",
    "昆明国家高新技术产业开发区": "GXQ",
    "昆明经济技术开发区": "JKQ",
}
STREET_MAP_ZONE_FULL_NAMES = {
    "昆明滇池国家旅游度假区": "Dianchi Tourism Zone",
    "昆明国家高新技术产业开发区": "High-Tech Zone",
    "昆明经济技术开发区": "Economic Development Zone",
}
PGA_CLASS_ORDER = ["Very Low", "Low", "Moderate", "High", "Very High"]
PGA_CLASS_BREAKS = []
PGA_CLASS_BINS = []
PGA_CLASS_RANGES = []
PGA_CLASS_COLORS = ["#FFF7BC", "#FEE391", "#FEC44F", "#FC4E2A", "#BD0026"]
COUNTY_ENGLISH = {
    "呈贡区": "Chenggong District",
    "晋宁区": "Jinning District",
    "西山区": "Xishan District",
    "东川区": "Dongchuan District",
    "官渡区": "Guandu District",
    "寻甸回族彝族自治县": "Xundian Hui and Yi Autonomous County",
    "嵩明县": "Songming County",
    "禄劝彝族苗族自治县": "Luquan Yi and Miao Autonomous County",
    "宜良县": "Yiliang County",
    "石林彝族自治县": "Shilin Yi Autonomous County",
    "富民县": "Fumin County",
    "盘龙区": "Panlong District",
    "五华区": "Wuhua District",
    "安宁市": "Anning City",
}
FAULT_DISPLAY_NAMES = {
    "Westen brach of the Xiaojiang fault system (middle segment)":
        "Western branch of the Xiaojiang fault system (middle segment)",
    "Eastern brach of the Xiaojiang fault system (middle segment)":
        "Eastern branch of the Xiaojiang fault system (middle segment)",
}
FAULT_SUMMARY_STYLE = {
    "font.family": "Arial",
    "font.weight": "bold",
    "font.size": 16,
    "axes.labelsize": 24,
    "axes.labelweight": "bold",
    "axes.linewidth": 2.8,
    "xtick.labelsize": 16,
    "ytick.labelsize": 16,
    "xtick.major.width": 2.8,
    "ytick.major.width": 2.8,
    "xtick.major.size": 5,
    "ytick.major.size": 5,
    "legend.fontsize": 24,
    "mathtext.fontset": "custom",
    "mathtext.rm": "Arial:weight=bold",
    "mathtext.bf": "Arial:weight=bold",
    "mathtext.it": "Arial:style=italic:weight=bold",
    "mathtext.default": "regular",
}


def display_fault_name(value: object) -> str:
    text = str(value)
    return FAULT_DISPLAY_NAMES.get(text, text)

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.labelsize": 10,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.bbox": "tight",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def require_inputs() -> None:
    missing = [p for p in (HAZARD_RESULT, SCENARIO_STATS, COUNTY_ADMIN, STREET_ADMIN) if not p.exists()]
    if missing:
        raise FileNotFoundError("Required input(s) not found:\n" + "\n".join(map(str, missing)))


def pinyin_name(value: object) -> str:
    """Return readable Latin labels for street units while retaining source names in tables."""
    from pypinyin import lazy_pinyin

    text = str(value).strip()
    suffix = ""
    for ending, english in (("街道", "Subdistrict"), ("镇", "Town"), ("乡", "Township")):
        if text.endswith(ending):
            text, suffix = text[: -len(ending)], english
            break
    words = lazy_pinyin(text, errors="ignore")
    romanized = " ".join(word.capitalize() for word in words if word)
    if not romanized:
        romanized = "Administrative unit"
    return f"{romanized} {suffix}".strip()


def configure_pga_classes(values=None) -> None:
    global PGA_CLASS_BREAKS, PGA_CLASS_BINS, PGA_CLASS_RANGES
    if values is None:
        import sqlite3
        with sqlite3.connect(f"{HAZARD_RESULT.as_uri()}?mode=ro", uri=True) as connection:
            values = pd.read_sql_query('SELECT PGA_Final_g FROM building_hazard', connection)[PGA_FIELD]
    PGA_CLASS_BREAKS = jenks_breaks(values)
    PGA_CLASS_BINS = [-np.inf, *PGA_CLASS_BREAKS[1:-1], np.inf]
    PGA_CLASS_RANGES = range_labels(PGA_CLASS_BREAKS, precision=4, unit="g")


def assign_classes(values: pd.Series) -> pd.Categorical:
    if not PGA_CLASS_BREAKS:
        configure_pga_classes()
    return pd.cut(values, bins=PGA_CLASS_BINS, labels=PGA_CLASS_ORDER, right=True, ordered=True)


def load_buildings() -> gpd.GeoDataFrame:
    buildings = gpd.read_file(HAZARD_RESULT)
    required = {"Build_ID", PGA_FIELD, "Dom_Scenario", "Dom_Fault", "Dom_Mw", "Dom_Rrup", "Vs30"}
    missing = required - set(buildings.columns)
    if missing:
        raise KeyError(f"Hazard result is missing required fields: {sorted(missing)}")
    if buildings.crs is None:
        raise ValueError("Hazard result has no coordinate reference system")
    buildings[PGA_FIELD] = pd.to_numeric(buildings[PGA_FIELD], errors="coerce")
    buildings = buildings.loc[np.isfinite(buildings[PGA_FIELD])].copy()
    if buildings.empty:
        raise ValueError("No finite PGA values were found")
    configure_pga_classes(buildings[PGA_FIELD])
    buildings["PGA_Class"] = assign_classes(buildings[PGA_FIELD])
    # The hazard workflow defines Dom_Rrup = sqrt(d^2 + 10^2), where d is the
    # building-polygon-to-controlling-fault distance in the projected CRS.
    rrup = pd.to_numeric(buildings["Dom_Rrup"], errors="coerce").to_numpy(float)
    buildings["Controlling_Fault_Distance_km"] = np.sqrt(np.maximum(rrup**2 - 10.0**2, 0.0))
    return buildings


def assign_admin_units(buildings: gpd.GeoDataFrame, admin_path: Path, level: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    admin = gpd.read_file(admin_path)
    if admin.crs is None:
        raise ValueError(f"Administrative layer has no CRS: {admin_path}")
    admin = admin.to_crs(buildings.crs).copy()
    admin = admin.loc[admin.geometry.notna() & ~admin.geometry.is_empty].copy()
    if (~admin.geometry.is_valid).any():
        admin.geometry = admin.geometry.make_valid()

    if level == "county":
        admin["Admin_Unit_ID"] = [f"C{i:03d}" for i in range(1, len(admin) + 1)]
        admin["Admin_Name"] = admin["name"].astype(str).str.strip()
        admin["Admin_Name_EN"] = admin["Admin_Name"].map(COUNTY_ENGLISH).fillna(admin["Admin_Unit_ID"])
        admin["County_Name"] = admin["Admin_Name"]
        admin["County_Name_EN"] = admin["Admin_Name_EN"]
    elif level == "street":
        admin["Admin_Unit_ID"] = [f"S{i:03d}" for i in range(1, len(admin) + 1)]
        admin["Admin_Name"] = admin["乡"].astype(str).str.strip()
        admin["County_Name"] = admin["县"].astype(str).str.strip()
        admin["County_Name_EN"] = admin["County_Name"].map(COUNTY_ENGLISH).fillna(admin["县"].astype(str))
        admin["Admin_Name_Pinyin"] = admin["Admin_Name"].map(pinyin_name)
        admin["Admin_Name_EN"] = admin["County_Name_EN"].str.replace(
            r" (District|County|Autonomous County|City)$", "", regex=True
        ) + ": " + admin["Admin_Name_Pinyin"]
    else:
        raise ValueError(f"Unknown administrative level: {level}")

    # Use polygon centroids consistently for all scales, matching the location
    # used by the Vs30 sampling stage. The centroid-point join avoids area-weighted
    # duplication of buildings that intersect administrative boundaries.
    points = buildings[["Build_ID", PGA_FIELD, "PGA_Class", "Dom_Scenario", "Dom_Fault", "Dom_Mw", "Dom_Rrup", "Vs30", "Controlling_Fault_Distance_km"]].copy()
    points = gpd.GeoDataFrame(points, geometry=buildings.geometry.centroid, crs=buildings.crs)
    joined = gpd.sjoin(
        points,
        admin[["Admin_Unit_ID", "Admin_Name", "Admin_Name_EN", "County_Name", "County_Name_EN", "geometry"]],
        how="left",
        predicate="within",
    )
    match_count = joined.groupby("Build_ID")["index_right"].count()
    if len(match_count) != len(buildings) or not match_count.eq(1).all():
        bad = match_count[match_count.ne(1)]
        raise ValueError(
            f"{level} spatial join was not one-to-one: {len(bad)} buildings had zero or multiple matches."
        )
    return joined.drop(columns="index_right"), admin


def summarize_units(joined: gpd.GeoDataFrame, admin: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for unit_id, group in joined.groupby("Admin_Unit_ID", sort=False):
        pga = group[PGA_FIELD].to_numpy(float)
        classes = group["PGA_Class"].value_counts(sort=False).reindex(PGA_CLASS_ORDER, fill_value=0)
        row = {
            "Admin_Unit_ID": unit_id,
            "Admin_Name": group["Admin_Name"].iloc[0],
            "Admin_Name_EN": group["Admin_Name_EN"].iloc[0],
            "County_Name": group["County_Name"].iloc[0],
            "County_Name_EN": group["County_Name_EN"].iloc[0],
            "Building_Count": len(group),
            "Mean_PGA_g": float(np.mean(pga)),
            "Median_PGA_g": float(np.median(pga)),
            "SD_PGA_g": float(np.std(pga, ddof=1)) if len(pga) > 1 else np.nan,
            "Min_PGA_g": float(np.min(pga)),
            "P95_PGA_g": float(np.percentile(pga, 95)),
            "Max_PGA_g": float(np.max(pga)),
            "High_or_Very_High_Count": int(classes["High"] + classes["Very High"]),
            "High_or_Very_High_Pct": float((classes["High"] + classes["Very High"]) / len(group) * 100),
        }
        for label, count in classes.items():
            row[f"{label.replace(' ', '_')}_Count"] = int(count)
            row[f"{label.replace(' ', '_')}_Pct"] = float(count / len(group) * 100)
        rows.append(row)
    summary = pd.DataFrame(rows)
    summary_values = summary.drop(columns=["Admin_Name", "Admin_Name_EN", "County_Name", "County_Name_EN"])
    summary_geo = admin.merge(summary_values, on="Admin_Unit_ID", how="left", validate="one_to_one")
    # Keep all administrative polygons in the GIS output; empty units have zero
    # counts while their undefined distribution statistics remain null.
    count_fields = [c for c in summary.columns if c.endswith("_Count") or c == "Building_Count"]
    summary_geo[count_fields] = summary_geo[count_fields].fillna(0).astype(int)

    composition_rows = []
    for _, row in summary_geo.iterrows():
        for class_name in PGA_CLASS_ORDER:
            key = class_name.replace(" ", "_")
            composition_rows.append(
                {
                    "Admin_Unit_ID": row["Admin_Unit_ID"],
                    "Admin_Name": row["Admin_Name"],
                    "Admin_Name_EN": row["Admin_Name_EN"],
                    "PGA_Class": class_name,
                    "PGA_Range": PGA_CLASS_RANGES[PGA_CLASS_ORDER.index(class_name)],
                    "Building_Count": int(row.get(f"{key}_Count", 0) or 0),
                    "Percentage": row.get(f"{key}_Pct", np.nan),
                    "Unit_Building_Count": row["Building_Count"],
                }
            )
    return summary_geo, pd.DataFrame(composition_rows)


def save_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def save_figure(fig: plt.Figure, name: str, *, transparent: bool = False, dpi: int = 220) -> Path:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / name
    fig.savefig(path, dpi=dpi, facecolor="none" if transparent else "white", transparent=transparent)
    plt.close(fig)
    return path








def street_map_label(row: pd.Series) -> str:
    """Use pinyin initials, with compact aliases for development/tourism zones."""
    abbreviation = STREET_MAP_ABBREVIATIONS.get(row["Admin_Name"])
    if abbreviation:
        return abbreviation
    name = row["Admin_Name_Pinyin"]
    for suffix in (" Subdistrict", " Town", " Township"):
        name = name.removesuffix(suffix)
    return "".join(word[0].upper() for word in name.split())


def street_map_full_name(row: pd.Series) -> str:
    return STREET_MAP_ZONE_FULL_NAMES.get(row["Admin_Name"], row["Admin_Name_Pinyin"])




def label_street_median_map(ax: plt.Axes, selected: gpd.GeoDataFrame, font_scale: float = 1.0,
                            include_county_labels: bool = True, street_fontsize: float | None = None) -> None:
    """Place larger district names and all street names without text overlap."""
    anchors = selected.geometry.representative_point()
    labels = []
    street_size = STREET_MAP_STREET_FONTSIZE * font_scale if street_fontsize is None else street_fontsize
    street_scale = street_size / STREET_MAP_STREET_FONTSIZE
    if include_county_labels:
        counties = selected[["County_Name", "geometry"]].dissolve(by="County_Name")
        for name, row in counties.iterrows():
            polygon = row.geometry
            main_polygon = max(polygon.geoms, key=lambda part: part.area) if polygon.geom_type == "MultiPolygon" else polygon
            anchor = polylabel(main_polygon, tolerance=100)
            label = ax.text(
                anchor.x, anchor.y, COUNTY_ENGLISH[name].removesuffix(" District"),
                ha="center", va="center", fontsize=STREET_MAP_COUNTY_FONTSIZE * font_scale,
                fontfamily=STREET_MAP_FONT_FAMILY,
                fontweight="bold", color=STREET_MAP_COUNTY_COLOR, zorder=6,
                linespacing=1.05,
                path_effects=[path_effects.withStroke(linewidth=3 * font_scale, foreground="white")],
            )
            labels.append((label, anchor, polygon, 0))
    for (_, row), anchor in zip(selected.iterrows(), anchors):
        name = street_map_label(row)
        label = ax.text(
            anchor.x, anchor.y, name,
            ha="center", va="center", fontsize=street_size,
            fontfamily=STREET_MAP_FONT_FAMILY, color="#222222", zorder=5,
            linespacing=1.1,
            path_effects=[path_effects.withStroke(linewidth=2 * street_scale, foreground="white")],
        )
        label.set_gid("street-map-label")
        labels.append((label, anchor, row.geometry, 1))

    # Freeze the axes after layout so pixel-based text spacing remains valid
    # when the figure is saved at its final resolution.
    fig = ax.figure
    fig.canvas.draw()
    fig.set_layout_engine("none")
    renderer = fig.canvas.get_renderer()
    occupied = [child.get_tightbbox(renderer).padded(5) for child in ax.child_axes if child.get_visible()]
    occupied.extend(
        artist.get_window_extent(renderer).padded(3)
        for artist in [*ax.texts, *ax.patches]
        if artist.get_gid() in {"street-abbreviation-key", "street-north-arrow", "county-external-label"}
    )
    axes_bounds = ax.get_window_extent()
    angles = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    offsets = [(0.0, 0.0)] + [
        (radius * np.cos(angle), radius * np.sin(angle))
        for radius in range(max(2, round(8 * font_scale)), round(240 * font_scale) + 1, max(2, round(8 * font_scale))) for angle in angles
    ]
    # Reserve district labels first, followed by streets from large to small.
    # Dense urban labels use the nearest free space with a leader to the anchor.
    for label, anchor, polygon, _ in sorted(labels, key=lambda item: (item[3], -item[2].area)):
        target = ax.transData.transform((anchor.x, anchor.y))
        bounds = label.get_window_extent(renderer).expanded(1.12, 1.18)
        width, height = bounds.width, bounds.height
        candidates = []
        for dx, dy in offsets:
            center = target + (dx, dy)
            box = Bbox.from_bounds(center[0] - width / 2, center[1] - height / 2, width, height)
            if not axes_bounds.contains(box.x0, box.y0) or not axes_bounds.contains(box.x1, box.y1):
                continue
            if any(box.overlaps(other) for other in occupied):
                continue
            corners = ax.transData.inverted().transform(box.get_points())
            inside = polygon.covers(geometry_box(*corners.ravel()))
            cost = dx * dx + dy * dy + (0 if inside else 1600 * font_scale**2)
            candidates.append((cost, center, box))
        if not candidates:
            raise ValueError(f"Could not place administrative label without overlap: {label.get_text()}")
        _, center, box = min(candidates, key=lambda item: item[0])
        occupied.append(box)
        position = ax.transData.inverted().transform(center)
        label.set_position(position)
        if np.linalg.norm(center - target) > 4:
            ax.annotate(
                "", xy=(anchor.x, anchor.y), xytext=position,
                arrowprops={"arrowstyle": "-", "color": "#555555", "lw": 0.55 * font_scale},
                zorder=4,
            )
            ax.plot(anchor.x, anchor.y, marker="o", markersize=1.8 * font_scale, color="#555555", zorder=4)


def street_map_county_boundaries(
    street_geo: gpd.GeoDataFrame, selected: gpd.GeoDataFrame,
) -> gpd.GeoSeries:
    """Derive aligned parent boundaries without drawing excluded street areas."""
    counties = street_geo.loc[
        street_geo["County_Name"].isin(selected["County_Name"]), ["County_Name", "geometry"]
    ].dissolve(by="County_Name")
    # Use all source streets to derive true parent boundaries: omitting a
    # small/empty street must not create a false county boundary around it.
    return counties.boundary.intersection(selected.geometry.union_all())




def add_street_map_north_arrow(ax: plt.Axes, crs: object, font_scale: float = 1.0) -> None:
    """Draw a compact arrow aligned with true north in the displayed CRS."""
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    anchor = np.array([
        x_min + STREET_MAP_NORTH_ARROW_POSITION[0] * (x_max - x_min),
        y_min + STREET_MAP_NORTH_ARROW_POSITION[1] * (y_max - y_min),
    ])
    to_geographic = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    to_projected = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    lon, lat = to_geographic.transform(*anchor)
    north = np.array(to_projected.transform(lon, lat + 0.01)) - anchor
    north /= np.linalg.norm(north)
    side = np.array([north[1], -north[0]])
    length = 0.07 * (y_max - y_min)
    tip = anchor + length * north
    notch = anchor + 0.22 * length * north
    left = anchor - 0.18 * length * side
    right = anchor + 0.18 * length * side
    for points, fill in (([tip, left, notch], STREET_MAP_COUNTY_COLOR), ([tip, notch, right], "white")):
        arrow = Polygon(points, closed=True, facecolor=fill, edgecolor=STREET_MAP_COUNTY_COLOR, linewidth=0.9 * font_scale, zorder=8)
        arrow.set_gid("street-north-arrow")
        ax.add_patch(arrow)
    position = tip + 0.012 * (y_max - y_min) * north
    label = ax.text(
        *position, "N", ha="center", va="bottom", fontsize=16 * font_scale,
        fontfamily=STREET_MAP_FONT_FAMILY, fontweight="bold", color=STREET_MAP_COUNTY_COLOR, zorder=8,
    )
    label.set_gid("street-north-arrow")




def plot_fault_contribution() -> tuple[pd.DataFrame, Path]:
    frame = pd.read_csv(SCENARIO_STATS, encoding="utf-8-sig")
    required = {"scenario_id", "FaultName", "max_pga_g", "mean_pga_g", "dominant_buildings", "dominant_share_pct"}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f"Scenario statistics missing fields: {sorted(missing)}")
    frame["FaultName"] = frame["FaultName"].fillna("Unnamed fault segment")
    frame = frame.rename(columns={
        "scenario_id": "Scenario_ID",
        "FaultName": "Fault_Name",
        "Length_km": "Fault_Length_km",
        "Mw": "Moment_Magnitude",
        "max_pga_g": "Maximum_Scenario_PGA_g",
        "mean_pga_g": "Mean_Scenario_PGA_g",
        "dominant_buildings": "Dominant_Building_Count",
        "dominant_share_pct": "Dominant_Building_Share_pct",
    })
    frame["Fault_Name_Display"] = frame["Fault_Name"].map(display_fault_name)
    frame = frame.sort_values(["Dominant_Building_Count", "Mean_Scenario_PGA_g"], ascending=False)
    save_csv(frame, "fault_scenario_contributions.csv")
    top_mean = frame.nlargest(min(10, len(frame)), "Mean_Scenario_PGA_g").sort_values("Mean_Scenario_PGA_g")
    # Keep the ranking as a single panel; scope its typography to this figure.
    with matplotlib.rc_context(FAULT_SUMMARY_STYLE):
        fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
        values = top_mean["Mean_Scenario_PGA_g"].to_numpy(float)
        positions = np.arange(len(top_mean))
        # Map lower PGA to warm yellow and higher PGA to deep red, avoiding
        # the nearly white end of the palette so each bar remains distinct.
        color_fraction = (values - values.min()) / max(float(np.ptp(values)), np.finfo(float).eps)
        colors = plt.get_cmap("YlOrRd")(0.20 + 0.65 * color_fraction)
        ax.barh(positions, values, color=colors, edgecolor="white", linewidth=0.7)
        ax.set_yticks(positions, labels=[""] * len(positions))
        for y, name in zip(positions, top_mean["Fault_Name_Display"]):
            ax.text(
                values.max() * 0.015, y, name,
                ha="left", va="center", fontsize=16, color="#222222",
                fontfamily="Arial", fontweight="bold",
                path_effects=[path_effects.withStroke(linewidth=2.2, foreground="white")],
            )
        ax.set(xlabel="Mean scenario PGA (g)", ylabel="Fault scenario")
        path = save_figure(fig, "fault_scenario_contributions.png")
    return frame, path


def plot_dominant_fault_pie(contributions: pd.DataFrame) -> Path:
    counts = (
        contributions.groupby("Fault_Name_Display")["Dominant_Building_Count"]
        .sum().loc[lambda values: values > 0].sort_values(ascending=False)
    )
    if counts.empty:
        raise ValueError("No buildings have a controlling fault for the pie chart")
    total = int(counts.sum())
    summary = counts.rename("Building_Count").reset_index()
    summary["Share_pct"] = summary["Building_Count"] / total * 100
    save_csv(summary, "dominant_fault_building_counts.csv")
    fault_colors = {
        "Puduhe fault": "#B2182B",
        "Western branch of the Xiaojiang fault system (middle segment)": "#E05A70",
    }
    with matplotlib.rc_context(FAULT_SUMMARY_STYLE):
        fig, ax = plt.subplots(figsize=(9.5, 9.5), constrained_layout=True)
        wedges, _ = ax.pie(
            counts.to_numpy(),
            colors=[fault_colors.get(name, "#F4A3A8") for name in counts.index],
            startangle=90, counterclock=False,
            wedgeprops={"edgecolor": "white", "linewidth": 2.8},
        )
        for wedge, (name, count) in zip(wedges, counts.items()):
            angle = np.deg2rad((wedge.theta1 + wedge.theta2) / 2)
            small_sector = count / total < 0.5
            radius = 0.60 if small_sector else 0.45
            x, y = radius * np.cos(angle), radius * np.sin(angle)
            ax.text(
                x, y + 0.08, fill(name, width=16 if small_sector else 22),
                ha="center", va="center", fontsize=24, linespacing=1.15,
                fontfamily="Arial", fontweight="bold", color="black",
                path_effects=[path_effects.withStroke(linewidth=2.6, foreground="white")],
            )
            count_y = y - (0.25 if small_sector else 0.14)
            ax.text(
                x, count_y + 0.04, f"{count:,} buildings",
                ha="center", va="center", fontsize=20,
                fontfamily="Arial", fontweight="bold", color="black",
                path_effects=[path_effects.withStroke(linewidth=2.6, foreground="white")],
            )
            ax.text(
                x, count_y - 0.06, f"{count / total * 100:.1f}%",
                ha="center", va="center", fontsize=24,
                fontfamily="Arial", fontweight="bold", color="black",
                path_effects=[path_effects.withStroke(linewidth=2.6, foreground="white")],
            )
        ax.set_aspect("equal")
        ax.set(xlim=(-1.04, 1.04), ylim=(-1.04, 1.04))
        FIGURE_DIR.mkdir(parents=True, exist_ok=True)
        with matplotlib.rc_context({"svg.fonttype": "path"}):
            fig.savefig(
                FIGURE_DIR / "dominant_fault_building_counts_pie.svg",
                transparent=True, facecolor="none",
            )
        return save_figure(fig, "dominant_fault_building_counts_pie.png", transparent=True, dpi=600)




def make_quantile_summary(frame: pd.DataFrame, field: str, group_name: str, n_bins: int = 20) -> pd.DataFrame:
    work = frame[[field, PGA_FIELD]].dropna().copy()
    work[group_name] = pd.qcut(work[field], q=n_bins, duplicates="drop")
    result = work.groupby(group_name, observed=True).agg(
        Building_Count=(PGA_FIELD, "size"),
        X_Median=(field, "median"),
        X_Min=(field, "min"),
        X_Max=(field, "max"),
        Mean_PGA_g=(PGA_FIELD, "mean"),
        Median_PGA_g=(PGA_FIELD, "median"),
        P95_PGA_g=(PGA_FIELD, lambda x: float(np.percentile(x, 95))),
    ).reset_index(drop=True)
    result.insert(0, "Bin", np.arange(1, len(result) + 1))
    return result
















def main() -> None:
    require_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading building hazard result: {HAZARD_RESULT}", flush=True)
    buildings = load_buildings()
    pga = buildings[PGA_FIELD].to_numpy(float)
    pga_stats = {
        "Valid_Buildings": int(len(pga)),
        "PGA_Field": PGA_FIELD,
        "PGA_Unit": "g",
        "Minimum_g": float(np.min(pga)),
        "Maximum_g": float(np.max(pga)),
        "Mean_g": float(np.mean(pga)),
        "Median_g": float(np.median(pga)),
        "Standard_Deviation_g": float(np.std(pga, ddof=1)),
        "P05_g": float(np.percentile(pga, 5)),
        "P25_g": float(np.percentile(pga, 25)),
        "P75_g": float(np.percentile(pga, 75)),
        "P95_g": float(np.percentile(pga, 95)),
        "Skewness": float(pd.Series(pga).skew()),
    }
    save_csv(pd.DataFrame([pga_stats]), "pga_descriptive_statistics.csv")
    class_counts = buildings["PGA_Class"].value_counts(sort=False).reindex(PGA_CLASS_ORDER, fill_value=0)
    class_stats = pd.DataFrame({
        "PGA_Class": PGA_CLASS_ORDER,
        "PGA_Range": PGA_CLASS_RANGES,
        "lower_break": PGA_CLASS_BREAKS[:-1], "upper_break": PGA_CLASS_BREAKS[1:],
        "Building_Count": class_counts.astype(int).to_numpy(),
        "Percentage": class_counts.to_numpy() / len(buildings) * 100,
    })
    save_csv(class_stats, "pga_class_statistics.csv")

    print("Allocating building centroids to county-level and street-level polygons...", flush=True)
    county_join, county_admin = assign_admin_units(buildings, COUNTY_ADMIN, "county")
    street_join, street_admin = assign_admin_units(buildings, STREET_ADMIN, "street")
    county_geo, county_classes = summarize_units(county_join, county_admin)
    street_geo, street_classes = summarize_units(street_join, street_admin)
    county_stats = county_geo.drop(columns="geometry")
    street_stats = street_geo.drop(columns="geometry")
    save_csv(county_stats, "pga_by_county_level_unit.csv")
    save_csv(county_classes, "pga_class_by_county_level_unit.csv")
    save_csv(street_stats, "pga_by_street_level_unit.csv")
    save_csv(street_classes, "pga_class_by_street_level_unit.csv")
    contributions, _ = plot_fault_contribution()
    plot_dominant_fault_pie(contributions)
    quantiles = []
    for fault, group in buildings.groupby("Dom_Fault", dropna=False):
        bins = make_quantile_summary(group, "Controlling_Fault_Distance_km", "Distance_Bin")
        quantiles.append(bins.assign(Fault_Name_Display=display_fault_name(fault)))
    save_csv(pd.concat(quantiles, ignore_index=True), "pga_by_controlling_fault_distance_quantile_by_scenario.csv")

    gpkg_path = OUTPUT_DIR / "administrative_pga_statistics.gpkg"
    if gpkg_path.exists():
        gpkg_path.unlink()
    county_geo.to_file(gpkg_path, layer="county_level_units", driver="GPKG", index=False)
    street_geo.to_file(gpkg_path, layer="street_level_units", driver="GPKG", mode="a", index=False)

    metadata = {"analysis": "Current manuscript PGA, fault and administrative tables", "input": str(HAZARD_RESULT),
                "building_count": len(buildings), "pga_class_breaks": PGA_CLASS_BREAKS}
    (OUTPUT_DIR / "analysis_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"Hazard: {len(buildings):,} buildings; paper tables updated")



if __name__ == "__main__":
    main()
