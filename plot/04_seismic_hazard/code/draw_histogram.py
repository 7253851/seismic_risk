#!/usr/bin/env python3
"""Replot the building PGA histogram with a warm gradient at 1.73:1."""

from pathlib import Path
import json
import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[3]
OUTPUT_DIR = WORKSPACE / "plot/04_seismic_hazard/output/histogram"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SOURCE = WORKSPACE / "result/hazard/scs_pipeline/06_building_hazard.gpkg"
FIGSIZE = (12.12, 7.0)
CLASS_THRESHOLDS = pd.read_csv(WORKSPACE / "result/hazard/scs_pipeline/pga_class_breaks.csv", float_precision="round_trip").upper_break.to_numpy()[:-1]
CLASS_NAMES = ["Very Low", "Low", "Moderate", "High", "Very High"]
CLASS_COLORS = ["#FFF7BC", "#FEE391", "#FEC44F", "#FC4E2A", "#BD0026"]


def build_histogram(values: np.ndarray) -> tuple[plt.Figure, dict]:
    """Build the current histogram for standalone and pipeline exports."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not values.size:
        raise ValueError("No finite PGA values in the source.")

    plt.rcParams.update({
        "font.family": "Arial",
        "font.weight": "bold",
        "font.size": 18,
        "axes.labelsize": 24,
        "axes.labelweight": "bold",
        "xtick.labelsize": 18,
        "ytick.labelsize": 18,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 1.15,
        "xtick.major.width": 1.15,
        "ytick.major.width": 1.15,
        "xtick.major.size": 5,
        "ytick.major.size": 5,
        "savefig.facecolor": "white",
        "savefig.bbox": None,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })
    arial_path = findfont(FontProperties(family="Arial", weight="bold"), fallback_to_default=False)
    fig, ax = plt.subplots(figsize=FIGSIZE, facecolor="white")
    fig.subplots_adjust(left=0.115, right=0.985, bottom=0.15, top=0.915)

    counts, edges, bars = ax.hist(
        values, bins="fd", edgecolor="white", linewidth=0.45, zorder=2,
    )
    cmap = LinearSegmentedColormap.from_list(
        "warm_pga", [
            (0.00, "#F7D889"),
            (0.18, "#F3B24B"),
            (0.35, "#EB8A36"),
            (0.55, "#E35B2D"),
            (1.00, "#B7252B"),
        ], N=512,
    )
    norm = Normalize(vmin=edges[0], vmax=edges[-1])
    for bar, center in zip(bars, (edges[:-1] + edges[1:]) / 2):
        bar.set_facecolor(cmap(norm(center)))

    mean, median = float(values.mean()), float(np.median(values))
    std = float(values.std(ddof=1))
    for threshold in CLASS_THRESHOLDS:
        ax.axvline(threshold, color="#777777", linestyle=(0, (3, 3)),
                   linewidth=1.25, zorder=3)
        ax.text(threshold, 0.985, f"{threshold:.3f}",
                transform=ax.get_xaxis_transform(), ha="center", va="top",
                fontsize=20, color="#444444", zorder=7,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})
    mean_line = ax.axvline(mean, color="#E76F51", linestyle="--", linewidth=2.0,
                          label="Mean", zorder=4)
    median_line = ax.axvline(median, color="#264653", linestyle="-.", linewidth=2.0,
                            label="Median", zorder=5)
    ax.set(xlabel="Final PGA (g)",
           ylabel="Building count", xlim=(0.185, 0.485),
           ylim=(0, counts.max() * 1.13))
    ax.set_xticks(np.arange(0.20, 0.46, 0.05))
    ax.set_yticks(np.arange(0, counts.max() + 1, 250))
    ax.xaxis.labelpad = 10
    ax.yaxis.labelpad = 10
    ax.tick_params(pad=7)
    # Color strip and labels identify the five established PGA classes.
    class_edges = np.r_[ax.get_xlim()[0], CLASS_THRESHOLDS, ax.get_xlim()[1]]
    for left, right, name, color in zip(class_edges[:-1], class_edges[1:], CLASS_NAMES, CLASS_COLORS):
        ax.add_patch(Rectangle((left, 1.015), right - left, 0.05,
                               transform=ax.get_xaxis_transform(), facecolor=color,
                               edgecolor="white", linewidth=1, clip_on=False))
        ax.text((left + right) / 2, 1.04, name, transform=ax.get_xaxis_transform(),
                ha="center", va="center", fontsize=16,
                color="white" if name in ("High", "Very High") else "#292929")

    # Place all statistics in the empty upper-right part of the distribution.
    statistic_rows = [
        ("Buildings", f"{values.size:,}"),
        ("Mean", f"{mean:.4f} g"),
        ("Median", f"{median:.4f} g"),
        ("Minimum", f"{values.min():.4f} g"),
        ("Maximum", f"{values.max():.4f} g"),
        ("Std. dev.", f"{std:.4f} g"),
    ]
    for row, (label, value) in enumerate(statistic_rows):
        y = 0.880 - row * 0.075
        ax.text(0.675, y, label, transform=ax.transAxes, fontsize=24,
                ha="left", va="center", zorder=7)
        ax.text(0.980, y, value, transform=ax.transAxes, fontsize=24,
                ha="right", va="center", zorder=7)
    boundary_handle = Line2D([], [], color="#777777", linestyle=(0, (3, 3)),
                             linewidth=1.25, label="PGA class boundary")
    ax.legend(handles=[mean_line, median_line, boundary_handle],
              loc="upper left", bbox_to_anchor=(0.675, 0.435),
              frameon=False, fontsize=20, handlelength=1.8, labelspacing=0.35,
              borderaxespad=0, handletextpad=0.5)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    labels = [ax.xaxis.label, ax.yaxis.label, *ax.get_xticklabels(),
              *ax.get_yticklabels(), *ax.texts, *ax.get_legend().get_texts()]
    for label in labels:
        bounds = label.get_window_extent(renderer)
        if bounds.x0 < 0 or bounds.y0 < 0 or bounds.x1 > fig.bbox.width or bounds.y1 > fig.bbox.height:
            raise ValueError(f"Text exceeds figure bounds: {label.get_text()}")

    summary = {
        "source": str(SOURCE),
        "table": "building_hazard",
        "field": "PGA_Final_g",
        "valid_buildings": int(values.size),
        "mean_g": mean,
        "median_g": median,
        "standard_deviation_g": std,
        "standard_deviation_ddof": 1,
        "min_g": float(values.min()),
        "max_g": float(values.max()),
        "bin_rule": "Freedman-Diaconis (numpy bins='fd'), unchanged from original",
        "bin_count": len(counts),
        "histogram_total": int(counts.sum()),
        "figure_inches": FIGSIZE,
        "aspect_ratio": FIGSIZE[0] / FIGSIZE[1],
        "png_dpi": 600,
        "gradient": "left-to-right pale yellow, orange, red; color follows bin midpoint",
        "pga_class_thresholds_g": CLASS_THRESHOLDS.tolist(),
        "pga_class_names": CLASS_NAMES,
        "class_interval_rule": "Upper-inclusive five-class Jenks intervals; first class includes the minimum",
        "title": None,
        "font_family": "Arial",
        "resolved_font_file": arial_path,
        "font_sizes_pt": {
            "axis_labels": 24,
            "tick_labels": 18,
            "statistics_labels_and_values": 24,
            "line_legend": 20,
            "pga_class_names": 16,
            "pga_class_thresholds": 20,
        },
        "font_weight": "bold",
        "statistics_frame": False,
        "legend_frame": False,
    }
    return fig, summary


def main() -> None:
    with sqlite3.connect(f"{SOURCE.as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute('SELECT "PGA_Final_g" FROM "building_hazard"').fetchall()
    values = np.asarray([row[0] for row in rows], dtype=float)
    fig, summary = build_histogram(values)
    for suffix in ("png", "pdf", "svg"):
        fig.savefig(OUTPUT_DIR / f"pga_histogram_gradient.{suffix}", dpi=600)
    fig.savefig(OUTPUT_DIR / "preview.png", dpi=150)
    plt.close(fig)
    (OUTPUT_DIR / "plot_metadata.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
