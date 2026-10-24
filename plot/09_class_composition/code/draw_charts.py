#!/usr/bin/env python3
"""Draw four class-count bar charts in the recent statistical-figure style."""

from pathlib import Path
import gc
import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-four-indicators-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic-four-indicators-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.text import Text
from matplotlib.ticker import MaxNLocator, StrMethodFormatter
import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[3]
OUTPUT_DIR = WORKSPACE / "plot/09_class_composition/output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TABLE_DIR = WORKSPACE / "result/statistics/FourIndicators"
TABLE_DIR.mkdir(parents=True, exist_ok=True)
STATISTICS = WORKSPACE / "result/statistics"
NAMES_5 = ["Very Low", "Low", "Moderate", "High", "Very High"]
# Match the street-P90 composite; colors run from Very Low to Very High.
PANEL_PALETTES = {
    "Hazard": ["#FFF7BC", "#FEE391", "#FEC44F", "#FC4E2A", "#BD0026"],
    "Exposure": ["#EDF8F6", "#CCECE6", "#99D8C9", "#238B45", "#00441B"],
    "Vulnerability": ["#E8DFF2", "#BEA0D5", "#9360B5", "#63298C", "#2D004B"],
    "Risk": ["#FEE5D9", "#FCAE91", "#FB6A4A", "#DE2D26", "#A50F15"],
}
# Match the recent exposure distributions and vulnerability histograms.
AXIS_LABEL_PT = 24
TICK_LABEL_PT = 16
VALUE_LABEL_PT = 18
SAMPLE_LABEL_PT = 18
PANEL_LABEL_PT = 24
AXIS_LINEWIDTH_PT = 2.0
TICK_LINEWIDTH_PT = 1.6
BAR_EDGE_COLOR = "#8C8C8C"
BAR_EDGE_WIDTH_PT = 0.35
COMPOSITE_MM = (14.0 * 25.4, 8.4 * 25.4)
INDIVIDUAL_MM = (8.0 * 25.4, 5.5 * 25.4)
# Physical axes: 5.45 x 3.10 inches; 1.40-inch column and 1.08-inch row gaps.
COMPOSITE_AXES = tuple((left / 14.0, bottom / 8.4, 5.45 / 14.0, 3.10 / 8.4)
                      for bottom in (5.10, .92) for left in (1.40, 8.25))
PANELS = [
    {"slug": "pga", "module": "Hazard", "label": "PGA class", "class_col": "PGA_Class",
     "count_col": "Building_Count", "pct_col": "Percentage", "names": NAMES_5,
     "colors": PANEL_PALETTES["Hazard"], "expected_n": 57228},
    {"slug": "exposure", "module": "Exposure", "label": "Exposure class", "class_col": "exposure_class",
     "count_col": "building_count", "pct_col": "percentage",
     "names": NAMES_5,
     "colors": PANEL_PALETTES["Exposure"], "expected_n": 53513},
    {"slug": "vulnerability", "module": "Vulnerability", "label": "Vulnerability class",
     "class_col": "vulnerability_class", "count_col": "building_count", "pct_col": "percentage",
     "names": NAMES_5, "colors": PANEL_PALETTES["Vulnerability"], "expected_n": 41939},
    {"slug": "risk", "module": "Risk", "label": "Risk class", "class_col": "risk_class",
     "count_col": "building_count", "pct_col": "percentage", "names": NAMES_5,
     "colors": PANEL_PALETTES["Risk"], "expected_n": 40000},
]


def style() -> str:
    plt.rcParams.update({
        "font.family": "Arial", "font.weight": "bold", "font.size": TICK_LABEL_PT,
        "text.color": "black", "axes.labelcolor": "black", "axes.edgecolor": "black",
        "axes.labelsize": AXIS_LABEL_PT, "axes.labelweight": "bold",
        "xtick.labelsize": TICK_LABEL_PT, "ytick.labelsize": TICK_LABEL_PT,
        "xtick.color": "black", "ytick.color": "black",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": AXIS_LINEWIDTH_PT,
        "xtick.major.width": TICK_LINEWIDTH_PT, "ytick.major.width": TICK_LINEWIDTH_PT,
        "xtick.major.size": 5.0, "ytick.major.size": 5.0,
        "xtick.direction": "out", "ytick.direction": "out", "axes.axisbelow": True,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "savefig.bbox": None,
        "svg.fonttype": "none", "pdf.fonttype": 42,
    })
    return findfont(FontProperties(family="Arial", weight="bold"), fallback_to_default=False)


def load(panel: dict) -> pd.DataFrame:
    path = STATISTICS / panel["module"] / "analysis" / f"{panel['slug']}_class_statistics.csv"
    frame = pd.read_csv(path, float_precision="round_trip").set_index(panel["class_col"]).loc[panel["names"]]
    frame = frame[[panel["count_col"], panel["pct_col"]]].rename(
        columns={panel["count_col"]: "building_count", panel["pct_col"]: "percentage"})
    total = int(frame.building_count.sum())
    if total != panel["expected_n"] or not np.allclose(frame.percentage, frame.building_count / total * 100):
        raise ValueError(f"Counts or percentages differ: {panel['slug']}")
    return frame


def draw_panel(ax: plt.Axes, panel: dict, frame: pd.DataFrame, *, identifier: str | None = None) -> None:
    x = np.arange(len(frame))
    bars = ax.bar(x, frame.building_count, width=0.74, color=panel["colors"],
                  edgecolor=BAR_EDGE_COLOR, linewidth=BAR_EDGE_WIDTH_PT, zorder=3)
    for bar, (_, row) in zip(bars, frame.iterrows()):
        ax.annotate(f"{int(row.building_count):,}\n({row.percentage:.2f}%)",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 3.5), textcoords="offset points", ha="center", va="bottom",
                    fontsize=VALUE_LABEL_PT, fontfamily="Arial", fontweight="bold", color="black", linespacing=1.08)
    y_max = float(np.ceil(frame.building_count.max() * 1.45 / 1000) * 1000)
    ax.set(xlim=(-0.6, len(frame) - 0.4), ylim=(0, y_max),
           xlabel=panel["label"], ylabel="Building count")
    ax.set_xticks(x, panel["names"])
    ticks = MaxNLocator(nbins=6, integer=True).tick_values(0, y_max)
    # Clear the upper-left corner for an identifier beside the y-axis.
    tick_limit = .82 * y_max if identifier is not None else y_max
    ax.set_yticks(ticks[(ticks >= 0) & (ticks <= tick_limit)])
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.tick_params(pad=5)
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        label.set_fontfamily("Arial")
        label.set_fontweight("bold")
    ax.grid(False)
    ax.xaxis.labelpad = 9
    ax.yaxis.labelpad = 9
    ax.text(0.985, 0.965, f"N = {int(frame.building_count.sum()):,}",
            transform=ax.transAxes, ha="right", va="top", fontsize=SAMPLE_LABEL_PT,
            fontfamily="Arial", fontweight="bold", color="black")
    if identifier is not None:
        ax.annotate(identifier, xy=(0, 1), xycoords="axes fraction", xytext=(-8, 0),
                    textcoords="offset points", fontsize=PANEL_LABEL_PT,
                    ha="right", va="top", annotation_clip=False)


def export(fig: plt.Figure, name: str, preview_dpi: int = 150) -> None:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    text_boxes = []
    for text in fig.findobj(Text):
        if not text.get_visible() or not text.get_text():
            continue
        bounds = text.get_window_extent(renderer)
        if bounds.x0 < 0 or bounds.y0 < 0 or bounds.x1 > fig.bbox.width or bounds.y1 > fig.bbox.height:
            raise ValueError(f"Text outside figure: {text.get_text()}")
        if text.get_fontweight() not in ("bold", 700):
            raise ValueError(f"Text is not bold: {text.get_text()}")
        resolved = findfont(text.get_fontproperties(), fallback_to_default=False)
        if FontProperties(fname=resolved).get_name() != "Arial":
            raise ValueError(f"Text is not Arial: {text.get_text()}")
        text_boxes.append((text.get_text(), bounds))
    collisions = [(label_a, label_b) for i, (label_a, box_a) in enumerate(text_boxes)
                  for label_b, box_b in text_boxes[:i] if box_a.overlaps(box_b)]
    if collisions:
        raise ValueError(f"Overlapping chart text: {collisions[:5]}")
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUTPUT_DIR / f"{name}.{suffix}", dpi=600)
    fig.savefig(OUTPUT_DIR / f"{name}_preview.png", dpi=preview_dpi)
    plt.close(fig)


def main() -> None:
    font_path = style()
    frames = [load(panel) for panel in PANELS]
    for panel, frame in zip(PANELS, frames):
        fig, ax = plt.subplots(figsize=tuple(mm / 25.4 for mm in INDIVIDUAL_MM))
        fig.subplots_adjust(left=0.18, right=0.97, bottom=0.20, top=0.94)
        draw_panel(ax, panel, frame)
        export(fig, f"{panel['slug']}_class_counts")
        del fig, ax
        gc.collect()

    # Compact equal-size axes; identifiers sit beside each y-axis upper end.
    fig = plt.figure(figsize=tuple(mm / 25.4 for mm in COMPOSITE_MM))
    axes = [fig.add_axes(bounds) for bounds in COMPOSITE_AXES]
    for index, (ax, panel, frame) in enumerate(zip(axes, PANELS, frames)):
        draw_panel(ax, panel, frame, identifier=f"({chr(97 + index)})")
    export(fig, "four_indicator_class_counts_2x2", preview_dpi=150)

    records = []
    for panel, frame in zip(PANELS, frames):
        for class_name, row in frame.iterrows():
            records.append({"indicator": panel["slug"], "class": class_name,
                            "building_count": int(row.building_count), "percentage": row.percentage})
    pd.DataFrame(records).to_csv(TABLE_DIR / "class_counts_data.csv", index=False)
    metadata = {
        "layout": "2 x 2",
        "panel_order": [["PGA", "Exposure"], ["Vulnerability", "Risk"]],
        "chart_type": "Class-count bar charts with counts and percentages",
        "percentage_decimal_places": 2,
        "style": "Recent statistical figures: large bold Arial text, compact equal axes, identifiers beside y-axis upper ends, subtle gray bar outlines, no grid",
        "style_references": ["plot/diagnostics/exposure_distribution/code/draw_exposure_2x2.py",
                             "plot/diagnostics/vulnerability_histograms/code/draw_histograms.py"],
        "panel_identifiers": ["(a)", "(b)", "(c)", "(d)"],
        "panel_identifier_placement": {"anchor_axes_fraction": [0, 1], "offset_pt": [-8, 0],
                                       "alignment": "right/top; beside the y-axis upper end"},
        "panel_gaps_inches": {"columns": 1.40, "rows": 1.08},
        "title": None, "panel_titles": None, "legend_frame": False,
        "classification": "Shared deterministic five-class Jenks natural breaks; upper-inclusive intervals",
        "palette": {"name": "Indicator-specific sequential palettes matching the street-P90 composite",
                    "classes": NAMES_5, "colors_by_indicator": PANEL_PALETTES},
        "font_family": "Arial", "font_weight": "bold", "resolved_font_file": font_path,
        "font_sizes_pt": {"axis_labels": AXIS_LABEL_PT, "tick_labels": TICK_LABEL_PT,
                          "count_percentage": VALUE_LABEL_PT, "sample_size": SAMPLE_LABEL_PT,
                          "panel_labels": PANEL_LABEL_PT},
        "axis_linewidth_pt": AXIS_LINEWIDTH_PT, "tick_linewidth_pt": TICK_LINEWIDTH_PT,
        "grid": "None",
        "bar_edges": {"color": BAR_EDGE_COLOR, "linewidth_pt": BAR_EDGE_WIDTH_PT},
        "composite_axes_bounds": [list(bounds) for bounds in COMPOSITE_AXES],
        "y_tick_format": "Integer counts with thousands separators",
        "composite_mm": list(COMPOSITE_MM), "individual_mm": list(INDIVIDUAL_MM),
        "composite_inches": [mm / 25.4 for mm in COMPOSITE_MM],
        "individual_inches": [mm / 25.4 for mm in INDIVIDUAL_MM], "png_dpi": 600,
        "building_counts": {panel["slug"]: int(frame.building_count.sum())
                            for panel, frame in zip(PANELS, frames)},
        "validation": "Original counts and percentages match; all labels are bold Arial, within figure, and do not overlap.",
        "sources": [str(STATISTICS / panel["module"] / "analysis" /
                        f"{panel['slug']}_class_statistics.csv") for panel in PANELS],
    }
    (OUTPUT_DIR / "plot_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")



if __name__ == "__main__":
    main()
