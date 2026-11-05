#!/usr/bin/env python3
"""Editable Figure 5 draft: exact A4 page and physical point-size typography.

Preserve the adopted data panels at their manuscript positions. Font sizes are
PDF point sizes, with no export/crop/downscale step. Formal outputs are read-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic_risk_mpl")
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "work"  # never the adopted files in layout/
SOURCE = ROOT / "plot/05_distance_site_response/code/combine_hazard_site_response.py"
sys.path[:0] = [str(ROOT / "project/code"), str(ROOT / "plot/shared")]
spec = importlib.util.spec_from_file_location("figure05_original", SOURCE)
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
site = original.site
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib._mathtext as mathtext_engine
from matplotlib.mathtext import MathTextParser
from matplotlib.transforms import ScaledTranslation
import numpy as np
import pandas as pd

PAGE_MM = (210.0, 297.0)
PT_PER_MM = 72.0 / 25.4
SCALE = 0.28720211340331364
SOURCE_PAGE_PT = (1299.6809375, 1038.0590625)
GRAPH_MM = (131.6817534, SOURCE_PAGE_PT[1] * SCALE / PT_PER_MM)
GRAPH_TOP_LEFT_MM = ((PAGE_MM[0] - GRAPH_MM[0]) / 2, 25.0)
# Adopted vector PDF data rectangles (PDF bottom-left coordinates, pt).
SOURCE_AXES_PT = {
    "a": (85.3615625, 593.0990625, 547.2, 439.2),
    "b": (733.3615625, 593.0990625, 547.2, 439.2),
    "c": (85.3615625, 60.2990625, 547.2, 439.2),
    "d": (733.3615625, 60.2990625, 547.2, 439.2),
}
FONTS_PT = {
    "axis_titles": 8.0, "axis_ticks": 6.0,
    "colorbar_titles": 7.0, "colorbar_base_10": 6.0,
    "colorbar_exponents": 4.0, "fault_legends": 7.0,
    "Rrup_legend": 7.0, "model_parameters": 6.0,
    "urban_site_notes": 5.5, "AF_equals_1": 5.0,
}


def digest(path):
    return site.fingerprint(Path(path))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def axes_rect(key):
    page_w, page_h = (x * PT_PER_MM for x in PAGE_MM)
    left = GRAPH_TOP_LEFT_MM[0] * PT_PER_MM
    bottom = page_h - GRAPH_TOP_LEFT_MM[1] * PT_PER_MM - SOURCE_PAGE_PT[1] * SCALE
    x, y, w, h = SOURCE_AXES_PT[key]
    return [(left + x * SCALE) / page_w, (bottom + y * SCALE) / page_h,
            w * SCALE / page_w, h * SCALE / page_h]


def scale_graphics(ax):
    """Keep original final-paper line/marker sizes while changing typography."""
    for line in ax.lines:
        line.set_linewidth(line.get_linewidth() * SCALE)
        line.set_markersize(line.get_markersize() * SCALE)
        line.set_markeredgewidth(line.get_markeredgewidth() * SCALE)
        for effect in line.get_path_effects():
            gc = getattr(effect, "_gc", {})
            if "linewidth" in gc:
                gc["linewidth"] *= SCALE
    for collection in ax.collections:
        collection.set_linewidth(np.asarray(collection.get_linewidth()) * SCALE)
    for patch in ax.patches:
        patch.set_linewidth(patch.get_linewidth() * SCALE)
    for spine in ax.spines.values():
        spine.set_linewidth(2.8 * SCALE)
    ax.tick_params(axis="both", which="major", length=6 * SCALE,
                   width=2.8 * SCALE, pad=7 * SCALE, labelsize=FONTS_PT["axis_ticks"])
    ax.xaxis.labelpad = ax.yaxis.labelpad = 4 * SCALE
    ax.xaxis.label.set_fontsize(FONTS_PT["axis_titles"])
    ax.yaxis.label.set_fontsize(FONTS_PT["axis_titles"])


def bbox_pt(artist, renderer, fig):
    box = artist.get_window_extent(renderer)
    return [float(v * 72 / fig.dpi) for v in (box.x0, box.y0, box.x1, box.y1)]


def build(output):
    output = output.resolve()
    if not (output.is_relative_to(ROOT / "drafts") or output.is_relative_to(DEFAULT_OUTPUT)):
        raise ValueError("A4 drafts may only be written below drafts/ or layout/work/")
    output.mkdir(parents=True, exist_ok=True)
    run = ROOT / "result/statistics/Hazard/site_effects/current"
    composition = ROOT / "plot/05_distance_site_response/output/current"
    metadata = json.loads((composition / "analysis_metadata.json").read_text())
    audit = json.loads((run / "gmpe_response_audit.json").read_text())
    context = json.loads((run / "urban_vs30_context.json").read_text())
    input_path = Path(context["source"])
    quantile_path = original.QUANTILE_TABLE
    protected_paths = [SOURCE, Path(site.__file__), input_path, quantile_path,
                       run / "gmpe_fixed_response_grid.csv", run / "gmpe_response_audit.json",
                       run / "urban_vs30_context.json", composition / "analysis_metadata.json",
                       composition / (original.FIGURE_STEM + ".pdf"),
                       ROOT / "plot/05_distance_site_response/output/final/figure05.png",
                       ROOT / "manuscript/figures/jpg/Figure5.jpg",
                       ROOT / "manuscript/pdf/manuscript.pdf", ROOT / "plot/figure_index.json"]
    before = [digest(p) for p in protected_paths]
    buildings = site.read_buildings(input_path)
    buildings = buildings.loc[np.isfinite(buildings.PGA_Final_g)].copy()
    depth = float(audit["model_configuration"]["equivalent_depth_km"])
    buildings["Horizontal_Distance_km"] = np.sqrt(np.maximum(buildings.Dom_Rrup ** 2 - depth ** 2, 0))
    quantiles = pd.read_csv(quantile_path)
    frame = pd.read_csv(run / "gmpe_fixed_response_grid.csv")
    if len(buildings) != metadata["building_count"]:
        raise ValueError("Building inventory does not match the adopted Figure 5")
    if not np.allclose(frame.PGA_g, site.gmpe.predict_pga(frame.Mw, frame.Rrup_Input_km, frame.Vs30_m_s)[0], rtol=1e-12, atol=1e-14):
        raise ValueError("Stored GMPE curves do not match the project model")
    reference_pga = site.gmpe.predict_pga(frame.Mw, frame.Rrup_Input_km, site.REFERENCE_VS30)[0]
    if not np.allclose(frame.AF_760, frame.PGA_g / reference_pga, rtol=1e-12, atol=1e-14):
        raise ValueError("Stored AF curves do not match the 760 m/s reference")
    style = {**site.STYLE, "font.size": 6, "axes.labelsize": 8,
             "xtick.labelsize": 6, "ytick.labelsize": 6, "legend.fontsize": 7,
             "axes.linewidth": 2.8 * SCALE,
             "xtick.major.width": 2.8 * SCALE, "ytick.major.width": 2.8 * SCALE}
    old_shrink = mathtext_engine.SHRINK_FACTOR
    # Matplotlib normally makes superscripts 70% of the base. The requested
    # physical values are exactly 4 pt over a 6 pt base (2/3), only in this process.
    mathtext_engine.SHRINK_FACTOR = FONTS_PT["colorbar_exponents"] / FONTS_PT["colorbar_base_10"]
    MathTextParser._parse_cached.cache_clear()
    try:
        with plt.rc_context(style):
            fig = plt.figure(figsize=tuple(x / 25.4 for x in PAGE_MM), facecolor="white", dpi=144)
            axes = {key: fig.add_axes(axes_rect(key)) for key in "abcd"}
            color_axes = [axes[k].inset_axes([0.10, 0.18, 0.48, 0.035]) for k in "ab"]
            distance_info = original.draw_distance_panels(fig, [axes[k] for k in "ab"], color_axes, buildings, quantiles)
            handles = site.draw_fixed_gmpe_response([axes[k] for k in "cd"], frame,
                                                   urban_context=context, panel_labels=("", ""))
            assert distance_info == metadata["distance_panel_details"]
            for ax in axes.values():
                scale_graphics(ax)
            for key in "ab":
                ax = axes[key]
                # Retain the title anchor. A compact line spacing keeps the
                # enlarged 8 pt two-line title clear of the lower data panel.
                ax.xaxis.label.set_linespacing(1.0)
                ax.get_legend().remove()
                ratio = 19 * SCALE / FONTS_PT["fault_legends"]
                ax.legend(frameon=False, loc="upper right", fontsize=FONTS_PT["fault_legends"],
                          handlelength=2.1 * ratio, handletextpad=0.8 * ratio,
                          borderaxespad=0.5 * ratio, borderpad=0.4 * ratio, labelspacing=0.5 * ratio)
            for ax in color_axes:
                ax.xaxis.label.set_fontsize(FONTS_PT["colorbar_titles"])
                ax.xaxis.labelpad = 4 * SCALE
                ax.tick_params(which="major", labelsize=FONTS_PT["colorbar_base_10"],
                               length=3.5 * SCALE, width=0.8 * SCALE, pad=3.5 * SCALE)
                ax.tick_params(which="minor", length=2 * SCALE, width=0.6 * SCALE)
                for spine in ax.spines.values():
                    spine.set_linewidth(2.8 * SCALE)
            for key in "cd":
                for text in list(axes[key].texts):
                    if not text.get_text():
                        text.remove()
                    elif text.get_text() == "AF = 1":
                        text.set_fontsize(FONTS_PT["AF_equals_1"])
                    else:
                        text.set_fontsize(FONTS_PT["urban_site_notes"])
                        # 5.5 pt cannot fit the original narrow band: preserve its
                        # vertical anchor and shift only this label 1.1 mm right
                        # so its left edge clears the y-axis (originally -0.7 mm).
                        text.set_transform(text.get_transform() + ScaledTranslation(1.1 / 25.4, 0, fig.dpi_scale_trans))
            ratio = 24 * SCALE / FONTS_PT["Rrup_legend"]
            legend = axes["d"].legend(handles=handles, loc="upper right", bbox_to_anchor=(0.97, 0.97),
                                      labelspacing=0.25 * ratio, handlelength=2.2 * ratio,
                                      handletextpad=0.8 * ratio, borderpad=0, borderaxespad=0,
                                      frameon=False, fontsize=FONTS_PT["Rrup_legend"])
            note = axes["d"].text(0.97, 0.65,
                                    f"Mw={audit['fixed_magnitude_Mw']:.1f}, strike-slip\nReference Vs30=760 m/s",
                                    transform=axes["d"].transAxes, ha="right", va="top",
                                    fontsize=FONTS_PT["model_parameters"])
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            layout = {
                "page_mm": PAGE_MM, "reference_figure_mm": GRAPH_MM,
                "reference_figure_top_left_mm": GRAPH_TOP_LEFT_MM,
                "data_axes_bounds_in_A4": {k: list(ax.get_position().bounds) for k, ax in axes.items()},
                "axis_limits": {k: {"x": list(ax.get_xlim()), "y": list(ax.get_ylim())} for k, ax in axes.items()},
                "text": [dict(panel=k, text=t.get_text(), fontsize_pt=t.get_fontsize(),
                              bbox_bottom_left_pt=bbox_pt(t, renderer, fig))
                         for k, ax in axes.items() for t in [ax.xaxis.label, ax.yaxis.label, *ax.texts]],
                "upper_xlabel_to_lower_panel_clearance_pt": min(
                    bbox_pt(axes[k].xaxis.label, renderer, fig)[1] - axes[lower].bbox.y1 * 72 / fig.dpi
                    for k, lower in zip("ab", "cd")),
                "legend_parameter_overlap": bool(legend.get_window_extent(renderer).overlaps(note.get_window_extent(renderer))),
                "panel_ids_removed": True, "position_adjustments": [
                    {"panels": ["c", "d"], "element": "Urban building sites / Vs30 range",
                     "shift_mm": [1.1, 0], "reason": "5.5 pt text crossed the y-axis by approximately 0.7 mm"}],
                "typography_spacing_adjustments": [
                    {"panels": ["a", "b"], "element": "two-line x-axis title",
                     "linespacing_before": 1.2, "linespacing_after": 1.0,
                     "anchor_unchanged": True, "reason": "keep the 8 pt title clear of the lower panels"}],
            }
            pdf = output / "figure05_A4.pdf"
            fig.savefig(pdf, format="pdf", dpi=300, bbox_inches=None)
            fig.savefig(output / "figure05_A4.svg", format="svg", bbox_inches=None)
            plt.close(fig)
    finally:
        mathtext_engine.SHRINK_FACTOR = old_shrink
        MathTextParser._parse_cached.cache_clear()
    after = {str(p): digest(p)["sha256"] for p in protected_paths}
    changed = [v["path"] for v in before if v["sha256"] != after[v["path"]]]
    if changed:
        raise RuntimeError(f"Protected inputs changed: {changed}")
    report = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
              "pdf": digest(pdf), "font_family": "Arial", "font_weight": "bold",
              "font_sizes_pt": FONTS_PT, "layout": layout, "distance_panels": distance_info,
              "response_grid_rows": len(frame), "protected_inputs": before,
              "all_protected_inputs_unchanged": True, "code": digest(Path(__file__))}
    write_json(output / "build_report.json", report)
    print(json.dumps({"pdf": str(pdf), "all_protected_inputs_unchanged": True,
                      "clearance_pt": layout["upper_xlabel_to_lower_panel_clearance_pt"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build(parser.parse_args().output)
