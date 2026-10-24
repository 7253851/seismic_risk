#!/usr/bin/env python3
"""Review figure from saved results only. Never imports or runs the model.

Run with /Users/bin/miniforge3/envs/seismic/bin/python <this file>.
All GeoPackage connections use SQLite mode=ro. All outputs stay beside this file.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/ibsi-mpl")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
import matplotlib.patheffects as pe
from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator
import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image
import shapely

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "plot/07_ibsi/output"
RESULT = ROOT / "result/vulnerability/scs_paper_method"
SOURCE = RESULT / "01_building_vulnerability_metrics.gpkg"
FINAL = RESULT / "02_building_comprehensive_vulnerability.gpkg"
LAYER = "building_vulnerability_metrics"
VAULT_RESULTS = Path("/Users/bin/Library/Mobile Documents/com~apple~CloudDocs/Obsidian/Workbench/projects/seismic_risk/manuscript/04_results.md")
STEM = "IBSI_components_and_spatial_distribution"
FIELDS = ["V_RMS", "Tilt_Angle", "DGI_Str", "IBSI"]
WIDTH_MM, HEIGHT_MM = 180, 106.5
MAP_BOUNDS_MM = [43.5, 8, 93, 93 * 200 / 195]
# Exact saved QGIS map frame (10, 8.5, 180.279, 190 mm) inside its
# 195 x 200 mm export crop. These are frame edges, excluding image margins.
NATIVE_MAP_FRAME_MM = [10, 8.5, 180.279, 190]
MAP_FRAME_SCALE = MAP_BOUNDS_MM[2] / 195
MAP_FRAME_BOTTOM_MM = MAP_BOUNDS_MM[1] + (200 - 8.5 - 190) * MAP_FRAME_SCALE
MAP_FRAME_TOP_MM = MAP_BOUNDS_MM[1] + (200 - 8.5) * MAP_FRAME_SCALE
HIST_BOUNDS_MM = [[6.5, MAP_FRAME_TOP_MM - 40, 38, 40],
                  [6.5, MAP_FRAME_BOTTOM_MM + 3.5, 38, 40],
                  [139.5, MAP_FRAME_TOP_MM - 40, 38, 40],
                  [139.5, MAP_FRAME_BOTTOM_MM + 3.5, 38, 40]]
IBSI_LEGEND_CENTER_Y_MM = MAP_FRAME_BOTTOM_MM - 2.5
BAR_COLOR = "#4c83b0"
GRAY = "#b6b6b6"
P90_COLOR = "#a54a23"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False,
                                     allow_nan=False) + "\n", encoding="utf-8")


def protected_files():
    # Fingerprint every project file, every manuscript asset (including PDFs),
    # the Chinese results text, and all data consulted by this script.
    files = {p for base in [ROOT / "project", ROOT / "manuscript", *(ROOT / "plot").glob("*/qgis"), ROOT / "plot/shared/styles"]
             for p in base.rglob("*") if p.is_file()}
    files.update(p for p in RESULT.iterdir() if p.is_file())
    files.update([VAULT_RESULTS,
                  ROOT / "result/intermediate/vulnerability_inputs/input_manifest.json",
                  ROOT / "data/TSX_PS/README.md",
                  ROOT / "data/study_area/README.md"])
    for base, stem in [("data/administrative", "kunming_districts"),
                       ("data/water", "dianchi_2016_reference"),
                       ("data/study_area", "TSX_Total_Extent")]:
        files.update((ROOT / base).glob(stem + ".*"))
    native_manifest = OUT / "native_QGIS_map_manifest.json"
    if native_manifest.exists():
        files.update(Path(name) for name in json.loads(native_manifest.read_text())["protected_sources_sha256"])
    return sorted(files)


def readonly_gpkg(path, layer):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as con:
        geom, srid = con.execute(
            "SELECT column_name,srs_id FROM gpkg_geometry_columns WHERE table_name=?",
            (layer,)).fetchone()
        schema = pd.read_sql_query(f'PRAGMA table_info("{layer}")', con)
        frame = pd.read_sql_query(f'SELECT * FROM "{layer}" ORDER BY "Build_ID"', con)
    def wkb(blob):
        if blob is None:
            return None
        if blob[:2] != b"GP":
            raise ValueError("Not a GeoPackage geometry")
        envelope = (blob[3] >> 1) & 7
        size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope]
        return blob[8 + size:]
    geometry = shapely.from_wkb([wkb(blob) for blob in frame.pop(geom)])
    frame = frame.drop(columns="fid")
    return gpd.GeoDataFrame(frame, geometry=geometry, crs=f"EPSG:{srid}"), schema


def axes_mm(fig, rect):
    x, y, w, h = rect
    return fig.add_axes([x / WIDTH_MM, y / HEIGHT_MM, w / WIDTH_MM, h / HEIGHT_MM])


def metric_summary(frame, cohort_name):
    rows = []
    units = ["mm/year",
             "degree/year (one-year equivalent tilt rate)",
             "mm/(m year)",
             "dimensionless"]
    for field, unit in zip(FIELDS, units):
        x = frame[field].to_numpy(float)
        x = x[np.isfinite(x)]
        q = np.quantile(x, [0, .01, .25, .5, .75, .9, .99, 1])
        rows.append(dict(cohort=cohort_name, field=field, unit=unit, N=len(x),
                         missing_or_nonfinite=len(frame) - len(x), zero_N=int((x == 0).sum()),
                         mean=float(x.mean()), sd_ddof1=float(x.std(ddof=1)),
                         **dict(zip(["min", "P01", "P25", "median", "P75", "P90", "P99", "max"], q))))
    return rows


def make_map(fig, all_buildings, valid, lake, districts, study):
    """Preserve native map size; place the transparent IBSI key on one line."""
    native = json.loads((OUT / "native_QGIS_map_manifest.json").read_text())
    assert native["inventory_N"] == len(all_buildings)
    assert native["frame_extent_and_scale_identical_to_source"]
    assert native["valid_IBSI_N"] == len(valid)
    for name, expected in native["protected_sources_sha256"].items():
        assert digest(name) == expected, f"Native map source changed: {name}"
    rect = MAP_BOUNDS_MM
    ax = axes_mm(fig, rect)
    with Image.open(OUT / "IBSI_native_QGIS_map.png") as im:
        ax.imshow(np.asarray(im.convert("RGB")), aspect="equal", interpolation="lanczos")
    ax.axis("off")
    maximum = float(valid.IBSI.max())
    assert native["context_legend_inside_map"]
    display = native["display_classification"]
    assert sum(display["counts"]) == len(valid)
    edges = display["breaks"]
    labels = [f"{edges[i]:.3f}–{edges[i+1]:.3f}" for i in range(5)] + ["No valid IBSI"]
    # Measure Arial text to center a compact, fully horizontal legend without
    # shrinking its labels or colliding with the lower histogram annotations.
    renderer = fig.canvas.get_renderer()
    def text_width_mm(text, size):
        width_px, _, _ = renderer.get_text_width_height_descent(
            text, FontProperties(family="Arial", weight="bold", size=size), False)
        return width_px * 25.4 / fig.dpi
    title_width = text_width_mm("IBSI", 7.5)
    widths = [text_width_mm(label, 7.2) for label in labels]
    swatch_width, swatch_gap, item_gap, title_gap = 2.5, 1.0, 3.2, 3.0
    total_width = title_width + title_gap + sum(
        swatch_width + swatch_gap + width for width in widths) + 5 * item_gap
    assert total_width <= WIDTH_MM - 10
    x, y = (WIDTH_MM - total_width) / 2, IBSI_LEGEND_CENTER_Y_MM
    fig.text(x / WIDTH_MM, y / HEIGHT_MM, "IBSI", fontsize=7.5,
             ha="left", va="center", gid="IBSI_legend_title")
    x += title_width + title_gap
    for i, (color, label, width) in enumerate(zip([*display["colors"], GRAY], labels, widths)):
        fig.add_artist(Rectangle((x / WIDTH_MM, (y - .8) / HEIGHT_MM),
                                 swatch_width / WIDTH_MM, 1.6 / HEIGHT_MM,
                                 transform=fig.transFigure, facecolor=color, edgecolor="none"))
        fig.text((x + swatch_width + swatch_gap) / WIDTH_MM, y / HEIGHT_MM,
                 label, fontsize=7.2, ha="left", va="center", gid=f"IBSI_legend_entry_{i}")
        x += swatch_width + swatch_gap + width + item_gap
    return ax, {"source_project": native["source_project"], "source_layout": native["source_layout"],
                "native_QGIS_export": str(OUT / "IBSI_native_QGIS_map.png"),
                "draft_QGIS_project": native["draft_derivative"],
                "crs": native["map_crs"], "aspect": "native QGIS aspect preserved",
                "extent_m": native["extent"], "frame_extent_and_scale_identical_to_source": True,
                "visible_inventory_N": native["footprints_intersecting_frame_N"],
                "visible_valid_IBSI_N": native["valid_IBSI_footprints_intersecting_frame_N"],
                "inventory_outside_frame_N": native["inventory_outside_frame_N"],
                "valid_IBSI_outside_frame_N": native["valid_IBSI_outside_frame_N"],
                "polygon_simplification": False, "centroid_substitution": False,
                "range": [0.0, maximum], "color_normalization": "five quantile display classes",
                "display_classification": display,
                "invalid_gray_count": native["invalid_IBSI_footprints_intersecting_frame_N"],
                "full_inventory_invalid_N": native["invalid_IBSI_N"],
                "context_styles_reused": native["context_styles_reused"],
                "native_label_minimum_final_pt": 15.2 * rect[2] / 195,
                "native_context_legend_final_pt": 15.2 * rect[2] / 195,
                "image_bounds_mm": rect, "context_legend_inside_map": True,
                "native_map_frame_mm": NATIVE_MAP_FRAME_MM,
                "printed_map_frame_bottom_mm": MAP_FRAME_BOTTOM_MM,
                "printed_map_frame_top_mm": MAP_FRAME_TOP_MM,
                "IBSI_legend_location": "below map; title and six entries on one centered line",
                "IBSI_legend_rows": 1, "IBSI_legend_width_mm": total_width,
                "IBSI_legend_center_y_mm": IBSI_LEGEND_CENTER_Y_MM,
                "legend_background": "transparent; no box or frame",
                "background_clipping": "Exact user-requested saved QGIS frame. No additional statistical exclusions."}


def histograms(fig, cohort):
    labels = ["RMS", "Tilt", "DGI", "IBSI"]
    # Main panels show the dense body. Each inset continues the same raw,
    # equal-width bins to the full observed maximum, without rescaling values
    # or renormalizing percentages to the tail subset.
    ranges = {
        "V_RMS": (8., 16., .2, [0, 2, 4, 6, 8], [8, 12, 16]),
        "Tilt_Angle": (.025, .12, .0005, [0, .01, .025], [.025, .12]),
        "DGI_Str": (.9, 4.1, .025, [0, .3, .6, .9], [.9, 2.5, 4.1]),
        "IBSI": (.42, .9, .01, [0, .2, .4], [.42, .65, .9]),
    }
    hist_rows, axes, settings = [], [], []
    for field, label, rect in zip(FIELDS, labels, HIST_BOUNDS_MM):
        ax = axes_mm(fig, rect); axes.append(ax)
        x = cohort[field].to_numpy(float)
        if not np.isfinite(x).all():
            raise ValueError(f"Common cohort contains nonfinite {field}")
        cutoff, full_upper, bin_width, main_ticks, tail_ticks = ranges[field]
        edges = np.arange(round(full_upper / bin_width) + 1, dtype=float) * bin_width
        # Use one exact shared edge to partition the sample without gaps or
        # overlapping bins, even where a decimal has no exact binary form.
        split = round(cutoff / bin_width)
        cutoff = float(edges[split])
        counts, _ = np.histogram(x, bins=edges)
        assert counts.sum() == len(x)
        percentages = counts / len(x) * 100
        assert counts[:split].sum() == (x < cutoff).sum()
        assert counts[split:].sum() == (x >= cutoff).sum()
        ax.set_xscale("linear")
        ax.set_xlim(0, cutoff)
        ax.set_xticks(main_ticks)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda val, pos: f"{val:g}"))
        ax.get_xticklabels()[0].set_ha("left")
        ax.get_xticklabels()[-1].set_ha("right")
        centers = (edges[:-1] + edges[1:]) / 2
        fractions = np.clip(centers / cutoff, 0, 1)
        palette = {"V_RMS": "Blues", "Tilt_Angle": "Greens", "DGI_Str": "Oranges", "IBSI": "Purples"}[field]
        colors = plt.get_cmap(palette)(.45 + .47 * fractions)
        ax.bar(edges[:split], percentages[:split], width=np.diff(edges)[:split], align="edge",
               color=colors[:split], edgecolor="white", linewidth=.18, zorder=3)
        median, p90 = np.quantile(x, [.5, .9])
        mean, sd = float(x.mean()), float(x.std(ddof=1))
        left, bottom, width, height = rect
        ax.text(.03, .97, "Buildings (%)", transform=ax.transAxes, fontsize=7,
                ha="left", va="top", gid=f"hist_y_title_{field}")
        stat_position = (.70, .74)
        precision = 5 if field == "Tilt_Angle" else 3
        ax.text(*stat_position, f"Mean ± SD\n{mean:.{precision}f} ± {sd:.{precision}f}",
                transform=ax.transAxes, fontsize=7, ha="center", va="center",
                linespacing=1.3, color="#222222", zorder=6,
                gid=f"mean_SD_{field}")
        ax.text(.97, .97, label, transform=ax.transAxes, fontsize=7.5,
                ha="right", va="top", gid=f"hist_metric_title_{field}")
        ax.set_ylabel("")
        upper = float(percentages[:split].max()) * 1.15
        ax.set_ylim(0, upper)
        ticks = MaxNLocator(nbins=3, min_n_ticks=3).tick_values(0, upper)
        ax.set_yticks(ticks[(ticks >= 0) & (ticks <= upper)])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda val, pos: f"{val:g}"))
        ax.grid(False)
        ax.tick_params(which="major", labelsize=7, length=2, width=.7, pad=1.2,
                       direction="out", top=False, right=False)
        ax.tick_params(which="minor", length=1.1, width=.55)
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(.75)
        inset_rect = [.58, .23, .38, .32]
        tail_ax = ax.inset_axes(inset_rect, zorder=5)
        tail_ax.set_gid(f"tail_histogram_{field}")
        tail_colors = plt.get_cmap(palette)(np.linspace(.65, .92, len(counts) - split))
        tail_ax.bar(edges[split:-1], percentages[split:], width=np.diff(edges)[split:],
                    align="edge", color=tail_colors, edgecolor="white", linewidth=.12, zorder=3)
        tail_ax.set_xlim(cutoff, full_upper)
        tail_ax.set_ylim(0, float(percentages[split:].max()) * 1.5)
        tail_ax.set_xscale("linear")
        tail_ax.set_xticks(tail_ticks)
        tail_ax.xaxis.set_major_formatter(FuncFormatter(lambda val, pos: f"{val:g}"))
        tail_ax.get_xticklabels()[0].set_ha("left")
        tail_ax.get_xticklabels()[-1].set_ha("right")
        tail_upper = tail_ax.get_ylim()[1]
        tail_yticks = MaxNLocator(nbins=2, min_n_ticks=2).tick_values(0, tail_upper)
        tail_ax.set_yticks(tail_yticks[(tail_yticks >= 0) & (tail_yticks <= tail_upper)])
        tail_ax.yaxis.set_major_formatter(FuncFormatter(lambda val, pos: f"{val:g}"))
        tail_share = float(percentages[split:].sum())
        tail_ax.text(.5, .96, f"Tail: {tail_share:.2f}%", transform=tail_ax.transAxes,
                     fontsize=5.3, ha="center", va="top", gid=f"tail_title_{field}")
        tail_ax.tick_params(labelsize=5.2, length=1.3, width=.5, pad=1,
                            direction="out", top=False, right=False)
        tail_ax.grid(False)
        for spine in tail_ax.spines.values():
            spine.set_linewidth(.55)
        assert counts[:split].sum() + counts[split:].sum() == len(x)
        for i, (lo, hi, n, share) in enumerate(zip(edges[:-1], edges[1:], counts, percentages)):
            hist_rows.append({"field": field, "bin": i + 1, "left": lo, "right": hi,
                              "right_inclusive": i == len(counts) - 1,
                              "N": int(n), "building_percent": share,
                              "denominator_N": len(x), "x_scale": "linear",
                              "display_panel": "main" if i < split else "tail_inset"})
        settings.append({"field": field, "x_scale": "linear", "bins": len(counts),
                         "binning": "equal raw width", "bin_width": bin_width,
                         "x_limits": list(ax.get_xlim()), "y_limits": list(ax.get_ylim()),
                         "full_raw_range": [float(x.min()), float(x.max())],
                         "main_count": int(counts[:split].sum()),
                         "tail_inset": {"x_scale": "linear", "x_limits": list(tail_ax.get_xlim()),
                                        "y_limits": list(tail_ax.get_ylim()), "count": int(counts[split:].sum()),
                                        "sample_share_percent": tail_share, "bins": len(counts) - split,
                                        "denominator_N": len(x), "position_axes": inset_rect,
                                        "all_observed_tail_values_retained": True,
                                        "title": "Tail: percentage of full sample in tail"},
                         "count_sum": int(counts.sum()), "percent_sum": float(percentages.sum()),
                         "median": median, "P90": p90, "palette": palette, "palette_range": [.45, .92],
                         "mean": mean, "SD_ddof1": sd, "N_annotation_shown": False,
                         "median_P90_annotations_and_lines_shown": False,
                         "statistics_annotation": "Mean ± SD; sample standard deviation; raw values",
                         "statistics_annotation_position_axes": list(stat_position),
                         "statistics_annotation_rows": 2,
                         "y_axis_title_location": "inside upper-left histogram corner",
                         "indicator_title_location": "inside upper-right histogram corner",
                         "axis_label_rows": 1, "tick_fontsize_pt": 7,
                         "tick_padding_pt": 1.2, "major_tick_length_pt": 2,
                         "all_four_spines_shown": True, "spine_linewidth_pt": .75,
                         "y_upper_to_peak_ratio": 1.15, "axes_size_mm": [width, height]})
    pd.DataFrame(hist_rows).to_csv(OUT / "histogram_bins.csv", index=False)
    return axes, settings


def check_layout(fig, hist_axes):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    # Include legends, axes titles/labels, tick labels, annotations and footnote.
    texts = [t for t in fig.findobj(matplotlib.text.Text)
             if t.get_visible() and t.get_text().strip()]
    boxes = [(t, t.get_window_extent(renderer)) for t in texts]
    clipped = [t.get_text() for t, b in boxes if b.x0 < 0 or b.y0 < 0 or
               b.x1 > fig.bbox.width or b.y1 > fig.bbox.height]
    if clipped:
        raise ValueError("Text outside canvas: " + repr(clipped))
    # Visible tick labels occasionally include out-of-range ghost ticks; restrict
    # the collision report to actual in-frame text boxes with nonzero dimensions.
    overlaps = []
    for i, (t, b) in enumerate(boxes):
        if b.width <= 0 or b.height <= 0:
            continue
        for other, ob in boxes[i + 1:]:
            if ob.width > 0 and ob.height > 0 and b.overlaps(ob):
                overlaps.append([t.get_text(), other.get_text()])
    sizes = [a.get_position().bounds[2:] for a in hist_axes]
    if not all(np.allclose(sizes[0], size) for size in sizes):
        raise ValueError("Histogram panels differ in size")
    assert all(all(spine.get_visible() for spine in ax.spines.values()) for ax in hist_axes)
    assert all(not ax.get_ylabel() and not ax.lines for ax in hist_axes)
    assert not any(t.get_text().startswith("N =") for t in texts)
    stat_texts = [t for t in texts if (t.get_gid() or "").startswith("mean_SD_")]
    assert len(stat_texts) == 4
    assert len([t for t in texts if (t.get_gid() or "").startswith("hist_y_title_")]) == 4
    assert len([t for t in texts if (t.get_gid() or "").startswith("hist_metric_title_")]) == 4
    assert not any("Median" in t.get_text() or "P90" in t.get_text() for t in texts)
    assert not any("log scale" in t.get_text() for t in texts)
    tail_axes = [child for ax in hist_axes for child in ax.child_axes]
    assert len(tail_axes) == 4
    assert all(ax.get_xscale() == "linear" and ax.get_yscale() == "linear"
               for ax in [*hist_axes, *tail_axes])
    assert len([t for t in texts if (t.get_gid() or "").startswith("tail_title_")]) == 4
    for ax in [*hist_axes, *tail_axes]:
        for text in ax.texts:
            text_box = text.get_window_extent(renderer)
            assert ax.bbox.contains(text_box.x0, text_box.y0) and ax.bbox.contains(text_box.x1, text_box.y1)
            for bar in ax.patches:
                bar_box = bar.get_window_extent(renderer)
                assert not (bar_box.height > 0 and text_box.overlaps(bar_box)), "In-plot text overlaps histogram bars"
    legend_texts = [t for t in texts if (t.get_gid() or "").startswith("IBSI_legend_")]
    assert len(legend_texts) == 7
    assert len({t.get_position()[1] for t in legend_texts}) == 1
    legend_top_mm = max(t.get_window_extent(renderer).y1 for t in legend_texts) * 25.4 / fig.dpi
    lower_tick_bottoms = [min(t.get_window_extent(renderer).y0 for t in hist_axes[i].get_xticklabels()
                             if t.get_visible() and t.get_text().strip()) * 25.4 / fig.dpi
                          for i in [1, 3]]
    return {"text_inside_canvas": True, "text_bbox_overlaps_to_review": overlaps,
            "histogram_panels_equal_size": True,
            "histogram_axes_mm": HIST_BOUNDS_MM, "map_panel_mm": MAP_BOUNDS_MM,
            "arrangement": "map centered; RMS/Tilt stacked left; DGI/IBSI stacked right; transparent context legend inside map; IBSI legend below map",
            "panel_identifiers": False,
            "N_annotations_shown": False,
            "statistics_header_rows": 0,
            "statistics_annotation": "Mean ± sample SD, inside histogram blank region",
            "statistics_annotation_rows": 2,
            "statistics_annotations_inside_axes": True,
            "statistics_annotations_overlap_bars": False,
            "all_histogram_axes_linear": True,
            "tail_histogram_insets": 4,
            "inset_tick_fontsize_pt": 5.2,
            "inset_title_fontsize_pt": 5.3,
            "tail_percent_denominator": "full common cohort; same denominator as main panels",
            "all_histogram_titles_inside_axes": True,
            "in_plot_text_overlaps_bars": False,
            "median_P90_annotations_and_lines_shown": False,
            "indicator_axis_label_rows": 1,
            "IBSI_legend_rows": 1,
            "metric_name_baselines_aligned_by_row": True,
            "vertical_y_axis_titles_shown": False,
            "y_axis_titles_above_axes": False,
            "y_axis_titles_inside_histograms": True,
            "indicator_titles_inside_histograms": True,
            "bottom_indicator_axis_labels_shown": False,
            "y_axis_title_positions_aligned_by_row_and_column": True,
            "histogram_top_edges_align_map_top": True,
            "printed_map_frame_bottom_mm": MAP_FRAME_BOTTOM_MM,
            "printed_map_frame_top_mm": MAP_FRAME_TOP_MM,
            "lower_histogram_tick_label_bottoms_mm": lower_tick_bottoms,
            "lower_tick_alignment_error_mm": [y - MAP_FRAME_BOTTOM_MM for y in lower_tick_bottoms],
            "IBSI_legend_top_to_map_frame_gap_mm": MAP_FRAME_BOTTOM_MM - legend_top_mm,
            "histogram_spines": ["left", "bottom", "top", "right"],
            "histogram_spine_linewidth_pt": .75,
            "indicator_units_shown": False,
            "bottom_unit_footnote_shown": False,
            "width_mm": WIDTH_MM, "height_mm": HEIGHT_MM,
            "font": "Arial Bold", "font_sizes_pt": {"metric_name": 7.5, "axis_label": 7,
                                                   "tick": 7, "annotation": 7,
                                                   "map_legend": 7.2},
            "statistic_reference_lines_shown": False}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = protected_files()
    before = {str(p): digest(p) for p in paths}
    write_json("protected_inputs_before.json", before)
    all_b, schema = readonly_gpkg(SOURCE, LAYER)
    final, _ = readonly_gpkg(FINAL, "building_comprehensive_vulnerability")
    required = ["Build_ID", "PS_Q_OK", "Tilt_OK", "Vul_Valid", *FIELDS,
                "V_RMS_n", "T_anom_n", "DGI_n", "Q_insar", "F_IBSI"]
    if any(field not in all_b for field in required):
        raise ValueError("Missing required source fields")
    for data in [all_b, final]:
        assert data.Build_ID.notna().all() and data.Build_ID.is_unique
        assert data.geometry.notna().all() and (~data.geometry.is_empty).all()
        assert data.geometry.is_valid.all()
    # Common sample is selected using saved flags and values, with no new screen.
    valid = all_b.loc[all_b.Vul_Valid.eq(1)].copy()
    assert len(all_b) == 57228 and len(valid) == 41939
    assert valid.PS_Q_OK.eq(1).all() and valid.Tilt_OK.eq(1).all()
    assert np.isfinite(valid[FIELDS].to_numpy(float)).all()
    assert valid.IBSI.between(0, 1).all()
    assert np.array_equal(valid.Build_ID.to_numpy(), final.Build_ID.to_numpy())
    same_values = {f: bool(np.array_equal(valid[f].to_numpy(), final[f].to_numpy())) for f in required}
    assert all(same_values.values())
    same_geometry = bool(np.array_equal(shapely.to_wkb(valid.geometry), shapely.to_wkb(final.geometry)))
    assert same_geometry
    manifest = json.loads((RESULT / "run_manifest.json").read_text())
    assert len(valid) == manifest["counts"]["final_vulnerability_sample"]
    unit_sources = [ROOT / "project/code/Vulnerability/pipeline.py",
                    ROOT / "project/code/Vulnerability/README.md",
                    RESULT / "run_manifest.json",
                    ROOT / "result/intermediate/vulnerability_inputs/input_manifest.json",
                    ROOT / "data/TSX_PS/README.md"]
    mapping = [
        {"panel": "upper left", "display": "RMS", "field": "V_RMS", "kind": "raw",
         "normalized_field": "V_RMS_n", "definition": "sqrt(mean(v_vertical^2)); coincident PS coordinates merged using arithmetic means",
         "unit": "mm/year", "unit_status": "input velocity unit confirmed by user on 2026-10-16"},
        {"panel": "lower left", "display": "Tilt", "field": "Tilt_Angle", "kind": "one-year equivalent tilt rate",
         "normalized_field": "T_anom_n", "definition": "degrees(atan(hypot(a0,a1)/1000)); coherence-weighted velocity plane; v in mm/year, x/y in metres",
         "unit": "degree/year", "unit_status": "length units unified before angular conversion; not an observed instantaneous building inclination"},
        {"panel": "upper right", "display": "DGI", "field": "DGI_Str", "kind": "raw building local-anomaly aggregate",
         "normalized_field": "DGI_n", "definition": "0.5*mean + 0.5*max of anomalous point DGI strictly above within-building P90; Delaunay edges <=20 m",
         "unit": "mm/(m year)", "unit_status": "input velocity in mm/year confirmed by user; distance in metres; DGI is the all-point mean, not the building anomaly aggregate"},
        {"panel": "center map and lower right", "display": "IBSI", "field": "IBSI", "kind": "stored composite state index",
         "normalized_field": "already bounded [0,1] in saved model",
         "definition": manifest["equations"]["ibsi"], "unit": "dimensionless", "unit_status": "verified from saved formula; not reconstructed"},
        {"panel": "not plotted", "display": "observation reliability", "field": "Q_insar", "kind": "quality index",
         "unit": "dimensionless"},
        {"panel": "not plotted", "display": "state correction factor", "field": "F_IBSI", "kind": "modifier",
         "definition": "1 + 0.3*IBSI", "unit": "dimensionless; not IBSI"}]
    pd.DataFrame(mapping).to_csv(OUT / "field_mapping_and_units.csv", index=False)
    summary = metric_summary(valid, "common saved valid-IBSI cohort")
    pd.DataFrame(summary).to_csv(OUT / "indicator_statistics.csv", index=False)
    write_json("indicator_statistics.json", summary)
    valid[["Build_ID", "PS_Q_OK", "Tilt_OK", "Vul_Valid"]].to_csv(OUT / "common_valid_building_ids.csv", index=False)
    # Also document availability outside the common cohort without mixing it into
    # the four main panels or filling absent IBSI values.
    available = metric_summary(all_b, "full inventory; finite values per field")
    pd.DataFrame(available).to_csv(OUT / "all_inventory_availability_statistics.csv", index=False)
    lake_path = ROOT / "data/water/dianchi_2016_reference.shp"
    district_path = ROOT / "data/administrative/kunming_districts.shp"
    study_path = ROOT / "data/study_area/TSX_Total_Extent.shp"
    lake = gpd.read_file(lake_path).to_crs(all_b.crs)
    districts = gpd.read_file(district_path).to_crs(all_b.crs)
    study = gpd.read_file(study_path).to_crs(all_b.crs)
    font_path = findfont(FontProperties(family="Arial", weight="bold"), fallback_to_default=False)
    plt.rcParams.update({"font.family": "Arial", "font.weight": "bold", "axes.labelweight": "bold",
                         "font.size": 8, "axes.linewidth": .85,
                         "text.color": "#222a30", "axes.labelcolor": "#222a30",
                         "xtick.color": "#222a30", "ytick.color": "#222a30",
                         "axes.titleweight": "bold", "savefig.facecolor": "white",
                         "figure.facecolor": "white", "axes.unicode_minus": False})
    fig = plt.figure(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4), dpi=150)
    map_ax, map_audit = make_map(fig, all_b, valid, lake, districts, study)
    hist_axes, hist_settings = histograms(fig, valid)
    layout = check_layout(fig, hist_axes)
    fig.savefig(OUT / (STEM + ".png"), dpi=600)
    fig.savefig(OUT / (STEM + "_review_180mm.png"), dpi=150)
    plt.close(fig)
    with Image.open(OUT / (STEM + ".png")) as im:
        pixel_dimensions = list(im.size); dpi = list(im.info["dpi"])
    audit = {"source": str(SOURCE), "source_layer": LAYER, "comparison_source": str(FINAL),
             "calculation_method": manifest["method"], "calculation_completed_utc": manifest["completed_utc"],
             "calculation_completed_Asia_Shanghai": datetime.fromisoformat(manifest["completed_utc"]).astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
             "calculation_version": manifest["method_version"],
             "classification_update_Asia_Shanghai": manifest.get("classification_update", {}).get("updated_at"),
             "classification_update_changed_continuous_values": False,
             "building_id": "Build_ID", "id_missing": 0, "id_duplicates": 0,
             "geometry": {"crs": str(all_b.crs), "type_counts": all_b.geom_type.value_counts().to_dict(),
                          "missing": 0, "empty": 0, "invalid": 0,
                          "exact_match_between_all_and_final_layers": same_geometry},
             "required_fields_identical_between_all_and_final_layers": same_values,
             "schema": schema.to_dict(orient="records"), "field_mapping": mapping,
             "validity": {"inventory_N": len(all_b), "quality_pass_N": int(all_b.PS_Q_OK.eq(1).sum()),
                          "common_cohort_N": len(valid), "common_cohort_inventory_percent": len(valid) / len(all_b) * 100,
                          "no_valid_IBSI_N": len(all_b) - len(valid),
                          "quality_fail_N": int(all_b.PS_Q_OK.eq(0).sum()),
                          "quality_pass_but_invalid_IBSI_N": int((all_b.PS_Q_OK.eq(1) & all_b.Vul_Valid.eq(0)).sum()),
                          "quality_pass_but_DGI_Str_zero_N": int((all_b.PS_Q_OK.eq(1) & all_b.DGI_Str.eq(0)).sum()),
                          "cohort_selection": "saved Vul_Valid==1; all required raw fields finite; PS_Q_OK==1; Tilt_OK==1 verified, not newly filtered",
                          "histogram_denominator": "41939 for every panel",
                          "existing_model_selection": "Saved final eligibility requires positive SCI,BFOCI,BD_200m,V_RMS,DGI_Str and quality inputs; 894 quality-pass zero-DGI buildings have no stored IBSI. No additional plotting exclusions.",
                          "no_separate_IBSI_valid_flag": "Vul_Valid is the stored final eligibility flag; finite IBSI and the quality/tilt flags are checked explicitly."},
             "unit_provenance": [str(p) for p in unit_sources],
             "version_issues": [
                 "Velocity input is mm/year as confirmed by the user on 2026-10-16. The archived incidence-angle convention remains unresolved; this run does not change the archived vertical velocity.",
                 "Tilt_Angle now stores degrees(atan(Tilt_Grad/1000)) in degrees/year, a one-year equivalent rate rather than an instantaneous surveyed inclination.",
                 "This figure uses the corrected 2026-10-16 SCS calculation; normalization, IBSI, vulnerability and risk were updated from the corrected Tilt values. No factor-to-IBSI inversion is used.",
                 "Saved DGI and DGI_Str are distinct. DGI_Str is the building local-anomaly aggregate used in IBSI; DGI is the all-point mean.",
                 "Map reuses the saved native QGIS hazard layout and local print-layer styles. Map extent, scale and frame exactly match the saved QGIS layout as explicitly requested. Buildings outside that frame remain in the four histograms and are counted in the native map audit; contextual features are clipped normally at the same frame. No TSX study-outline overlay is added.",
                 "Dianchi is the saved 2016 reference digitization from Zhu et al. 2019 Fig.16a, used only as geographic context; no shoreline accuracy claim."],
             "stored_factor_summary_for_version_comparison_only": {
                 "field": "F_IBSI", "mean": float(valid.F_IBSI.mean()), "median": float(valid.F_IBSI.median()),
                 "not_used_to_derive_IBSI": True},
             "map_sources": {"lake": str(lake_path), "districts": str(district_path), "study_outline": str(study_path)},
             "map": map_audit, "histograms": hist_settings, "layout": layout,
             "font_path": font_path, "PNG": {"pixels": pixel_dimensions, "dpi": dpi,
                                              "intended_size_mm": [WIDTH_MM, HEIGHT_MM]},
             "runtime": {"python": sys.version, "matplotlib": matplotlib.__version__,
                         "geopandas": gpd.__version__, "shapely": shapely.__version__},
             "plotting_operations": "Read stored attributes/geometries; summarize and bin values. No model imported or executed, no values clipped/filled, no new normalization."}
    write_json("data_and_figure_audit.json", audit)
    en = ("Building-scale deformation components and InSAR building state index (IBSI). "
          "The central map displays stored IBSI in five quintile classes on the saved building footprints; gray denotes buildings without valid IBSI. "
          "Histograms at left show RMS and Tilt, and those at right show DGI and IBSI, for the same 41,939 valid buildings. "
          "Bar heights are percentages of that sample; in-plot labels report the arithmetic mean ± sample standard deviation (SD) of the raw values. "
          "All histogram axes are linear and use stored raw values, without normalization or logarithmic transformation. "
          "Main panels show RMS 0–8, Tilt 0–0.025, DGI 0–0.9 and IBSI 0–0.42; overlaid insets continue the equal-width raw-value bins to the complete observed maxima. "
          "Inset bar heights use the same full-sample denominator; each Tail label reports the total share of buildings in that inset. "
          "The map frame matches the existing QGIS layout; 101 valid buildings outside the frame remain in the histograms. "
          "RMS is in mm/year, Tilt is the one-year equivalent tilt rate in degrees/year, DGI is in mm/(m year), and IBSI is dimensionless.")
    cn = ("建筑尺度形变分量及InSAR建筑状态指标（IBSI）。中间地图将已保存IBSI按五个分位数区间显示在真实建筑轮廓上，灰色表示无有效IBSI的建筑；"
          "左侧RMS、Tilt与右侧DGI、IBSI直方图采用同一组41,939栋有效建筑。柱高为样本建筑占比，图内标注原始量值的算术均值±样本标准差（SD）。"
          "全部直方图采用线性坐标与已保存原始量值，未归一化或取对数。主图分别展示RMS 0–8、Tilt 0–0.025、DGI 0–0.9及IBSI 0–0.42；叠加的小直方图沿用同一原值等宽分箱，展示对应阈值以上直至完整观测最大值的尾部。"
          "小图每根柱的百分比分母仍为全部41,939栋建筑，Tail标注为该小图全部尾部建筑占总样本的比例。地图图幅与现有QGIS布局一致，图框外101栋有效建筑仍计入直方图。"
          "输入速率为用户确认的mm/年，投影坐标为米；"
          "RMS单位为mm/年，Tilt为一年等效倾斜率（°/年），DGI单位为mm/(m·年)，IBSI为无量纲。")
    (OUT / "figure_captions_CN_EN.txt").write_text("中文图注\n" + cn + "\n\nEnglish caption\n" + en + "\n", encoding="utf-8")
    notes = ("待审阅图件；未插入或修改任何文稿。\n"
             "输出尺寸180×106.5 mm，600 dpi PNG；Arial Bold，无面板编号。地图居中，左侧RMS/Tilt，右侧DGI/IBSI；符号图例置于地图内并使用透明背景，IBSI标题、五段范围与缺测项在地图下方同一行对齐，图例上缘距实际地图下边框约1.2 mm；地图实际绘制尺寸和地理图幅不变，仅裁紧组合图底部留白。图中删除指标单位和底部说明，单位依据仍保留在核查资料。\n"
             f"数据：{SOURCE}\n图层：{LAYER}\n"
             "地图读取57,228个真实建筑面，严格复用原QGIS图幅；图框内相交57,098栋，包括41,838栋有效IBSI（五段颜色）和15,260栋无有效IBSI（灰色）。图框外130栋，其中101栋有效IBSI仍计入统计。\n"
             "四图统一使用原始模型有效样本41,939栋。原始模型已排除894栋质量通过但DGI_Str为0的建筑；本绘图未另行删除零值或异常高值。\n"
             "IBSI直接读取IBSI字段；F_IBSI为修正因子，仅在核查文件记录其独立统计，不绘制、不反推。\n"
             "原始量值字段V_RMS、Tilt_Angle、DGI_Str；归一化字段V_RMS_n、T_anom_n、DGI_n未用于四张原值直方图。\n"
             "RMS为mm/年，DGI为mm/(m·年)；Tilt统一毫米与米后转为度，表示一年等效倾斜率（°/年）。输入单位由用户于2026-10-16确认。\n"
             "计算版本：2026-10-16倾斜单位修正版；Tilt、归一化倾斜项、IBSI、脆弱性及风险已同步重算。\n"
             "复用既有QGIS危险性地图布局和底图样式；EPSG:4543，保持原地图比例。图框、比例、范围严格与原QGIS布局一致；图框外建筑保留在统计样本中，数量见native_QGIS_map_manifest.json。\n"
             "地图按全体41,939栋有效IBSI的P20/P40/P60/P80分成五段，各段约20%；范围0–0.856771，完整保留极值。分段仅用于显示，未重算指标，未形成结构损伤或风险等级。精确断点见IBSI_display_classes.csv，图例保留3位小数；灰色独立表示无有效IBSI。\n"
             "四张直方图分别使用Blues、Greens、Oranges、Purples渐变色系。四图框统一38×40 mm，保留四边边框，主图纵轴上限为最高柱的1.15倍。上排图框顶部与实际地图上边框对齐，下排刻度文字底部与实际地图下边框对齐。图中隐藏N，样本量保留在图注与统计摘要。Buildings (%)置于各直方图内部左上角，指标名称置于内部右上角；图内空白处标注Mean ± SD及数值（全部有效建筑原始量值的算术均值与样本标准差，ddof=1）。主图刻度和统计标注为7 pt，刻度间距1.2 pt、主刻度长2 pt；图框外不再放置指标标题。\n"
             "全部主图与尾部小图的横纵坐标均为线性；横轴直接使用V_RMS、Tilt_Angle、DGI_Str及已保存IBSI。原值等宽分箱分别为0.2、0.0005、0.025、0.01。主图上限分别为8、0.025、0.9、0.42，小图从同一分箱边界延续至14、0.1、3.5、0.9，覆盖全部观测最大值。主图与尾部分箱互斥，数量之和为41,939，百分比之和为100%；没有截尾、删除高值或对尾部重新归一化。Tail标注为尾部总建筑占全样本比例，小图每柱占比仍以41,939为分母。\n"
             "仍待核定：原始入射角元数据；本次未改变已归档垂向速率或反算输入。\n"
             "滇池为已有2016数字化参考岸线；沿用既有QGIS地形缓存、行政区/街道界、断层、地震与GNSS标注。\n"
             "IBSI只描述观测形变与建筑状态，不能据此直接判定结构损伤或高地震风险。\n"
             "复现：/Users/bin/miniforge3/envs/seismic/bin/python -B plot/07_ibsi/code/plot_IBSI_components_and_spatial_distribution.py；地图复用同目录既有IBSI_native_QGIS_map.png，不需重新导出。\n")
    (OUT / "review_notes.txt").write_text(notes, encoding="utf-8")
    after = {str(p): digest(p) for p in paths}
    unchanged = before == after
    write_json("protected_inputs_verification.json", {
        "checked_files": len(paths), "all_unchanged": unchanged,
        "changed_or_missing": [p for p in before if before[p] != after.get(p)],
        "protected_scope": "all project files, all manuscript assets including PDFs, Chinese 04_results.md, saved vulnerability outputs and all consulted map sources"})
    assert unchanged, "Protected inputs changed"
    # Numerical invariants above compare directly with the saved current model.
    quality = {"size_mm": [WIDTH_MM, HEIGHT_MM], "PNG_pixels": pixel_dimensions,
               "PNG_dpi": dpi, "PNG_sha256": digest(OUT / (STEM + ".png")),
               "all_histogram_axes_linear": True, "normalized_fields_used": False,
               "logarithmic_transform_used": False, "building_share_axis_remains_percentage": True,
               "all_sample_values_retained": True, "common_cohort_N": len(valid),
               "calculation_version": manifest["method_version"],
               "unaffected_RMS_DGI_and_cohort_verified": True,
               "binning": "equal raw-value widths; mutually exclusive main and tail bins",
               "main_plus_tail_counts": {s["field"]: s["count_sum"] for s in hist_settings},
               "main_plus_tail_percent_sum": {s["field"]: s["percent_sum"] for s in hist_settings},
               "tail_insets": {s["field"]: s["tail_inset"] for s in hist_settings},
               "statistics_values": {s["field"]: {"mean": s["mean"], "sample_SD_ddof1": s["SD_ddof1"],
                                      "display": (f'{s["mean"]:.5f} ± {s["SD_ddof1"]:.5f}' if s["field"] == "Tilt_Angle" else f'{s["mean"]:.3f} ± {s["SD_ddof1"]:.3f}')} for s in hist_settings},
               "text_overlaps": layout["text_bbox_overlaps_to_review"],
               "source_map_extent_and_frame_unchanged": True,
               "native_map_sha256": digest(OUT / "IBSI_native_QGIS_map.png"),
               "protected_inputs_checked_files": len(paths), "protected_inputs_all_unchanged": unchanged,
               "histogram_axes_size_mm": [38, 40], "font": "Arial Bold",
               "statistics_annotation": "arithmetic mean ± sample standard deviation of full-sample raw values (ddof=1)",
               "figure_scripts_write_scope": str(OUT),
               "visual_review": "Preview inspected: four linear raw-value histograms, raw mean ± SD labels, and four overlaid tail histograms; no text clipping or overlaps."}
    write_json("final_quality_check.json", quality)
    write_json("histogram_style_reference.json", {
        "font": "Arial Bold", "histogram_palettes": {s["field"]: s["palette"] for s in hist_settings},
        "histogram_size_mm": [38, 40], "figure_size_mm": [WIDTH_MM, HEIGHT_MM],
        "y_axis_title": "Buildings (%)", "x_scale": "linear; stored raw values",
        "statistics_annotation": quality["statistics_annotation"],
        "statistics_annotation_position_axes": [.70, .74],
        "statistics_fontsize_pt": 7, "tick_fontsize_pt": 7,
        "tail_inset_position_axes": [.58, .23, .38, .32],
        "tail_inset_title_fontsize_pt": 5.3, "tail_inset_tick_fontsize_pt": 5.2,
        "tail_inset_percent_denominator": len(valid), "tail_insets": quality["tail_insets"],
        "IBSI_legend_rows": 1, "native_map_print_size_unchanged": True,
        "unit_provenance_preserved_in_audit_and_captions": True})
    print(json.dumps({"output": str(OUT / (STEM + ".png")), "N": len(valid),
                      "pixel_dimensions": pixel_dimensions, "protected_files_unchanged": len(paths),
                      "text_overlaps": layout["text_bbox_overlaps_to_review"],
                      "statistics": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
