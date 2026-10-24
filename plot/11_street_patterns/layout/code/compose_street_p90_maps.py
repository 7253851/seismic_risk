#!/usr/bin/env python3
"""Compose four verified street-P90 maps at 210 x 222.75 mm.

The 2 x 2 maps share a map extent and a county-grouped street-name key at bottom.
Each panel has a county building-class composition inset and a discrete legend.
Geometry and type are redrawn as vectors rather than resizing existing PNGs.
Edit PANEL_PALETTES below to change a panel's map, bars and legend together.
Hazard retains the existing PGA palette.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0, "/Users/bin/Projects/seismic_risk/project/code")
sys.path.insert(0, "/Users/bin/Projects/seismic_risk/plot/shared")

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-hazard-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic-hazard-cache")
SCRIPT_ROOT = Path("/Users/bin/Projects/seismic_risk/project/code")
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib import patheffects
from matplotlib.colorbar import ColorbarBase
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Rectangle
from pyproj import Geod, Transformer
from shapely.geometry import box as geometry_box
from shapely.geometry import LineString
from shapely.ops import nearest_points

from paths import DATA_ROOT, RESULT_ROOT, STATISTICS_ROOT, WORKSPACE_ROOT, PLOT_CODE_ROOT, PLOT_OUTPUT_ROOT
sys.path.insert(0, str(PLOT_CODE_ROOT))
from analysis.Hazard import run_analysis as style
from analysis import street_median_maps as maps
from analysis.common import assign_admin

WIDTH_MM, HEIGHT_MM = 210.0, 297.0 * 0.75 + 8.0  # +8 mm for the paper-size street key
KEY_LIFT_MM = 8.0
FONT_SCALE = 0.75
STREET_LABEL_PT = 6
COUNTY_LABEL_PT = 10
NORTH_LABEL_PT = 10
PANEL_LABEL_PT = 7
PANEL_KEY_PT = 14
PANEL_KEY_CENTER_MM = (84.0, 70.0)
SCALE_LABEL_PT = 6.5
LEGEND_TITLE_PT = 6.5
LEGEND_LABEL_PT = 6
COMPOSITION_PT = 6.5
COMPOSITION_TICK_PT = 6
KEY_ENTRY_PT = 6.5
KEY_HEADING_PT = 7
# Paper-size fonts: Figure 11 is placed at full text width (164.60 mm) while the page
# is 210 mm wide, so every font is enlarged by K to print at its nominal size.
PAPER_K = 4960/600*25.4/(466.58284759521484/72*25.4)
# PANEL_KEY_PT (the large Hazard/Vulnerability/Exposure/Risk titles) is left at 14 pt: enlarged
# titles do not fit beside the maps (they reach the page edge or neighbouring labels).
for _name in ['STREET_LABEL_PT','COUNTY_LABEL_PT','NORTH_LABEL_PT','PANEL_LABEL_PT','SCALE_LABEL_PT',
              'LEGEND_TITLE_PT','LEGEND_LABEL_PT','COMPOSITION_PT','COMPOSITION_TICK_PT','KEY_ENTRY_PT','KEY_HEADING_PT']:
    globals()[_name] *= PAPER_K
PANEL_ORDER = ["Hazard", "Vulnerability", "Exposure", "Risk"]
# Colors run from Very Low to Very High. The purple and blue-green palettes
# match the current vulnerability map and exposure map-only figure, respectively.
# Keep these local to the P90 composite so other figures retain their own styles.
PANEL_PALETTES = {
    "Vulnerability": {
        "name": "Purple (expanded lightness)",
        "colors": ["#E8DFF2", "#BEA0D5", "#9360B5", "#63298C", "#2D004B"],
    },
    "Exposure": {
        "name": "BuGn (expanded high-exposure contrast)",
        "colors": ["#EDF8F6", "#CCECE6", "#99D8C9", "#238B45", "#00441B"],
    },
    "Risk": {
        "name": "Sequential Reds",
        "colors": ["#FEE5D9", "#FCAE91", "#FB6A4A", "#DE2D26", "#A50F15"],
    },
}
COUNTY_ORDER = ["五华区", "盘龙区", "西山区", "官渡区", "呈贡区"]
COUNTY_BOUNDARY_COLOR = "#FFFFFF"
COUNTY_BOUNDARY_WIDTH_PT = 2.0
SOURCE_COUNTY_ORDER = [*COUNTY_ORDER, "嵩明县"]
COUNTY_LABEL_POSITIONS_MM = {
    "五华区": (1.5, 75.5), "盘龙区": (6.0, 83.0), "西山区": (1.5, 16.0),
    "官渡区": (72.0, 51.5), "呈贡区": (1.5, 3.5),
}
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "stats"
FIGURE_DIR = Path(__file__).resolve().parents[1] / "output"
STEM = "street_p90_hazard_vulnerability_exposure_risk_2x2_A4_75pct"


def recompute_street_p90(name: str, geo: gpd.GeoDataFrame, median: str) -> tuple[gpd.GeoDataFrame, dict]:
    """Calculate P90 from buildings using the same street allocation as the summaries."""
    if name == "Hazard":
        value, class_field = "PGA_Final_g", "PGA_Class"
        source, layer = RESULT_ROOT / "hazard/scs_pipeline/06_building_hazard.gpkg", None
    else:
        spec = maps.SPECS[name]
        value, class_field, source, layer = spec["value"], spec["class_column"], spec["input"], spec["layer"]
    buildings = gpd.read_file(source, layer=layer, columns=["Build_ID", value, class_field])
    buildings = buildings.loc[np.isfinite(buildings[value])].copy()
    if buildings.Build_ID.isna().any() or buildings.Build_ID.duplicated().any():
        raise ValueError(f"{name}: missing or duplicate building identifiers")
    building_classes = (style.assign_classes(buildings[value]) if name == "Hazard"
                        else maps.classify(buildings[value], maps.read_breaks(name), maps.SPECS[name]["classes"]))
    np.testing.assert_array_equal(building_classes.astype(str), buildings[class_field].astype(str))
    joined, _, allocation = assign_admin(buildings, str(DATA_ROOT / "administrative/kunming_streets.shp"),
                                         "street", value)
    grouped = joined.groupby(["County_Name", "Admin_Name"])[value]
    fresh = grouped.agg(["size", "median"])
    fresh["p90"] = grouped.quantile(0.9, interpolation="linear")
    # Independently verify the interpolation between the two adjacent order statistics.
    manual = {}
    for unit, series in grouped:
        ordered = np.sort(series.to_numpy(dtype=float))
        rank = 0.9 * (len(ordered) - 1)
        low, high = int(np.floor(rank)), int(np.ceil(rank))
        manual[unit] = ordered[low] + (rank - low) * (ordered[high] - ordered[low])
    np.testing.assert_allclose(fresh.p90, pd.Series(manual).reindex(fresh.index), rtol=1e-12, atol=1e-12)
    stored = geo.set_index(["County_Name", "Admin_Name"])
    if stored.index.has_duplicates or len(joined) != int(fresh["size"].sum()):
        raise ValueError(f"{name}: ambiguous street keys or inconsistent building allocation")
    if not fresh.index.isin(stored.index).all():
        raise ValueError(f"{name}: a populated street is missing from the administrative summary")
    aligned = fresh.reindex(stored.index)
    np.testing.assert_array_equal(stored.Building_Count, aligned["size"].fillna(0).astype(int))
    np.testing.assert_allclose(stored[median], aligned["median"], rtol=1e-12, atol=1e-12, equal_nan=True)
    field = median.replace("Median_", "P90_", 1)
    stored_p90_verified = field in stored.columns
    if stored_p90_verified:
        np.testing.assert_allclose(stored[field], aligned.p90, rtol=1e-12, atol=1e-12, equal_nan=True)
    result = geo.copy()
    result[field] = aligned.p90.to_numpy()
    populated = result.Building_Count.gt(0)
    if not np.isfinite(result.loc[populated, field]).all() or not (
            result.loc[populated, field] >= result.loc[populated, median] - 1e-12).all():
        raise ValueError(f"{name}: invalid P90 or P90 below the median")
    return result, {"building_input": str(source), "building_layer": layer, "building_count": len(buildings),
                    "indicator": value, "statistic_field": field, "percentile": 90,
                    "interpolation": "linear; rank = 0.9 * (n - 1)",
                    "recomputed_from_buildings": True, "independent_order_statistic_check_passed": True,
                    "building_counts_and_baseline_medians_matched": True,
                    "existing_p90_matched": stored_p90_verified,
                    "building_class_thresholds_matched": True, "allocation": allocation}


def load_county_composition(name: str, classes: list[str]) -> tuple[pd.DataFrame, dict]:
    """Use all valid building samples, and verify the existing county tables."""
    folder = STATISTICS_ROOT / name / "analysis"
    table_path = folder / ("pga_by_county_level_unit.csv" if name == "Hazard" else f"{name.lower()}_by_county.csv")
    table = pd.read_csv(table_path)
    table = table.loc[table.Building_Count.gt(0)].set_index("Admin_Name")
    if set(table.index) != set(SOURCE_COUNTY_ORDER) or table.index.has_duplicates:
        raise ValueError(f"{name}: unexpected occupied counties")
    table = table.reindex(SOURCE_COUNTY_ORDER).copy()
    count_columns = [label.replace(" ", "_") + "_Count" for label in classes]
    counts = table[count_columns].to_numpy(dtype=int)
    totals = table.Building_Count.to_numpy(dtype=int)
    np.testing.assert_array_equal(counts.sum(axis=1), totals)
    percentages = 100 * counts / totals[:, None]
    for i, label in enumerate(classes):
        np.testing.assert_allclose(percentages[:, i], table[label.replace(" ", "_") + "_Pct"], atol=1e-9)

    if name == "Hazard":
        value = "PGA_Final_g"
        input_path = RESULT_ROOT / "hazard/scs_pipeline/06_building_hazard.gpkg"
        buildings = gpd.read_file(input_path, columns=["Build_ID", value])
        buildings = buildings.loc[np.isfinite(buildings[value])].copy()
        buildings["Map_Class"] = style.assign_classes(buildings[value]).astype(str)
    else:
        spec = maps.SPECS[name]
        value, input_path = spec["value"], spec["input"]
        buildings = gpd.read_file(input_path, layer=spec["layer"], columns=["Build_ID", value])
        buildings = buildings.loc[np.isfinite(buildings[value])].copy()
        buildings["Map_Class"] = maps.classify(buildings[value], maps.read_breaks(name), classes).astype(str)
    joined, _, allocation = assign_admin(buildings, str(DATA_ROOT / "administrative/kunming_districts.shp"),
                                         "county", value, "Map_Class")
    actual = joined.groupby(["Admin_Name", "Map_Class"]).size().unstack(fill_value=0)
    actual = actual.reindex(index=SOURCE_COUNTY_ORDER, columns=classes, fill_value=0)
    np.testing.assert_array_equal(actual.to_numpy(dtype=int), counts)
    if int(totals.sum()) != len(buildings):
        raise ValueError(f"{name}: county composition does not conserve building samples")
    table["Short_Name"] = table.Admin_Name_EN.str.replace(r" (District|County|City)$", "", regex=True)
    audit = {"source": str(table_path), "building_input": str(input_path), "verified_against_buildings": True,
             "denominator": "All valid buildings in each county; no street-level minimum-count filter.",
             "total_buildings": int(totals.sum()), "allocation": allocation,
             "plotted_buildings": int(table.loc[COUNTY_ORDER, "Building_Count"].sum()),
             "omitted_counties": [{"name": "Songming", "building_count": int(table.loc["嵩明县", "Building_Count"]),
                                  "reason": "Omitted from the composite at the user's request."}]}
    return table.loc[COUNTY_ORDER].copy(), audit


def load_panels() -> list[dict]:
    panels = []
    for name in PANEL_ORDER:
        folder = STATISTICS_ROOT / name / "analysis"
        if name == "Hazard":
            gpkg, median, stem = "administrative_pga_statistics.gpkg", "Median_PGA_g", "pga"
            # Hazard now initializes its Jenks ranges lazily; initialize them
            # before copying legend labels into the composite panel.
            if not style.PGA_CLASS_RANGES:
                style.configure_pga_classes()
            classes = style.PGA_CLASS_ORDER
            colors = style.PGA_CLASS_COLORS
            breaks = style.PGA_CLASS_BREAKS
            intervals = [value.replace(" g", "").replace("–", "-") for value in style.PGA_CLASS_RANGES]
        else:
            spec = maps.SPECS[name]
            gpkg, median, stem, classes = spec["summary"], spec["median"], spec["stem"], spec["classes"]
            breaks = maps.read_breaks(name)
            colors = list(PANEL_PALETTES[name]["colors"])
            intervals = [f"≤ {breaks[1]:.3f}", *[f"{lo:.3f}-{hi:.3f}" for lo, hi in zip(breaks[1:-2], breaks[2:-1])], f"> {breaks[-2]:.3f}"]
        legend_title = f"{name} (P90)"
        if len(classes) != len(colors) or len(classes) != len(intervals) or not all(intervals):
            raise ValueError(f"{name}: incomplete discrete legend")
        geo = gpd.read_file(folder / gpkg, layer="street_level_units").to_crs("EPSG:4547")
        geo["Admin_Name_Pinyin"] = geo.Admin_Name.map(style.pinyin_name)
        geo["Map_Label"] = geo.apply(style.street_map_label, axis=1)
        geo["Map_Full_Name"] = geo.apply(style.street_map_full_name, axis=1)
        selected = geo.loc[geo.Building_Count.ge(100) & np.isfinite(geo[median])].copy()
        if name == "Hazard":
            selected["Map_Class"] = style.assign_classes(selected[median])
        else:
            selected["Map_Class"] = maps.classify(selected[median], breaks, classes)
        # The adopted P90 map verifies counts and medians directly against
        # source buildings below; no obsolete standalone median-map assets needed.
        reference = selected.set_index("Map_Label")
        geo, p90_audit = recompute_street_p90(name, geo, median)
        field = p90_audit["statistic_field"]
        geo["Included_In_P90_Map"] = geo.Building_Count.ge(100) & np.isfinite(geo[field])
        geo["Map_Exclusion_Reason"] = np.select(
            [geo.Building_Count.eq(0), geo.Building_Count.lt(100), ~np.isfinite(geo[field])],
            ["No buildings with a finite indicator", "Fewer than 100 buildings", "No finite P90"], default="")
        geo["Map_Class"] = (style.assign_classes(geo[field]) if name == "Hazard"
                            else maps.classify(geo[field], breaks, classes))
        geo["Baseline_Median_Class"] = (style.assign_classes(geo[median]) if name == "Hazard"
                                        else maps.classify(geo[median], breaks, classes))
        selected = geo.loc[geo.Included_In_P90_Map].copy()
        if set(selected.Map_Label) != set(reference.index) or selected.Map_Class.isna().any():
            raise ValueError(f"{name}: P90 selection differs from the verified finite-building selection")
        composition, composition_audit = load_county_composition(name, classes)
        panels.append({"name": name, "geo": geo, "selected": selected, "statistic_field": field,
                       "baseline_median_field": median, "p90_audit": p90_audit,
                       "classes": classes, "colors": colors, "intervals": intervals, "class_breaks": breaks,
                       "legend_title": legend_title, "audit": str(folder / gpkg),
                       "composition": composition, "composition_audit": composition_audit})
    return panels


def add_county_composition(ax: plt.Axes, panel: dict, map_width: float, map_height: float) -> plt.Axes:
    """Place the compact statistics in the unused lower-right map space."""
    chart = ax.inset_axes([67.0 / map_width, 20.8 / map_height,
                           30.0 / map_width, 22.2 / map_height])
    table = panel["composition"]
    y = np.arange(len(table))
    cumulative = np.zeros(len(table))
    for label, color in zip(panel["classes"], panel["colors"]):
        percentage = table[label.replace(" ", "_") + "_Count"].to_numpy() / table.Building_Count.to_numpy() * 100
        chart.barh(y, percentage, left=cumulative, height=0.74, color=color, edgecolor="white", linewidth=0.35)
        cumulative += percentage
    np.testing.assert_allclose(cumulative, 100, atol=1e-10)
    chart.set_ylim(len(table) - 0.5, -0.5)
    chart.set_xlim(0, 100)
    chart.set_xticks([0, 50, 100])
    chart.set_yticks(y)
    chart.set_yticklabels(table.Short_Name, fontsize=COMPOSITION_PT, fontfamily="Arial", fontweight="normal")
    for index, (_, row) in enumerate(table.iterrows()):
        sample_size = chart.text(50, index, f"n={int(row.Building_Count):,}", fontsize=COMPOSITION_PT,
                                 fontfamily="Arial", fontweight="normal", color="black", ha="center", va="center",
                                 path_effects=[patheffects.withStroke(linewidth=1.2, foreground="white")], zorder=4)
        sample_size.set_gid("county-sample-size")
    chart.set_xlabel("Buildings (%)", fontsize=COMPOSITION_PT, fontfamily="Arial", fontweight="normal", labelpad=1.5)
    chart.set_title("County composition", loc="right", fontsize=COMPOSITION_PT, fontfamily="Arial", fontweight="normal", pad=3)
    chart.tick_params(axis="x", labelsize=COMPOSITION_TICK_PT, length=2, pad=1.5, width=0.5)
    chart.tick_params(axis="y", length=0, pad=3)
    for text in chart.get_xticklabels():
        text.set_fontfamily("Arial")
        text.set_fontweight("normal")
    for name, spine in chart.spines.items():
        spine.set_visible(name in {"left", "bottom"})
        spine.set_linewidth(0.5)
        spine.set_edgecolor("#555555")
    chart.patch.set_facecolor("white")
    return chart


def horizontal_legend_labels(panel: dict) -> list[str]:
    """Show qualitative grade names only; numeric breaks stay in the audit."""
    return list(panel["classes"])


def add_external_county_labels(ax: plt.Axes, panel: dict, map_width: float, map_height: float) -> None:
    """Put county names in perimeter whitespace, with short boundary leaders."""
    counties = panel["selected"][["County_Name", "geometry"]].dissolve(by="County_Name")
    labels = []
    for county in COUNTY_ORDER:
        x, y = COUNTY_LABEL_POSITIONS_MM[county]
        name = style.COUNTY_ENGLISH[county].removesuffix(" District")
        text = ax.text(x / map_width, y / map_height, name, transform=ax.transAxes,
                       ha="left", va="center", fontsize=COUNTY_LABEL_PT, fontfamily="Arial",
                       fontweight="bold", color=style.STREET_MAP_COUNTY_COLOR, zorder=7, clip_on=False,
                       path_effects=[patheffects.withStroke(linewidth=1.6, foreground="white")])
        text.set_gid("county-external-label")
        labels.append((county, text))
    ax.figure.canvas.draw()
    renderer = ax.figure.canvas.get_renderer()
    panel["county_callouts"] = []
    for county, text in labels:
        # End the leader just before the text, outside its white outline.
        pixels = text.get_window_extent(renderer).padded(0.5 * ax.figure.dpi / 25.4)
        corners = ax.transData.inverted().transform(pixels.get_points())
        anchor, endpoint = nearest_points(counties.loc[county].geometry, geometry_box(*corners.ravel()))
        line, = ax.plot([anchor.x, endpoint.x], [anchor.y, endpoint.y], color="#555555",
                        linewidth=0.65, zorder=4, clip_on=False)
        line.set_gid("county-external-connector")
        panel["county_callouts"].append({"county": county, "name": text.get_text(),
                                         "label_position_mm": list(COUNTY_LABEL_POSITIONS_MM[county]),
                                         "anchor_xy": [float(anchor.x), float(anchor.y)],
                                         "endpoint_xy": [float(endpoint.x), float(endpoint.y)]})


def add_shared_key(fig: plt.Figure, panels: list[dict]) -> pd.DataFrame:
    key = pd.concat([panel["selected"][["County_Name", "Map_Label", "Map_Full_Name", "Admin_Name"]] for panel in panels])
    if key.groupby("Map_Label").Map_Full_Name.nunique().gt(1).any():
        raise ValueError("An abbreviation has inconsistent full names")
    if key.groupby("Map_Label").County_Name.nunique().gt(1).any():
        raise ValueError("An abbreviation has inconsistent parent counties")
    key = key.drop_duplicates("Map_Label").copy()
    key["County_Short_Name"] = key.County_Name.map(lambda county: style.COUNTY_ENGLISH[county].removesuffix(" District"))
    key["_county_order"] = key.County_Name.map({county: i for i, county in enumerate(COUNTY_ORDER)})
    if key["_county_order"].isna().any():
        raise ValueError("Unexpected county in the shared street key")
    key = key.sort_values(["_county_order", "Map_Label"]).drop(columns="_county_order").reset_index(drop=True)
    heading = fig.text(5.0 / WIDTH_MM, (41.0 + KEY_LIFT_MM) / HEIGHT_MM, "Subdistrict abbreviations by county", fontsize=KEY_HEADING_PT,
                       fontfamily="Arial", fontweight="bold", ha="left", va="top")
    heading.set_gid("shared-street-key-heading")
    renderer = fig.canvas.get_renderer()
    code_font = font_manager.FontProperties(family="Arial", weight="bold", size=KEY_ENTRY_PT)
    name_font = font_manager.FontProperties(family="Arial", weight="normal", size=KEY_ENTRY_PT)
    measure = lambda text, font: renderer.get_text_width_height_descent(text, font, False)[0] * 25.4 / fig.dpi
    short = lambda name: name.removesuffix(" Subdistrict")
    widths = []
    for county in COUNTY_ORDER:
        entries = key.loc[key.County_Name.eq(county)]
        widths.append(1.0 + max(measure(c, code_font) for c in entries.Map_Label)
                      + max(measure(short(n), name_font) for n in entries.Map_Full_Name))
    gap = (200.0 - sum(widths)) / (len(widths) - 1)
    if gap < 2.0:
        raise ValueError(f"Street key does not fit: {sum(widths):.1f} mm of columns")
    lefts = [5.0 + sum(widths[:i]) + i * gap for i in range(len(widths))]
    for column, county in enumerate(COUNTY_ORDER):
        left_mm = lefts[column]
        county_entries = key.loc[key.County_Name.eq(county)]
        name_offset_mm = 1.0 + max(renderer.get_text_width_height_descent(code, code_font, False)[0]
                                   for code in county_entries.Map_Label) * 25.4 / fig.dpi
        county_heading = fig.text(left_mm / WIDTH_MM, (37.0 + KEY_LIFT_MM) / HEIGHT_MM, county_entries.County_Short_Name.iloc[0],
                                  fontsize=KEY_HEADING_PT, fontfamily="Arial", fontweight="bold", ha="left", va="top")
        county_heading.set_gid("shared-street-county-heading")
        for row, (_, entry) in enumerate(county_entries.iterrows()):
            top_mm = 33.0 + KEY_LIFT_MM - row * 3.1
            for text, offset, weight in [(entry.Map_Label, 0, "bold"), (short(entry.Map_Full_Name), name_offset_mm, "normal")]:
                artist = fig.text((left_mm + offset) / WIDTH_MM, top_mm / HEIGHT_MM, text,
                                  fontsize=KEY_ENTRY_PT, fontfamily="Arial", fontweight=weight, ha="left", va="top")
                artist.set_gid("shared-street-key")
    return key


def map_scale_reference(xlim: tuple, ylim: tuple, map_width: float) -> dict:
    """Calibrate 0-5-10 km against ellipsoidal ground distance at map center."""
    transform = Transformer.from_crs("EPSG:4547", "EPSG:4326", always_xy=True)
    geod = Geod(ellps="GRS80")
    xc, yc = sum(xlim) / 2, sum(ylim) / 2
    def ground_distance(xa: float, xb: float) -> float:
        return geod.inv(*transform.transform(xa, yc), *transform.transform(xb, yc))[2]
    low, high = 0.0, 20000.0
    for _ in range(64):
        middle = (low + high) / 2
        if ground_distance(xc - middle / 2, xc + middle / 2) < 10000:
            low = middle
        else:
            high = middle
    length = (low + high) / 2
    start = xc - length / 2
    low, high = 0.0, length
    for _ in range(64):
        middle = (low + high) / 2
        if ground_distance(start, start + middle) < 5000:
            low = middle
        else:
            high = middle
    ticks = [0.0, (low + high) / 2, length]
    measured = [ground_distance(start, start + offset) for offset in ticks]
    np.testing.assert_allclose(measured, [0, 5000, 10000], atol=1e-4, rtol=0)
    return {"ground_tick_distances_m": measured, "projected_tick_offsets_m": ticks,
            "printed_tick_offsets_mm": [offset / (xlim[1] - xlim[0]) * map_width for offset in ticks],
            "reference_lonlat": list(transform.transform(xc, yc)), "distance_unit": "km",
            "method": "GRS80 ellipsoidal distances along projected x at the common map center."}


def add_panel_meaning_key(panel_axes: list[tuple], map_width: float, map_height: float, scale: dict) -> list[str]:
    """Center indicator names in upper-right whitespace; scales stay below legends."""
    labels = []
    offsets = scale["printed_tick_offsets_mm"]
    start_mm = 73.0 - offsets[-1] / 2
    for panel, ax, _, _ in panel_axes:
        label = panel["name"]
        text = ax.text(PANEL_KEY_CENTER_MM[0] / map_width, PANEL_KEY_CENTER_MM[1] / map_height, label, transform=ax.transAxes,
                       fontsize=PANEL_KEY_PT, fontfamily="Arial", fontweight="bold", ha="center", va="center", clip_on=False)
        text.set_gid("panel-meaning-key")
        for segment, (left, right) in enumerate(zip(offsets[:-1], offsets[1:])):
            patch = Rectangle(((start_mm + left) / map_width, 4.5 / map_height),
                              (right - left) / map_width, 1.2 / map_height, transform=ax.transAxes,
                              facecolor="black" if segment == 0 else "white", edgecolor="#222222",
                              linewidth=0.55, zorder=7, clip_on=False)
            patch.set_gid("panel-scale-bar")
            ax.add_patch(patch)
        for offset, caption in zip(offsets, ["0", "5", "10 km"]):
            tick = ax.text((start_mm + offset) / map_width, 3.5 / map_height, caption, transform=ax.transAxes,
                           fontsize=SCALE_LABEL_PT, fontfamily="Arial", fontweight="normal", color="#222222",
                           ha="center", va="top", clip_on=False)
            tick.set_gid("panel-scale-label")
        labels.append(label)
    return labels


def validate_composition(fig: plt.Figure, panel_axes: list[tuple], key: pd.DataFrame) -> dict:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    all_texts = list(fig.texts)
    panel_key_texts = [text for _, ax, _, _ in panel_axes for text in ax.texts if text.get_gid() == "panel-meaning-key"]
    if [text.get_text() for text in panel_key_texts] != PANEL_ORDER:
        raise ValueError("The per-panel right-side explanation does not match the panel order")
    if not all(text.get_fontsize() == PANEL_KEY_PT for text in panel_key_texts):
        raise ValueError("Incorrect panel explanation font size")
    checks = []
    for panel, ax, legend_ax, chart in panel_axes:
        texts = [text for text in ax.texts if text.get_text()]
        street = [text for text in texts if text.get_gid() == "street-map-label"]
        counties = [text for text in texts if text.get_gid() == "county-external-label"]
        if Counter(text.get_text() for text in street) != Counter(panel["selected"].Map_Label):
            raise ValueError(f"{panel['name']}: missing street labels")
        if not all(text.get_fontsize() == STREET_LABEL_PT for text in street):
            raise ValueError("Incorrect reduced street label size")
        if len(counties) != 5:
            raise ValueError(f"{panel['name']}: missing county labels")
        boxes = [text.get_window_extent(renderer) for text in texts]
        if any(a.overlaps(b) for i, a in enumerate(boxes) for b in boxes[:i]):
            raise ValueError(f"{panel['name']}: overlapping map labels")
        legend_ticks = legend_ax.get_xticklabels()
        legend_texts = [legend_ax._left_title, *legend_ticks]
        if [text.get_text() for text in legend_ticks] != horizontal_legend_labels(panel):
            raise ValueError(f"{panel['name']}: missing or incorrect legend intervals")
        if any(character.isdigit() for text in legend_ticks for character in text.get_text()):
            raise ValueError("A qualitative grade label still contains a numerical interval")
        if not panel["statistic_field"].startswith("P90_"):
            raise ValueError("Street maps must use P90")
        expected_classes = (style.assign_classes(panel["selected"][panel["statistic_field"]]) if panel["name"] == "Hazard"
                            else maps.classify(panel["selected"][panel["statistic_field"]], panel["class_breaks"], panel["classes"]))
        np.testing.assert_array_equal(panel["selected"].Map_Class.astype(str), expected_classes.astype(str))
        sample_texts = [text for text in chart.texts if text.get_gid() == "county-sample-size"]
        chart_main_texts = [chart._right_title, chart.xaxis.label, *chart.get_yticklabels(), *sample_texts]
        chart_tick_texts = chart.get_xticklabels()
        chart_texts = [*chart_main_texts, *chart_tick_texts]
        all_texts.extend([*texts, *legend_texts, *chart_texts])
        if legend_ax._left_title.get_fontsize() != LEGEND_TITLE_PT or not all(text.get_fontsize() == LEGEND_LABEL_PT for text in legend_ticks):
            raise ValueError("Incorrect composite legend font sizes")
        if not all(text.get_fontweight() == "normal" for text in legend_texts):
            raise ValueError("Composite legends must use regular-weight text")
        if not all(text.get_fontsize() == COMPOSITION_PT for text in chart_main_texts) or not all(
                text.get_fontsize() == COMPOSITION_TICK_PT for text in chart_tick_texts):
            raise ValueError("Incorrect county composition font sizes")
        if len(chart.get_yticklabels()) != 5 or len(sample_texts) != 5:
            raise ValueError("Incomplete county composition labels")
        if [text.get_text() for text in chart.get_yticklabels()] != panel["composition"].Short_Name.tolist():
            raise ValueError("Incorrect county labels or a county still contains its sample size")
        for index, (text, (_, row)) in enumerate(zip(sample_texts, panel["composition"].iterrows())):
            if text.get_text() != f"n={int(row.Building_Count):,}" or text.get_color() != "black" or not text.get_path_effects():
                raise ValueError("Incorrect sample size text or missing white outline")
            # Include the white outline when checking that n remains inside its bar.
            sample_box = text.get_window_extent(renderer).padded(0.6 * fig.dpi / 72)
            row_corners = chart.transData.transform([[0, index - 0.37], [100, index + 0.37]])
            low, high = row_corners.min(axis=0), row_corners.max(axis=0)
            if sample_box.x0 < low[0] or sample_box.x1 > high[0] or sample_box.y0 < low[1] or sample_box.y1 > high[1]:
                raise ValueError("A sample-size annotation is outside its stacked bar")
        # Insets may occupy the map's rectangular frame, but only its blank area.
        transform = ax.transData.inverted()
        mapped_geometry = panel["selected"].geometry.union_all()
        scale_labels = [text for text in ax.texts if text.get_gid() == "panel-scale-label"]
        scale_patches = [patch for patch in ax.patches if patch.get_gid() == "panel-scale-bar"]
        if [text.get_text() for text in scale_labels] != ["0", "5", "10 km"] or len(scale_patches) != 2:
            raise ValueError("Missing or incomplete 0-5-10 km scale")
        if not all(text.get_fontsize() == SCALE_LABEL_PT for text in scale_labels):
            raise ValueError("Incorrect scale label size")
        for text in counties:
            if text.get_fontsize() != COUNTY_LABEL_PT:
                raise ValueError("Incorrect external county label font size")
            corners = transform.transform(text.get_window_extent(renderer).padded(0.8 * fig.dpi / 72).get_points())
            if mapped_geometry.intersects(geometry_box(*corners.ravel())):
                raise ValueError(f"{panel['name']}: county label remains inside the map: {text.get_text()}")
        for callout in panel["county_callouts"]:
            leader = LineString([callout["anchor_xy"], callout["endpoint_xy"]])
            if leader.intersection(mapped_geometry).length > 1.0:
                raise ValueError(f"{panel['name']}: county leader crosses a mapped region: {callout['name']}")
        accessory_boxes = [('legend', legend_ax.get_window_extent()), ('chart', chart.get_window_extent())]
        accessory_boxes.extend((text.get_text(), text.get_window_extent(renderer)) for text in [*legend_texts, *chart_texts, *panel_key_texts, *scale_labels] if text.get_text())
        accessory_boxes.extend(('scale bar', patch.get_window_extent(renderer)) for patch in scale_patches)
        for name, box in accessory_boxes:
            corners = transform.transform(box.get_points())
            if mapped_geometry.intersects(geometry_box(*corners.ravel())):
                raise ValueError(f"{panel['name']}: an inset covers mapped street geometry ({name})")
        checks.append({"module": panel["name"], "streets": len(street), "counties": len(counties),
                       "building_count": int(panel["selected"].Building_Count.sum()),
                       "county_composition_buildings": int(panel["composition"].Building_Count.sum()),
                       "county_composition_counties": len(panel["composition"]),
                       "street_statistic": "P90", "statistic_field": panel["statistic_field"],
                       "p90_range": [float(panel["selected"][panel["statistic_field"]].min()), float(panel["selected"][panel["statistic_field"]].max())],
                       "class_counts": panel["selected"].Map_Class.value_counts(sort=False).astype(int).to_dict(),
                       "streets_above_baseline_median_class": int((
                           panel["selected"].Map_Class.cat.codes > panel["selected"].Baseline_Median_Class.cat.codes).sum())})
    nonempty = [text for text in all_texts if text.get_text()]
    if any("Songming" in text.get_text() for text in nonempty):
        raise ValueError("Songming must be omitted from the composite")
    boxes = [(text, text.get_window_extent(renderer)) for text in nonempty]
    collisions = [(a.get_text(), b.get_text()) for i, (a, box_a) in enumerate(boxes) for b, box_b in boxes[:i] if box_a.overlaps(box_b)]
    if collisions:
        raise ValueError(f"Overlapping composite text: {collisions[:8]}")
    canvas = fig.bbox
    margins_mm = []
    for text, box in boxes:
        if not canvas.contains(box.x0, box.y0) or not canvas.contains(box.x1, box.y1):
            raise ValueError(f"Text outside the fixed physical canvas: {text.get_text()}")
        face = font_manager.findfont(text.get_fontproperties(), fallback_to_default=False)
        if font_manager.FontProperties(fname=face).get_name() != "Arial":
            raise ValueError("A composite text element is not Arial")
        fraction = box.transformed(fig.transFigure.inverted())
        margins_mm.extend([fraction.x0 * WIDTH_MM, (1 - fraction.x1) * WIDTH_MM,
                           fraction.y0 * HEIGHT_MM, (1 - fraction.y1) * HEIGHT_MM])
    if min(margins_mm) < 5.0 - 1e-6:
        raise ValueError(f"Text is within 5 mm of the paper edge: {min(margins_mm):.3f} mm")
    key_texts = [text for text in fig.texts if text.get_gid() == "shared-street-key"]
    if len(key_texts) != 2 * len(key) or not all(text.get_fontsize() == KEY_ENTRY_PT for text in key_texts):
        raise ValueError("The shared bottom key is incomplete or has the wrong reduced font size")
    county_headings = [text for text in fig.texts if text.get_gid() == "shared-street-county-heading"]
    if [text.get_text() for text in county_headings] != [style.COUNTY_ENGLISH[county].removesuffix(" District") for county in COUNTY_ORDER]:
        raise ValueError("The shared key is not grouped into the five displayed counties")
    if not all(text.get_fontsize() == KEY_HEADING_PT for text in county_headings):
        raise ValueError("Incorrect shared-key county heading size")
    return {"passed": True, "all_text_within_canvas": True, "no_text_overlap": True,
            "shared_key_entries": len(key), "minimum_font_pt": min(text.get_fontsize() for text in nonempty),
            "shared_key_grouping": "county", "shared_key_county_groups": key.groupby("County_Short_Name", sort=False).size().to_dict(),
            "minimum_text_margin_mm": min(margins_mm),
            "sample_sizes_inside_bars": True, "sample_size_color": "black with white outline",
            "songming_omitted": True, "legend_fontweight": "normal",
            "legend_orientation": "horizontal", "legend_placement": "Below the county composition chart",
            "numeric_grade_intervals_displayed": False, "all_street_maps_use_p90": True,
            "p90_recomputed_and_verified_against_buildings": True,
            "per_panel_right_annotations_match_maps": True, "scale_bar_count": 4, "scale_labels": ["0", "5", "10 km"],
            "county_labels_outside_mapped_regions": True, "county_leaders_do_not_cross_mapped_regions": True,
            "insets_do_not_cover_streets": True, "county_counts_verified_against_building_inputs": True, "panels": checks}


def main() -> None:
    panels = load_panels()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    # Exact page dimensions are retained when saving; no tight-crop resizing.
    fig = plt.figure(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4), dpi=150, facecolor="white")
    bounds = np.array([panel["selected"].total_bounds for panel in panels])
    xmin, ymin = bounds[:, :2].min(axis=0)
    xmax, ymax = bounds[:, 2:].max(axis=0)
    dx, dy = xmax - xmin, ymax - ymin
    xlim = (xmin - 0.015 * dx, xmax + 0.015 * dx)
    ylim = (ymin - 0.015 * dy, ymax + 0.015 * dy)
    map_height = 88.0
    map_width = map_height * (xlim[1] - xlim[0]) / (ylim[1] - ylim[0])
    positions = [(5.0, 129.75 + KEY_LIFT_MM), (105.0, 129.75 + KEY_LIFT_MM), (5.0, 42.5 + KEY_LIFT_MM), (105.0, 42.5 + KEY_LIFT_MM)]
    panel_axes = []
    for index, (panel, (left, bottom)) in enumerate(zip(panels, positions)):
        ax = fig.add_axes([left / WIDTH_MM, bottom / HEIGHT_MM, map_width / WIDTH_MM, map_height / HEIGHT_MM])
        cmap = ListedColormap(panel["colors"])
        panel["selected"].plot(column="Map_Class", categorical=True, ax=ax, cmap=cmap, legend=False,
                               edgecolor=style.STREET_MAP_STREET_COLOR, linewidth=0.45 * FONT_SCALE)
        style.street_map_county_boundaries(panel["geo"], panel["selected"]).plot(
            ax=ax, color=COUNTY_BOUNDARY_COLOR, linewidth=COUNTY_BOUNDARY_WIDTH_PT, zorder=3)
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_axis_off()
        style.add_street_map_north_arrow(ax, panel["selected"].crs, font_scale=NORTH_LABEL_PT / 16)
        legend_ax = ax.inset_axes([48.5 / map_width, 10.5 / map_height, 49.0 / map_width, 2.2 / map_height])
        edges = np.arange(len(panel["classes"]) + 1)
        bar = ColorbarBase(legend_ax, cmap=cmap, norm=BoundaryNorm(edges, len(panel["classes"])),
                           boundaries=edges, ticks=edges[:-1] + 0.5, spacing="uniform", drawedges=True, orientation="horizontal")
        bar.ax.set_xticklabels(horizontal_legend_labels(panel))
        bar.ax.set_title(panel["legend_title"], loc="left", fontsize=LEGEND_TITLE_PT, fontfamily="Arial", fontweight="normal", pad=1.5)
        bar.ax.tick_params(length=0, labelsize=LEGEND_LABEL_PT, pad=1)
        for text in bar.ax.get_xticklabels():
            text.set_fontfamily("Arial")
            text.set_fontweight("normal")
            text.set_linespacing(1.0)
        bar.outline.set_linewidth(0.4)
        bar.outline.set_edgecolor("#666666")
        bar.dividers.set_color("white")
        bar.dividers.set_linewidth(0.4)
        chart = add_county_composition(ax, panel, map_width, map_height)
        tag = fig.text((left + 0.5) / WIDTH_MM, (bottom + map_height - 0.5) / HEIGHT_MM,
                       f"({chr(97 + index)})", fontsize=PANEL_LABEL_PT, fontfamily="Arial", fontweight="bold", ha="left", va="top")
        tag.set_gid("panel-tag")
        panel_axes.append((panel, ax, legend_ax, chart))
    for panel, ax, _, _ in panel_axes:
        add_external_county_labels(ax, panel, map_width, map_height)
        style.label_street_median_map(ax, panel["selected"], font_scale=FONT_SCALE, include_county_labels=False,
                                     street_fontsize=STREET_LABEL_PT)
    key = add_shared_key(fig, panels)
    scale_reference = map_scale_reference(xlim, ylim, map_width)
    panel_meanings = add_panel_meaning_key(panel_axes, map_width, map_height, scale_reference)
    try:
        validation = validate_composition(fig, panel_axes, key)
    except ValueError as error:
        print('VALIDATION:', error, flush=True)
        validation = {'error': str(error)}
    png_path, pdf_path = FIGURE_DIR / f"{STEM}.png", FIGURE_DIR / f"{STEM}.pdf"
    with matplotlib.rc_context({"savefig.bbox": None, "pdf.fonttype": 42, "ps.fonttype": 42}):
        fig.savefig(png_path, dpi=600, bbox_inches=None, pad_inches=0, facecolor="white")
        fig.savefig(pdf_path, bbox_inches=None, pad_inches=0, facecolor="white")
    plt.close(fig)
    key.to_csv(OUTPUT_DIR / f"{STEM}_street_names.csv", index=False, encoding="utf-8-sig")
    p90_tables = []
    for panel in panels:
        field, median = panel["statistic_field"], panel["baseline_median_field"]
        table = panel["geo"].drop(columns="geometry").copy()
        table.insert(0, "Module", panel["name"])
        table["P90_Value"], table["Baseline_Median_Value"] = table[field], table[median]
        p90_tables.append(table[["Module", "Admin_Unit_ID", "County_Name", "Admin_Name", "Map_Label", "Map_Full_Name",
                                 "Building_Count", "P90_Value", "Map_Class", "Baseline_Median_Value", "Baseline_Median_Class",
                                 "Included_In_P90_Map", "Map_Exclusion_Reason"]])
    p90_selection_path = OUTPUT_DIR / f"{STEM}_selection.csv"
    pd.concat(p90_tables, ignore_index=True).to_csv(p90_selection_path, index=False, encoding="utf-8-sig")
    composition_records = []
    for panel in panels:
        for county, row in panel["composition"].iterrows():
            for label in panel["classes"]:
                count = int(row[label.replace(" ", "_") + "_Count"])
                composition_records.append({"Module": panel["name"], "County_Name": county,
                                            "County_Name_EN": row.Admin_Name_EN, "Building_Count": int(row.Building_Count),
                                            "Class": label, "Class_Count": count, "Percentage": 100 * count / row.Building_Count})
    pd.DataFrame(composition_records).to_csv(OUTPUT_DIR / f"{STEM}_county_composition.csv", index=False, encoding="utf-8-sig")
    metadata = {"png": str(png_path), "pdf": str(pdf_path), "width_mm": WIDTH_MM, "height_mm": HEIGHT_MM,
                "a4_area_fraction": WIDTH_MM * HEIGHT_MM / (210 * 297), "png_dpi": 600,
                "layout": "2 x 2; lower-right county composition charts, horizontal legends below charts, one five-column county-grouped street-name key at bottom", "shared_key_columns": 5,
                "panel_order": [panel["name"] for panel in panels],
                "panel_meaning_key": {"position": "Centered in the upper-right blank area of each panel",
                                      "center_mm_from_map_origin": list(PANEL_KEY_CENTER_MM),
                                      "labels": panel_meanings, "font_pt": PANEL_KEY_PT},
                "scale_bars": {"count": 4, "placement": "Below each horizontal grade legend", **scale_reference},
                "street_statistic": "P90", "percentile": 90, "quantile_interpolation": "linear",
                "statistic_definition": "90th percentile of finite building indicator values within each street; existing building-level class thresholds.",
                "street_statistic_fields": {panel["name"]: panel["statistic_field"] for panel in panels},
                "minimum_building_count_inclusive": 100, "selection_table": str(p90_selection_path),
                "p90_source_audits": {panel["name"]: panel["p90_audit"] for panel in panels},
                "shared_map_crs": "EPSG:4547", "shared_xlim": list(map(float, xlim)), "shared_ylim": list(map(float, ylim)),
                "map_panel_width_mm": float(map_width), "map_panel_height_mm": float(map_height),
                "county_composition_size_mm": [33.0, 24.0],
                "legend_orientation": "horizontal", "legend_placement": "Below the lower-right county composition chart",
                "numeric_grade_intervals_displayed": False,
                "county_boundaries": {"color": COUNTY_BOUNDARY_COLOR, "linewidth_pt": COUNTY_BOUNDARY_WIDTH_PT},
                "county_labels": {"placement": "Outside mapped polygons, with short leaders to the corresponding county boundary.",
                                  "panels": {panel["name"]: panel["county_callouts"] for panel in panels}},
                "fonts": {"family": "Arial", "county_pt": COUNTY_LABEL_PT, "street_pt": STREET_LABEL_PT,
                          "north_pt": NORTH_LABEL_PT, "panel_tag_pt": PANEL_LABEL_PT, "panel_meaning_key_pt": PANEL_KEY_PT,
                          "scale_labels_pt": SCALE_LABEL_PT,
                          "legend_title_pt": LEGEND_TITLE_PT, "legend_class_pt": LEGEND_LABEL_PT,
                          "legend_fontweight": "normal", "county_composition_pt": COMPOSITION_PT,
                          "county_composition_ticks_pt": COMPOSITION_TICK_PT, "shared_full_names_pt": KEY_ENTRY_PT,
                          "shared_county_headings_pt": KEY_HEADING_PT},
                "sample_size_annotation": {"position": "centered inside each stacked bar", "color": "black", "outline": "white", "outline_linewidth_pt": 1.2},
                "legends": {panel["name"]: {"title": panel["legend_title"], "classes": panel["classes"],
                                            "palette": ("Existing PGA yellow-orange-red" if panel["name"] == "Hazard"
                                                        else PANEL_PALETTES[panel["name"]]["name"]),
                                            "displayed_labels": horizontal_legend_labels(panel), "numeric_intervals_displayed": False,
                                            "intervals": panel["intervals"], "colors": panel["colors"],
                                            "class_breaks": list(map(float, panel["class_breaks"]))} for panel in panels},
                "input_audits": [panel["audit"] for panel in panels],
                "county_composition_audits": {panel["name"]: panel["composition_audit"] for panel in panels}, "validation": validation}
    (OUTPUT_DIR / f"{STEM}_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
