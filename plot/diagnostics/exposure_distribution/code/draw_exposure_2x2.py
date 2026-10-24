#!/usr/bin/env python3
"""Read existing exposure indices and draw distributions and joint counts.

No exposure/vulnerability model is imported or executed. Every run writes to
new directories. Zero/one endpoints, missingness and histogram/hexbin counts
are explicitly audited; stored index values are never renormalized or clipped.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import sys
import uuid
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-risk-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic-risk-cache")
for parent in Path(__file__).resolve().parents:
    if (parent / "project/code/paths.py").is_file():
        sys.path.insert(0, str(parent / "project/code"))
        break
else:
    raise RuntimeError("Cannot locate project/code/paths.py")

from paths import PLOT_OUTPUT_ROOT, RESULT_ROOT, STATISTICS_ROOT, WORKSPACE_ROOT

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_hex
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.ticker import FuncFormatter, MaxNLocator, NullLocator, StrMethodFormatter
import numpy as np
import pandas as pd
from PIL import Image
import scipy
from scipy.stats import spearmanr

SCRIPT = Path(__file__).resolve()
SOURCE = RESULT_ROOT / "exposure/scs_paper_method/building_exposure.gpkg"
LAYER = "building_exposure_scs"
FIELDS = ("Idx_Pop", "Idx_Econ", "Exp_Final")
LABELS = {"Idx_Pop": "Population exposure index\n(Idx_Pop)",
          "Idx_Econ": "Relative economic exposure index\n(Idx_Econ)",
          "Exp_Final": "Final exposure index\n(Exp_Final)"}
EXPECTED_N = 53513
EDGES = np.linspace(0., 1., 26)
FIGURE_SIZE = (16.5, 11.)
AXIS_BOUNDS = ((.095, .615, .34, .315), (.55, .615, .34, .315),
               (.095, .135, .34, .315), (.55, .135, .34, .315))
COLORBAR_BOUNDS = (.91, .135, .018, .315)
FONT_SIZES = {"axis_labels": 24, "ticks": 16, "annotations": 18,
              "panel_labels": 24, "colorbar_label": 24, "colorbar_ticks": 16}
PALETTE_NAME = "BuGn"
PALETTE_RANGE = (.35, .95)
HEX_GRID_SIZE = (50, 18)
HEX_EXTENT = (0., 1., 0., 1.)
EXPORT_DPI = 1200
PREVIEW_DPI = 150
STEM = "exposure_distribution_2x2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def protected_files() -> list[Path]:
    roots = (SOURCE.parent, WORKSPACE_ROOT / "project/code/Exposure", WORKSPACE_ROOT / "manuscript")
    files = {path for root in roots for path in root.rglob("*")
             if path.is_file() and not path.name.startswith(".") and "__pycache__" not in path.parts}
    files.add(WORKSPACE_ROOT / "project/code/paths.py")
    return sorted(files)


def read_existing_results() -> tuple[pd.DataFrame, dict]:
    with sqlite3.connect(SOURCE.as_uri() + "?mode=ro", uri=True) as connection:
        schema = pd.read_sql_query(f'PRAGMA table_info("{LAYER}")', connection)
        required = ("Build_ID", *FIELDS)
        missing = sorted(set(required) - set(schema["name"]))
        if missing:
            raise ValueError(f"Missing fields: {missing}")
        selection = ",".join(f'"{field}"' for field in required)
        frame = pd.read_sql_query(f'SELECT {selection} FROM "{LAYER}" ORDER BY "Build_ID"', connection)
    if frame["Build_ID"].isna().any() or not frame["Build_ID"].is_unique:
        raise ValueError("The existing exposure layer requires unique, non-null Build_ID values")
    source_manifest = json.loads((SOURCE.parent / "run_manifest.json").read_text(encoding="utf-8"))
    if len(frame) != source_manifest["output_rows"]:
        raise ValueError("Exposure sample count differs from its existing run manifest")
    audit = {"source": str(SOURCE), "layer": LAYER, "schema": schema.to_dict(orient="records"),
             "sample_definition": "All existing exposure-layer rows; no vulnerability sample or additional quality/positivity filters",
             "row_count": len(frame), "unique_build_id_count": int(frame["Build_ID"].nunique()),
             "null_build_id_count": 0, "duplicate_build_id_count": 0,
             "expected_sample_count": EXPECTED_N, "matches_expected_sample_count": len(frame) == EXPECTED_N,
             "source_manifest_count": source_manifest["output_rows"],
             "units": "All three indices are stored, dimensionless relative indices on [0,1]",
             "economic_interpretation": "Relative economic exposure index; neither an absolute asset valuation nor an expected loss",
             "fields": {}}
    for field in FIELDS:
        original = frame[field]
        numeric = pd.to_numeric(original, errors="coerce")
        all_values = numeric.to_numpy(dtype=float)
        values = all_values[np.isfinite(all_values)]
        if not len(values):
            raise ValueError(f"No finite values in {field}")
        outside = int(np.count_nonzero((values < 0) | (values > 1)))
        if outside:
            raise ValueError(f"{field}: {outside} stored values outside [0,1]; no clipping is permitted")
        quantiles = np.quantile(values, [0., .01, .05, .25, .5, .75, .95, .99, 1.])
        audit["fields"][field] = {
            "valid_n": len(values), "missing_n": int(numeric.isna().sum()),
            "infinite_n": int(np.isinf(all_values).sum()),
            "non_numeric_n": int((original.notna() & numeric.isna()).sum()), "out_of_range_n": outside,
            "zero_n": int(np.count_nonzero(values == 0)), "one_n": int(np.count_nonzero(values == 1)),
            "zero_share_pct": float(np.mean(values == 0) * 100),
            "one_share_pct": float(np.mean(values == 1) * 100),
            "mean": float(values.mean()), "std_ddof1": float(values.std(ddof=1)),
            "quantiles": dict(zip(("min", "p01", "p05", "p25", "p50", "p75", "p95", "p99", "max"), quantiles.tolist()))}
        frame[field] = numeric
    return frame, audit


def histogram_tables(frame: pd.DataFrame, audit: dict, stats_dir: Path) -> dict[str, pd.DataFrame]:
    tables, exclusions = {}, []
    for field in FIELDS:
        values_all = frame[field].to_numpy(dtype=float)
        valid = np.isfinite(values_all)
        values = values_all[valid]
        counts, _ = np.histogram(values, bins=EDGES)
        if int(counts.sum()) != len(values):
            raise AssertionError(f"Histogram lost observations: {field}")
        percentages = counts / len(values) * 100
        if not np.isclose(percentages.sum(), 100., rtol=0, atol=1e-10):
            raise AssertionError(f"Histogram percentages fail to sum to 100: {field}")
        record = audit["fields"][field]
        table = pd.DataFrame({"field": field, "bin_index": np.arange(25),
                              "left_edge": EDGES[:-1], "right_edge": EDGES[1:],
                              "right_inclusive": [False] * 24 + [True], "count": counts,
                              "percentage": percentages, "valid_n": len(values),
                              "zero_n": record["zero_n"], "one_n": record["one_n"]})
        table.to_csv(stats_dir / f"{field}_bins.csv", index=False, float_format="%.17g")
        tables[field] = table
        exclusions.extend({"field": field, "Build_ID": int(building_id), "reason": "Non-finite stored value"}
                          for building_id in frame.loc[~valid, "Build_ID"])
    pd.concat(tables.values()).to_csv(stats_dir / "histogram_bins.csv", index=False, float_format="%.17g")
    pd.DataFrame(exclusions, columns=["field", "Build_ID", "reason"]).to_csv(stats_dir / "panel_exclusions.csv", index=False)
    frame.to_csv(stats_dir / "stored_indices_snapshot.csv", index=False, float_format="%.17g")
    frame[["Build_ID"]].to_csv(stats_dir / "exposure_building_ids.csv", index=False)
    rows = [{"field": field, **{key: value for key, value in record.items() if key != "quantiles"}, **record["quantiles"]}
            for field, record in audit["fields"].items()]
    pd.DataFrame(rows).to_csv(stats_dir / "field_audit.csv", index=False, float_format="%.17g")
    return tables


def paired_analysis(frame: pd.DataFrame, stats_dir: Path) -> tuple[pd.DataFrame, dict]:
    valid = np.isfinite(frame[["Idx_Pop", "Idx_Econ"]].to_numpy(dtype=float)).all(axis=1)
    pairs = frame.loc[valid, ["Build_ID", "Idx_Pop", "Idx_Econ"]].copy()
    if len(pairs) < 3 or pairs["Idx_Pop"].nunique() < 2 or pairs["Idx_Econ"].nunique() < 2:
        raise ValueError("Spearman correlation requires at least three paired values with variable indices")
    statistic = spearmanr(pairs["Idx_Pop"], pairs["Idx_Econ"], alternative="two-sided")
    correlation = {"x_field": "Idx_Pop", "y_field": "Idx_Econ", "paired_valid_n": len(pairs),
                   "excluded_non_finite_pairs": int((~valid).sum()), "spearman_rho": float(statistic.statistic),
                   "two_sided_p_value": float(statistic.pvalue), "method": "scipy.stats.spearmanr; paired finite stored values; average ranks for ties; no resampling",
                   "x_zero_n": int(pairs["Idx_Pop"].eq(0).sum()), "x_one_n": int(pairs["Idx_Pop"].eq(1).sum()),
                   "y_zero_n": int(pairs["Idx_Econ"].eq(0).sum()), "y_one_n": int(pairs["Idx_Econ"].eq(1).sum())}
    write_json(stats_dir / "spearman_correlation.json", correlation)
    pd.DataFrame([correlation]).to_csv(stats_dir / "spearman_correlation.csv", index=False, float_format="%.17g")
    pairs[["Build_ID"]].to_csv(stats_dir / "hexbin_building_ids.csv", index=False)
    frame.loc[~valid, ["Build_ID", "Idx_Pop", "Idx_Econ"]].to_csv(stats_dir / "hexbin_excluded_pairs.csv", index=False)
    return pairs, correlation


def set_style() -> str:
    font = findfont(FontProperties(family="Arial", weight="bold"), fallback_to_default=False)
    plt.rcParams.update({"font.family": "Arial", "font.weight": "bold", "font.size": 16,
                         "axes.labelweight": "bold", "axes.titleweight": "bold", "axes.labelsize": 24,
                         "xtick.labelsize": 16, "ytick.labelsize": 16, "axes.linewidth": 2.,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "xtick.major.width": 1.6, "ytick.major.width": 1.6,
                         "xtick.major.size": 5., "ytick.major.size": 5.,
                         "figure.facecolor": "white", "axes.facecolor": "white",
                         "savefig.facecolor": "white", "savefig.transparent": False,
                         "pdf.fonttype": 42, "svg.fonttype": "path", "axes.formatter.use_mathtext": False})
    return font


def palette():
    return LinearSegmentedColormap.from_list("BuGn_exposure", plt.get_cmap(PALETTE_NAME)(np.linspace(*PALETTE_RANGE, 256)))


def configure_axes(ax) -> None:
    ax.tick_params(pad=5)
    for text in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        text.set_fontfamily("Arial")
        text.set_fontweight("bold")
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:.1f}"))


def aligned_identifiers(fig, axes: list) -> list:
    width, height = fig.get_size_inches()
    labels = []
    for letter, ax in zip("abcd", axes):
        box = ax.get_position()
        labels.append(fig.text(box.x0 - 8 / (72 * width), box.y1 + 10 / (72 * height), f"({letter})",
                               fontsize=FONT_SIZES["panel_labels"], ha="right", va="bottom", bbox=None))
    return labels


def check_layout(fig, axes: list, identifiers: list, annotations: list) -> dict:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    checked = [*identifiers, *annotations]
    for ax in fig.axes:
        checked.extend([ax.xaxis.label, ax.yaxis.label, ax.title])
        for coordinate in (ax.xaxis, ax.yaxis):
            low, high = sorted(coordinate.get_view_interval())
            checked.extend(tick.label1 for tick in coordinate.get_major_ticks()
                           if low - 1e-12 <= tick.get_loc() <= high + 1e-12)
            checked.extend(tick.label2 for tick in coordinate.get_major_ticks()
                           if low - 1e-12 <= tick.get_loc() <= high + 1e-12)
    visible = [text for text in checked if text.get_visible() and text.get_text()]
    boxes = [text.get_window_extent(renderer) for text in visible]
    for text, box in zip(visible, boxes):
        if box.x0 < -.2 or box.y0 < -.2 or box.x1 > fig.bbox.width + .2 or box.y1 > fig.bbox.height + .2:
            raise ValueError("Clipped figure text: " + text.get_text())
    overlaps = []
    for index, (text, box) in enumerate(zip(visible, boxes)):
        for other, other_box in zip(visible[index + 1:], boxes[index + 1:]):
            if box.overlaps(other_box):
                overlaps.append((text.get_text(), other.get_text()))
    if overlaps:
        raise ValueError(f"Text overlaps: {overlaps}")
    a, b, c, d = [text.get_window_extent(renderer) for text in identifiers]
    errors = {"top_row_top_px": abs(a.y1 - b.y1), "bottom_row_top_px": abs(c.y1 - d.y1),
              "left_column_right_px": abs(a.x1 - c.x1), "right_column_right_px": abs(b.x1 - d.x1)}
    if max(errors.values()) > 1e-6:
        raise ValueError("Panel identifiers are not aligned")
    return {"text_inside_canvas": True, "no_text_overlap": True, "alignment_errors_px": errors,
            "identifier_position": "Outside upper-left corner; 8 pt left and 10 pt above each spine; no background box",
            "all_panel_axes_same_size": all(np.allclose(ax.get_position().bounds[2:], axes[0].get_position().bounds[2:]) for ax in axes)}


def create_figure(tables: dict, audit: dict, pairs: pd.DataFrame, correlation: dict, stats_dir: Path):
    fig = plt.figure(figsize=FIGURE_SIZE, dpi=100)
    axes = [fig.add_axes(bounds) for bounds in AXIS_BOUNDS]
    cmap = palette()
    colors = [to_hex(value) for value in cmap((EDGES[:-1] + EDGES[1:]) / 2)]
    annotations, panel_parameters = [], []
    for ax, field, letter in zip(axes[:3], FIELDS, "abc"):
        table = tables[field]
        ax.bar(table["left_edge"], table["percentage"], width=np.diff(EDGES), align="edge",
               color=colors, edgecolor="white", linewidth=.5)
        ax.set(xlim=(0, 1), ylim=(0, float(table["percentage"].max()) * 1.30),
               xlabel=LABELS[field], ylabel="Building share (%)", xticks=np.linspace(0, 1, 6))
        ax.xaxis.labelpad = ax.yaxis.labelpad = 10
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=3, prune="upper"))
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        configure_axes(ax)
        annotations.append(ax.text(.97, .965, f"N = {audit['fields'][field]['valid_n']:,}",
                                   fontsize=18, transform=ax.transAxes, ha="right", va="top", color="#222222"))
        panel_parameters.append({"panel": letter, "field": field, "valid_n": audit["fields"][field]["valid_n"],
                                 "x_label": ax.get_xlabel(), "y_label": ax.get_ylabel(),
                                 "x_limits": list(ax.get_xlim()), "y_limits": list(ax.get_ylim()),
                                 "bin_edges": EDGES.tolist(), "bin_colors": colors})

    ax = axes[3]
    norm = LogNorm(vmin=1)
    hb = ax.hexbin(pairs["Idx_Pop"], pairs["Idx_Econ"], gridsize=HEX_GRID_SIZE, extent=HEX_EXTENT,
                   mincnt=1, cmap=cmap, norm=norm, edgecolors="none", linewidths=0, rasterized=False)
    counts = np.asarray(hb.get_array())
    if not np.array_equal(counts, np.round(counts)) or int(counts.sum()) != len(pairs):
        raise AssertionError("Hexbin must count every paired-valid building exactly once")
    maximum = int(counts.max())
    norm.vmax = float(10 ** max(1, int(np.ceil(np.log10(maximum)))))
    centers = hb.get_offsets()
    pd.DataFrame({"hex_index": np.arange(len(counts)), "population_index_center": centers[:, 0],
                  "economic_index_center": centers[:, 1], "building_count": counts.astype(int)}).to_csv(
                      stats_dir / "hexbin_counts.csv", index=False, float_format="%.17g")
    polygon = hb.get_paths()[0].vertices
    pd.DataFrame(polygon, columns=["relative_x", "relative_y"]).to_csv(stats_dir / "hexbin_polygon_template.csv", index=False, float_format="%.17g")
    # A small margin displays whole cells whose centers lie at index 0 or 1.
    dx, dy = 1 / HEX_GRID_SIZE[0], 1 / HEX_GRID_SIZE[1]
    ax.set(xlim=(-dx / 2 - 1e-8, 1 + dx / 2 + 1e-8), ylim=(-dy / 3 - 1e-8, 1 + dy / 3 + 1e-8),
           xlabel=LABELS["Idx_Pop"], ylabel="Relative economic index\n(Idx_Econ)",
           xticks=np.linspace(0, 1, 6), yticks=np.linspace(0, 1, 6))
    ax.xaxis.labelpad = ax.yaxis.labelpad = 10
    configure_axes(ax)
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:.1f}"))
    rho_label = f"{correlation['spearman_rho']:.3f}".replace("-", "−")
    annotations.append(ax.text(.035, 1.025, f"N = {len(pairs):,};  Spearman ρ = {rho_label}",
                               transform=ax.transAxes, ha="left", va="bottom", fontsize=18,
                               color="#222222"))
    cax = fig.add_axes(COLORBAR_BOUNDS)
    colorbar = fig.colorbar(hb, cax=cax)
    # Matplotlib otherwise rasterizes a finely segmented colorbar automatically.
    if colorbar.solids is not None:
        colorbar.solids.set_rasterized(False)
    colorbar.set_label("Building count (log scale)", fontsize=24, fontweight="bold", labelpad=12)
    colorbar.set_ticks(10. ** np.arange(int(np.log10(norm.vmin)), int(np.log10(norm.vmax)) + 1))
    colorbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{int(value):,}"))
    colorbar.ax.yaxis.set_minor_locator(NullLocator())
    colorbar.ax.tick_params(labelsize=16, width=1.6, length=5, pad=5)
    colorbar.outline.set_linewidth(1.6)
    for label in colorbar.ax.get_yticklabels():
        label.set_fontfamily("Arial")
        label.set_fontweight("bold")
    identifiers = aligned_identifiers(fig, axes)
    layout = check_layout(fig, axes, identifiers, annotations)
    hex_parameters = {"x_field": "Idx_Pop", "y_field": "Idx_Econ", "paired_valid_n": len(pairs),
                      "x_label": ax.get_xlabel(), "y_label": ax.get_ylabel(),
                      "annotation_position_axes_fraction": [.035, 1.025],
                      "gridsize": list(HEX_GRID_SIZE), "extent": list(HEX_EXTENT), "mincnt": 1,
                      "weighting": "Unweighted counts of all paired-valid buildings; no sampling",
                      "xscale": "linear", "yscale": "linear", "color_normalization": "LogNorm (base-10 ticks)",
                      "color_vmin": float(norm.vmin), "color_vmax": float(norm.vmax),
                      "color_vmax_rule": "Next power of ten at or above maximum occupied-cell count",
                      "occupied_cells": len(counts), "minimum_occupied_count": int(counts.min()),
                      "maximum_occupied_count": maximum, "sum_of_counts": int(counts.sum()),
                      "zero_indicator_values_retained": True, "coordinate_endpoints_retained": True,
                      "zero_count_empty_cells": "Not drawn; mincnt=1 affects empty cells, not zero-valued index observations",
                      "view_limits": {"x": list(ax.get_xlim()), "y": list(ax.get_ylim())},
                      "view_margin": "Half-cell x and third-cell y padding retains complete boundary-cell polygons",
                      "colorbar_label": "Building count (log scale)", "colorbar_tick_values": colorbar.get_ticks().tolist(),
                      "rasterized": False}
    write_json(stats_dir / "hexbin_parameters.json", hex_parameters)
    panel_parameters.append({"panel": "d", **hex_parameters, "spearman_rho": correlation["spearman_rho"]})
    return fig, {"layout_checks": layout, "panels": panel_parameters}


def export_figure(fig, work_dir: Path, final_dir: Path | None) -> dict:
    preview = work_dir / f"{STEM}_preview.png"
    fig.savefig(preview, dpi=PREVIEW_DPI, facecolor="white", transparent=False)
    files = {"preview": str(preview)}
    if final_dir is not None:
        for extension in ("pdf", "svg"):
            path = work_dir / f"{STEM}.{extension}"
            fig.savefig(path, facecolor="white", transparent=False)
            data = path.read_bytes()
            if extension == "svg":
                fonts = set(re.findall(rb'id="([A-Za-z0-9_-]*MT)-[0-9a-f]+"', data))
                if b"<image" in data or fonts != {b"Arial-BoldMT"}:
                    raise AssertionError(f"SVG must use vector marks and Arial Bold only: {fonts}")
            else:
                fonts = re.findall(rb"/BaseFont\s*/([^\s/>]+)", data)
                if b"/Subtype /Image" in data or not fonts or any(b"Arial-BoldMT" not in name for name in fonts):
                    raise AssertionError(f"PDF must use vector marks and Arial Bold only: {fonts}")
            files[extension] = str(path)
        png = work_dir / f"{STEM}_1200dpi.png"
        print("Rendering 1200-dpi PNG ...", flush=True)
        fig.savefig(png, dpi=EXPORT_DPI, facecolor="white", transparent=False)
        previous_limit = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = None
            with Image.open(png) as image:
                pixels, dpi = image.size, image.info.get("dpi")
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit
        if pixels != tuple(round(value * EXPORT_DPI) for value in FIGURE_SIZE) or dpi is None or abs(dpi[0] - EXPORT_DPI) > .1:
            raise AssertionError(f"Incorrect PNG resolution: {pixels}/{dpi}")
        files.update({"png": str(png), "png_pixels": list(pixels), "png_dpi_metadata": list(dpi), "vector_formats_verified": True})
        finals = {}
        for extension in ("png", "pdf", "svg"):
            original = Path(files[extension])
            final = final_dir / original.name
            shutil.copy2(original, final)
            if sha256(original) != sha256(final):
                raise AssertionError("Final file differs from work export")
            finals[extension] = str(final)
        files["finals"] = finals
        fig.set_dpi(100)
        fig.canvas.draw()
    plt.close(fig)
    gc.collect()
    return files


def run(preview_only: bool = False) -> dict:
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    protected = protected_files()
    before = {str(path): sha256(path) for path in protected}
    created = datetime.now(ZoneInfo("Asia/Shanghai"))
    run_id = created.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    work_dir = PLOT_OUTPUT_ROOT / "diagnostics/exposure_distribution/output" / run_id
    stats_dir = STATISTICS_ROOT / "Exposure/distribution_analysis" / run_id
    final_dir = None if preview_only else PLOT_OUTPUT_ROOT / "diagnostics/exposure_distribution/output/final" / run_id
    for directory in (work_dir, stats_dir, *([final_dir] if final_dir else [])):
        directory.mkdir(parents=True, exist_ok=False)
    frame, audit = read_existing_results()
    tables = histogram_tables(frame, audit, stats_dir)
    pairs, correlation = paired_analysis(frame, stats_dir)
    audit["hexbin_paired_valid_n"] = len(pairs)
    write_json(stats_dir / "sample_audit.json", audit)
    print(f"Existing exposure sample {len(frame):,}; paired N {len(pairs):,}; Spearman rho {correlation['spearman_rho']:.8f}", flush=True)
    font_file = set_style()
    fig, details = create_figure(tables, audit, pairs, correlation, stats_dir)
    files = export_figure(fig, work_dir, final_dir)
    after = {str(path): sha256(path) for path in protected}
    if before != after:
        raise AssertionError("Original exposure result, model, shared paths or manuscript changed during plotting")
    parameters = {"run_id": run_id, "created_Asia_Shanghai": created.isoformat(),
                  "input": str(SOURCE), "input_sha256": before[str(SOURCE)], "input_layer": LAYER,
                  "script": str(SCRIPT), "script_sha256": sha256(SCRIPT),
                  "shared_path_module": str(WORKSPACE_ROOT / "project/code/paths.py"),
                  "value_handling": "Stored values only; no recomputation, normalization, clipping, missing-value filling or vulnerability-sample selection",
                  "histogram_edges": EDGES.tolist(), "histogram_interval_convention": "[left,right), final bin [0.96,1] includes 1",
                  "histogram_denominator": "Each field's own finite N from the existing exposure layer",
                  "font_family": "Arial", "font_weight": "bold", "font_file": font_file, "font_sizes_pt": FONT_SIZES,
                  "palette": {"name": PALETTE_NAME, "truncated_range": list(PALETTE_RANGE),
                              "histogram_mapping": "Bin center, on [0,1], light to dark as stored index value increases",
                              "hexbin_mapping": "Raw building count through LogNorm, light to dark; no logarithm of x/y indices"},
                  "background": "Opaque white; no overall title or panel-label background boxes",
                  "figure_size_inches": list(FIGURE_SIZE), "main_axis_bounds": [list(bounds) for bounds in AXIS_BOUNDS],
                  "colorbar_bounds": list(COLORBAR_BOUNDS), "dpi": EXPORT_DPI, "preview_dpi": PREVIEW_DPI,
                  "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                               "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
                  "work_directory": str(work_dir), "statistics_directory": str(stats_dir),
                  "final_directory": str(final_dir) if final_dir else None, "correlation": correlation,
                  **details, "files": files}
    write_json(stats_dir / "protected_input_hashes.json", {"unchanged": True, "sha256_before_and_after": before})
    write_json(stats_dir / "plot_parameters.json", parameters)
    shutil.copy2(SCRIPT, stats_dir / "draw_exposure_2x2_snapshot.py")
    (stats_dir / "README.md").write_text(
        "# Existing exposure distribution analysis\n\n"
        f"Source: {SOURCE}\n\nLayer: {LAYER}\n\n"
        f"Existing sample: {len(frame):,} unique buildings. No vulnerability cohort is used.\n\n"
        "Histograms use the stored Idx_Pop, Idx_Econ and Exp_Final, with common np.linspace(0,1,26) edges. Heights are count / field-specific finite N * 100. The final bin includes 1. All zeros and endpoints are retained; non-finite observations are recorded without filling.\n\n"
        "Panel (d) uses paired-finite Idx_Pop and Idx_Econ. Color represents unweighted building counts through LogNorm; the index axes remain linear. mincnt=1 omits empty cells, not zero-valued index observations. Hex-cell counts sum to paired N. The full source index snapshot, occupied-cell centers/counts and relative polygon vertices are saved for reproducibility.\n\n"
        f"Spearman rho = {correlation['spearman_rho']:.17g}; paired N = {len(pairs):,}; two-sided p = {correlation['two_sided_p_value']:.17g}.\n\n"
        "Idx_Econ is a relative economic exposure index, not actual asset value or expected loss. All labels are English, Arial Bold. BuGn colors, white background, 24 pt axis/colorbar labels and panel IDs, 16 pt ticks, 18 pt N/correlation.\n\n"
        f"Code: {SCRIPT}\n\nWork and preview: {work_dir}\n\nFinal: {final_dir}\n\n"
        "Original result/model/manuscript hashes were identical before and after plotting. Each run creates new directories.\n", encoding="utf-8")
    write_json(work_dir / "figure_manifest.json", parameters)
    if final_dir:
        shutil.copy2(work_dir / "figure_manifest.json", final_dir / "figure_manifest.json")
    print(json.dumps({"work": str(work_dir), "statistics": str(stats_dir), "final": str(final_dir) if final_dir else None,
                      "preview": files["preview"], "protected_files_unchanged": len(protected)}, indent=2), flush=True)
    return parameters


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-only", action="store_true", help="Create a new audit/preview run without final exports")
    args = parser.parse_args()
    run(preview_only=args.preview_only)
