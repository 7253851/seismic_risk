#!/usr/bin/env python3
"""Compose the existing PGA-distance and fixed-GMPE results as a 2 x 2 figure."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "project/code"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plot/shared"))
from textwrap import fill
from zoneinfo import ZoneInfo

SCRIPT_ROOT = Path(__file__).resolve().parents[3] / "project/code"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from analysis.Hazard import site_effect_analysis as site
import matplotlib.pyplot as plt
import matplotlib.patheffects as effects
from matplotlib.colors import LogNorm
import numpy as np
import pandas as pd

LEGACY_ROOT = site.STATISTICS_ROOT / "Hazard/analysis"
QUANTILE_TABLE = LEGACY_ROOT / "pga_by_controlling_fault_distance_quantile_by_scenario.csv"
PANEL_INSET_PT = 18.0
FIGURE_STEM = "pga_distance_and_gmpe_site_response_abcd_2x2"
FIGURE_SIZE_IN = (18.2, 15.0)
PANEL_SIZE_IN = (7.6, 6.1)
COLUMN_GAP_IN = 1.4
ROW_GAP_IN = 1.3


def new_composition_directory(root: Path) -> Path:
    """Use one current composition; keep adopted paper images separate."""
    directory = root / "current"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def draw_aligned_panel_labels(fig, axes) -> dict:
    """Use equal point-based insets, independent of each panel's dimensions."""
    width, height = fig.get_size_inches()
    labels = []
    positions = {}
    for panel, ax in zip(("a", "b", "c", "d"), axes):
        bounds = ax.get_position()
        x = bounds.x0 + PANEL_INSET_PT / (72 * width)
        y = bounds.y1 - PANEL_INSET_PT / (72 * height)
        labels.append(fig.text(x, y, f"({panel})", fontsize=24, fontfamily="Arial", fontweight="bold",
                               color="black", ha="left", va="top", bbox=None, zorder=20))
        positions[panel] = {"x_figure": float(x), "y_figure": float(y)}
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    a, b, c, d = [label.get_window_extent(renderer) for label in labels]
    x_error = max(abs(a.x0 - c.x0), abs(b.x0 - d.x0))
    y_error = max(abs(a.y1 - b.y1), abs(c.y1 - d.y1))
    if x_error > 1e-6 or y_error > 1e-6:
        raise ValueError("Panel labels must align in both rows and columns")
    return {"positions": positions, "inset_pt": PANEL_INSET_PT,
            "column_left_alignment_error_px": float(x_error),
            "row_top_alignment_error_px": float(y_error), "label_background": "transparent"}


def measure_figure_layout(fig, axes, color_axes, response_legend, parameter_note) -> dict:
    """Record actual artist sizes and check the compact inter-panel clearances."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    top_left, top_right, bottom_left, bottom_right = axes
    gap_pt = (min(ax.xaxis.label.get_window_extent(renderer).y0 for ax in (top_left, top_right))
              - max(ax.bbox.y1 for ax in (bottom_left, bottom_right))) * 72 / fig.dpi
    if gap_pt < 4:
        raise ValueError(f"Upper x labels are too close to the lower panels: {gap_pt:.2f} pt")
    color_bounds = [ax.get_position().bounds for ax in color_axes]
    color_alignment_error = max(abs(color_bounds[0][i] - color_bounds[1][i]) for i in (1, 2, 3))
    if color_alignment_error > 1e-10:
        raise ValueError("Inset colorbars must share the same vertical position, width and height")
    for artist in (response_legend, parameter_note):
        bounds = artist.get_window_extent(renderer)
        for line in bottom_right.lines:
            if line.get_label().startswith("Rrup ="):
                points = line.get_transform().transform(line.get_xydata())
                if any(bounds.contains(x, y) for x, y in points):
                    raise ValueError("The response legend or parameter note overlaps an AF response curve")
    if response_legend.get_window_extent(renderer).overlaps(parameter_note.get_window_extent(renderer)):
        raise ValueError("The response legend overlaps the parameter note")
    return {
        "figure_size_in": list(FIGURE_SIZE_IN), "panel_size_in": list(PANEL_SIZE_IN),
        "column_gap_in": COLUMN_GAP_IN, "row_gap_in": ROW_GAP_IN,
        "upper_xlabel_to_lower_panel_clearance_pt": float(gap_pt),
        "inset_colorbars": {"parent_panels": ["a", "b"], "orientation": "horizontal",
                           "bounds_in_parent_axes": [0.10, 0.18, 0.48, 0.035],
                           "alignment_error_figure_units": float(color_alignment_error),
                           "shared_log_count_scale": True},
        "response_legend": {"parent_panel": "d", "location": "upper right", "columns": 1},
        "parameter_note": {"parent_panel": "d", "location": "below the legend in the upper-right blank area"},
        "response_annotation_curve_overlap": False,
        "font_sizes_pt": {
            "axis_labels": sorted({float(label.get_fontsize()) for ax in axes for label in (ax.xaxis.label, ax.yaxis.label)}),
            "colorbar_label": sorted({float(ax.xaxis.label.get_fontsize()) for ax in color_axes}),
            "axis_ticks": sorted({float(label.get_fontsize()) for ax in axes for label in (*ax.get_xticklabels(), *ax.get_yticklabels())}),
            "colorbar_ticks": sorted({float(label.get_fontsize()) for ax in color_axes for label in ax.get_xticklabels()}),
            "fault_legends": sorted({float(label.get_fontsize()) for ax in (top_left, top_right) for label in ax.get_legend().get_texts()}),
            "response_legend": sorted({float(label.get_fontsize()) for label in response_legend.get_texts()}),
            "urban_range_and_AF_notes": sorted({float(label.get_fontsize()) for ax in (bottom_left, bottom_right) for label in ax.texts if label.get_text() and label is not parameter_note}),
            "parameter_note": float(parameter_note.get_fontsize()),
            "panel_labels_and_parameter_note": sorted({float(label.get_fontsize()) for label in fig.texts}),
        },
    }


def find_latest_response_run() -> Path:
    candidates = []
    for path in site.DEFAULT_OUTPUT.glob("*/analysis_metadata.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if (metadata.get("status") == "complete" and metadata.get("analysis_mode") == "fixed-response"
                and metadata.get("fixed_magnitude_Mw") == site.FIXED_MAGNITUDE
                and metadata.get("Rrup_distances_km") == list(site.RESPONSE_DISTANCES_KM)
                and (path.parent / "urban_vs30_context.json").exists()):
            candidates.append((metadata["created_at"], path.parent))
    if not candidates:
        raise FileNotFoundError("Run the current fixed-response site analysis before composing the combined figure")
    return max(candidates)[1]


def draw_distance_panels(fig, axes, color_axes, buildings: pd.DataFrame, quantiles: pd.DataFrame) -> dict:
    """Split the original panel by controlling fault, preserving its quantile means.

    Use the same hexagon lattice and log-count scale in both panels. Axis limits
    follow each fault's observations so that both attenuation curves remain clear.
    """
    groups = list(buildings.groupby("Dom_Fault", sort=True))
    if len(groups) != 2 or sum(len(group) for _, group in groups) != len(buildings):
        raise ValueError("The 2 x 2 layout requires exactly two controlling-fault groups with no missing assignments")
    extent = (float(buildings.Horizontal_Distance_km.min()), float(buildings.Horizontal_Distance_km.max()),
              float(buildings.PGA_Final_g.min()), float(buildings.PGA_Final_g.max()))
    densities, panel_info = [], {}
    for index, (ax, (fault, group)) in enumerate(zip(axes, groups)):
        hb = ax.hexbin(group.Horizontal_Distance_km, group.PGA_Final_g,
                       gridsize=55, extent=extent, mincnt=1, cmap="YlOrRd")
        if not np.isclose(hb.get_array().sum(), len(group)):
            raise ValueError(f"Hexbin counts do not cover the full fault group: {fault}")
        densities.append(hb)
        name = site.display_name(fault)
        table = quantiles.loc[quantiles.Fault_Name_Display.eq(name)].sort_values("Bin")
        if table.empty or int(table.Building_Count.sum()) != len(group):
            raise ValueError(f"Existing distance-quantile table does not match the building inventory: {name}")
        color, linestyle, marker = site.STYLES[index % len(site.STYLES)]
        ax.plot(table.X_Median, table.Mean_PGA_g, color=color, linestyle=linestyle,
                marker=marker, markersize=4.5, linewidth=2.5, label=fill(name, width=30),
                zorder=3, path_effects=[effects.withStroke(linewidth=4., foreground="white")])
        xspan = float(group.Horizontal_Distance_km.max() - group.Horizontal_Distance_km.min())
        yspan = float(group.PGA_Final_g.max() - group.PGA_Final_g.min())
        ax.set(xlabel="Building-to-fault horizontal\ndistance (km)", ylabel="Final PGA (g)",
               xlim=(max(-0.5, group.Horizontal_Distance_km.min() - 0.04 * xspan),
                     group.Horizontal_Distance_km.max() + 0.04 * xspan),
               ylim=(group.PGA_Final_g.min() - 0.08 * yspan, group.PGA_Final_g.max() + 0.15 * yspan))
        ax.tick_params(axis="both", length=6, pad=7)
        ax.legend(frameon=False, loc="upper right", fontsize=19, handlelength=2.1)
        panel_info["ab"[index]] = {
            "fault": name, "building_count": len(group), "quantile_count": len(table),
            "hexbin_count_sum": int(hb.get_array().sum()),
            "x_limits_km": list(map(float, ax.get_xlim())), "y_limits_g": list(map(float, ax.get_ylim())),
        }
    vmax = max(float(hb.get_array().max()) for hb in densities)
    norm = LogNorm(vmin=1, vmax=max(2, vmax))
    for hb in densities:
        hb.set_norm(norm)
    for hb, color_ax in zip(densities, color_axes):
        fig.colorbar(hb, cax=color_ax, orientation="horizontal", label="Building count (log scale)")
    return {"fault_panels": panel_info, "common_hexbin_extent": list(extent),
            "hexbin_gridsize": 55, "shared_log_count_limits": [1, max(2, vmax)],
            "axis_limits": "Independent limits follow each fault's observations; tick labels show the scales"}


def combine(*, response_run: Path | None = None, output_root: Path | None = None, dpi: int = 300) -> dict:
    if dpi < 100:
        raise ValueError("Export DPI must be at least 100")
    response_run = Path(response_run or find_latest_response_run()).resolve()
    source_metadata = json.loads((response_run / "analysis_metadata.json").read_text(encoding="utf-8"))
    if (source_metadata.get("fixed_magnitude_Mw") != site.FIXED_MAGNITUDE
            or source_metadata.get("Rrup_distances_km") != list(site.RESPONSE_DISTANCES_KM)
            or not source_metadata.get("all_requested_inputs_in_range")):
        raise ValueError("Response source must match the current in-range Mw and Rrup configuration")
    audit = json.loads((response_run / "gmpe_response_audit.json").read_text(encoding="utf-8"))
    context = json.loads((response_run / "urban_vs30_context.json").read_text(encoding="utf-8"))
    input_path = Path(context["source"])
    protected = {input_path, QUANTILE_TABLE, Path(site.gmpe.__file__).resolve()}
    for root in (LEGACY_ROOT, site.DEFAULT_OUTPUT,
                 site.PLOT_OUTPUT_ROOT / "04_seismic_hazard/output/statistics",
                 site.PLOT_OUTPUT_ROOT / "05_distance_site_response/output/fixed_response"):
        protected.update(path for path in root.rglob("*") if path.is_file() and not path.name.startswith("."))
    destination_root = Path(output_root or site.PLOT_OUTPUT_ROOT / "05_distance_site_response/output").resolve()
    before = {str(path): site.fingerprint(path) for path in sorted(protected)}
    frame = pd.read_csv(response_run / "gmpe_fixed_response_grid.csv")
    expected_pga = site.gmpe.predict_pga(frame.Mw, frame.Rrup_Input_km, frame.Vs30_m_s)[0]
    expected_ref = site.gmpe.predict_pga(frame.Mw, frame.Rrup_Input_km, site.REFERENCE_VS30)[0]
    if not np.allclose(frame.PGA_g, expected_pga, rtol=1e-12, atol=1e-14) or not np.allclose(frame.AF_760, expected_pga / expected_ref, rtol=1e-12, atol=1e-14):
        raise ValueError("Stored response curves do not reproduce the current GMPE")
    buildings = site.read_buildings(input_path)
    buildings = buildings.loc[np.isfinite(buildings.PGA_Final_g)].copy()
    depth = float(audit["model_configuration"]["equivalent_depth_km"])
    buildings["Horizontal_Distance_km"] = np.sqrt(np.maximum(buildings.Dom_Rrup ** 2 - depth ** 2, 0.))
    quantiles = pd.read_csv(QUANTILE_TABLE)
    directory = new_composition_directory(destination_root)
    with plt.rc_context(site.STYLE):
        fig = plt.figure(figsize=FIGURE_SIZE_IN, facecolor="white")
        def rect(x, y, width, height):
            return [x / FIGURE_SIZE_IN[0], y / FIGURE_SIZE_IN[1],
                    width / FIGURE_SIZE_IN[0], height / FIGURE_SIZE_IN[1]]
        left_x, lower_y = 1.15, 0.90
        right_x = left_x + PANEL_SIZE_IN[0] + COLUMN_GAP_IN
        upper_y = lower_y + PANEL_SIZE_IN[1] + ROW_GAP_IN
        top_left = fig.add_axes(rect(left_x, upper_y, *PANEL_SIZE_IN))
        top_right = fig.add_axes(rect(right_x, upper_y, *PANEL_SIZE_IN))
        color_axes = [ax.inset_axes([0.10, 0.18, 0.48, 0.035]) for ax in (top_left, top_right)]
        left = fig.add_axes(rect(left_x, lower_y, *PANEL_SIZE_IN))
        right = fig.add_axes(rect(right_x, lower_y, *PANEL_SIZE_IN))
        distance_info = draw_distance_panels(fig, (top_left, top_right), color_axes, buildings, quantiles)
        handles = site.draw_fixed_gmpe_response((left, right), frame, urban_context=context,
                                               panel_labels=("", ""))
        alignment = draw_aligned_panel_labels(fig, (top_left, top_right, left, right))
        response_legend = right.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.97, 0.97),
                                      ncol=1, labelspacing=0.25, handlelength=2.2, borderpad=0,
                                      borderaxespad=0, frameon=False, fontsize=24)
        parameter_note = right.text(0.97, 0.65, f"Mw={audit['fixed_magnitude_Mw']:.1f}, strike-slip\nReference Vs30=760 m/s",
                                    transform=right.transAxes, ha="right", va="top", fontsize=24)
        layout_details = measure_figure_layout(fig, (top_left, top_right, left, right),
                                              color_axes, response_legend, parameter_note)
        paths = site.save_plot(fig, directory, FIGURE_STEM, dpi, transparent=False)
    # Keep the exact curve values with the composition for reproducibility.
    (directory / "gmpe_fixed_response_grid.csv").write_bytes((response_run / "gmpe_fixed_response_grid.csv").read_bytes())
    (directory / "fault_distance_quantile_curves.csv").write_bytes(QUANTILE_TABLE.read_bytes())
    changed = [name for name, old in before.items() if not Path(name).exists() or site.fingerprint(Path(name))["sha256"] != old["sha256"]]
    site.write_json(directory / "preservation_check.json", {
        "all_original_results_unchanged": not changed, "changed_existing_files": changed,
        "protected_file_count": len(before), "fingerprints": list(before.values()),
    })
    metadata = {
        "status": "complete" if not changed else "existing_files_changed_during_run",
        "run_directory": str(directory), "analysis_mode": "combined-abcd-2x2",
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "response_source_run": str(response_run), "building_input": before[str(input_path)],
        "distance_quantile_source": before[str(QUANTILE_TABLE)],
        "composition_code": site.fingerprint(Path(__file__).resolve()),
        "shared_response_renderer": site.fingerprint(Path(site.__file__).resolve()),
        "gmpe_code": before[str(Path(site.gmpe.__file__).resolve())],
        "building_count": len(buildings), "response_grid_rows": len(frame),
        "panels": {"a": f"{distance_info['fault_panels']['a']['fault']}: inventory PGA versus horizontal distance, log-count hexbin and existing quantile means",
                   "b": f"{distance_info['fault_panels']['b']['fault']}: inventory PGA versus horizontal distance, log-count hexbin and existing quantile means",
                   "c": "Direct GMPE Vs30–PGA at Mw=6.0 and Rrup=10,15,20,30 km",
                   "d": "Direct GMPE Vs30–AF, reference Vs30=760 m/s"},
        "distance_panel_details": distance_info,
        "urban_vs30_context": context, "style": {"layout": "Compact 2 x 2; aligned horizontal colorbars inside (a,b), response legend and parameters inside (d)",
            "font": "Arial Bold", "axis_and_colorbar_labels_pt": 24, "response_legend_pt": 24, "fault_legend_pt": 19,
            "panel_labels_pt": 24, "tick_labels_pt": 16, "context_note_pt": 16, "parameter_note_pt": 24,
            "background": "white", "panel_label_background": "transparent", "figure_title": None},
        "panel_label_alignment": alignment, "layout_details": layout_details,
        "figure_paths": paths, "dpi": dpi, "preservation_check_passed": not changed,
    }
    site.write_json(directory / "analysis_metadata.json", metadata)
    (directory / "figure_caption.txt").write_text(
        "Distance and site-response controls on PGA. (a,b) Final PGA versus building-to-fault horizontal distance for buildings controlled by the Puduhe and western Xiaojiang scenarios, respectively. "
        "Colour denotes building counts on a shared logarithmic scale; lines show the existing mean PGA within each fault's distance quantiles. Axis limits differ between the two fault panels. "
        "(c) GMPE-predicted PGA versus Vs30 and (d) amplification factor (AF), defined as the PGA ratio to the Vs30=760 m/s reference site at the same magnitude and distance. "
        "Curves in (c,d) use Mw=6.0, strike-slip conditions and Rrup=10,15,20,30 km. Gray shading marks the urban-site range of 190–350 m/s.\n",
        encoding="utf-8")
    if changed:
        raise RuntimeError(f"Pre-existing files changed during composition: {changed}")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-run", type=Path, help="Existing fixed-response result directory; default: latest matching run")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()
    result = combine(response_run=args.site_run, output_root=args.output_root, dpi=args.dpi)
    print(json.dumps({key: result[key] for key in ("run_directory", "figure_paths", "preservation_check_passed")}, indent=2))


if __name__ == "__main__":
    main()
