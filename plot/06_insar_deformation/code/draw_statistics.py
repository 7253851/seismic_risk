"""Histogram and pie chart of the current merged PS vertical-rate field."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-deformation-matplotlib")
import matplotlib
matplotlib.use("Agg")
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch, Wedge, Polygon, Ellipse
from matplotlib.text import Text
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import Affine2D
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/"project/code"))
from paths import DATA_ROOT, RESULT_ROOT, PLOT_OUTPUT_ROOT, WORKSPACE_ROOT

SOURCE = DATA_ROOT/"TSX_PS/tsx_merged.csv"
TABLES = RESULT_ROOT/"statistics/Deformation"
WORK = PLOT_OUTPUT_ROOT/"06_insar_deformation/output/statistics"
FINAL = WORK
LOW, HIGH = -4.5, 4.5
COLORS = ["#B2182B", "#8AC65A", "#18558C"]
LABELS = ["v < -4.5", "-4.5 ≤ v ≤ 4.5", "v > 4.5"]
SLUG = "deformation_rate_histogram_pie"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def read_data(path):
    arrays, total, source_counts = [], 0, {}
    for chunk in pd.read_csv(path, usecols=["v_vertical", "source"], chunksize=500000):
        total += len(chunk)
        values = pd.to_numeric(chunk.v_vertical, errors="coerce").to_numpy(float)
        arrays.append(values[np.isfinite(values)])
        for source, count in chunk.source.value_counts(dropna=False).items():
            key = str(source)
            source_counts[key] = source_counts.get(key, 0)+int(count)
    values = np.concatenate(arrays) if arrays else np.array([], float)
    if not len(values):
        raise ValueError("No finite vertical-rate observations")
    return values, total, source_counts


def summarize(values, total, source_counts, width):
    masks = [values < LOW, (values >= LOW) & (values <= HIGH), values > HIGH]
    counts = np.array([int(mask.sum()) for mask in masks])
    # Use symmetric limits that contain all observations; align the threshold
    # boundaries with equal-width bins where possible. No tail clipping.
    extent = max(18., np.ceil(np.max(np.abs(values))/width)*width)
    edges = np.arange(-extent, extent+width*.5, width)
    class_histograms = np.array([np.histogram(values[mask], bins=edges)[0] for mask in masks])
    full_counts = np.histogram(values, bins=edges)[0]
    if counts.sum() != len(values) or full_counts.sum() != len(values):
        raise AssertionError("Rate classes or histogram failed to preserve the point count")
    if not np.array_equal(class_histograms.sum(axis=0), full_counts):
        raise AssertionError("Class-wise histogram does not reproduce the full histogram")
    q1, median, q3 = np.percentile(values, [25, 50, 75])
    summary = {"total_input_rows": total, "valid_rate_points": int(len(values)),
               "excluded_nonfinite_rows": total-len(values), "source_counts": source_counts,
               "field": "v_vertical", "unit_label": "mm/yr", "rate_recalculated": False,
               "min": float(values.min()), "max": float(values.max()), "mean": float(values.mean()),
               "std_ddof0": float(values.std()), "p25": float(q1), "median": float(median), "p75": float(q3),
               "class_thresholds": [LOW, HIGH], "middle_interval_includes_endpoints": True,
               "class_counts": counts.tolist(), "class_percentages": (counts/len(values)*100).tolist(),
               "histogram_bin_width_mm_yr": width, "histogram_limits": [float(edges[0]), float(edges[-1])],
               "histogram_point_count": int(full_counts.sum()), "tails_clipped": False,
               "interpretation": "Fractions of current merged PS records, not land-area fractions; no additional filtering or deduplication"}
    return summary, edges, class_histograms


def style():
    font = findfont(FontProperties(family="Arial", weight="bold"), fallback_to_default=False)
    plt.rcParams.update({"font.family": "Arial", "font.weight": "bold", "font.size": 15,
                         "axes.labelsize": 18, "axes.labelweight": "bold", "axes.linewidth": 1.3,
                         "xtick.labelsize": 14, "ytick.labelsize": 14,
                         "xtick.major.width": 1.2, "ytick.major.width": 1.2,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "axes.facecolor": "white",
                         "savefig.facecolor": "white", "pdf.fonttype": 42,
                         "svg.fonttype": "none", "axes.unicode_minus": False,
                         "legend.frameon": False})
    return font


def draw_extruded_pie(ax, counts, flatten=.66, depth=.18):
    """Vector, parallel-projected pie with exact count-proportional angles."""
    counts = np.asarray(counts, dtype=float)
    angles = np.r_[90., 90.+np.cumsum(counts/counts.sum()*360.)]
    angles[-1] = 450.
    top_transform = Affine2D().scale(1, flatten)+ax.transData
    base_transform = Affine2D().scale(1, flatten).translate(0, -depth)+ax.transData
    ax.add_patch(Ellipse((0, -depth-.025), 2.035, 2*flatten,
                         facecolor="black", edgecolor="none", alpha=.065, zorder=.5))
    for left, right, color in zip(angles[:-1], angles[1:], COLORS):
        rgb = np.asarray(to_rgb(color))
        ax.add_patch(Wedge((0, 0), 1, left, right, transform=base_transform,
                           facecolor=rgb*.56, edgecolor="none", zorder=1))
        # Only the outer half facing the viewer exposes the extrusion wall.
        for turn in range(int(np.floor(left/360))-1, int(np.ceil(right/360))+1):
            first, last = max(left, 180.+turn*360), min(right, 360.+turn*360)
            if last <= first:
                continue
            samples = np.linspace(first, last, int(np.ceil((last-first)/1.5))+1)
            for a, b in zip(samples[:-1], samples[1:]):
                radians = np.deg2rad([a, b])
                x, y = np.cos(radians), flatten*np.sin(radians)
                shade = .66+.13*np.cos(np.deg2rad((a+b)/2-245))
                face = rgb*shade
                ax.add_patch(Polygon([(x[0], y[0]), (x[1], y[1]),
                                      (x[1], y[1]-depth), (x[0], y[0]-depth)],
                                     closed=True, facecolor=face, edgecolor=face,
                                     linewidth=.15, antialiased=False, zorder=2))
    for left, right, color in zip(angles[:-1], angles[1:], COLORS):
        ax.add_patch(Wedge((0, 0), 1, left, right, transform=top_transform,
                           facecolor=color, edgecolor="white", linewidth=1.35, zorder=4))
    return angles, flatten


def build_figure(summary, edges, histograms):
    fig = plt.figure(figsize=(12.86, 5.52))
    ax = fig.add_axes([.078, .17, .575, .785])
    pie_ax = fig.add_axes([.655, .28, .34, .67])
    bottom = np.zeros(len(edges)-1, float)
    for values, color in zip(histograms, COLORS):
        ax.bar(edges[:-1], values, width=np.diff(edges), align="edge", bottom=bottom,
               color=color, edgecolor="white", linewidth=.35, zorder=2)
        bottom += values
    ax.axvline(0, color="#333333", linewidth=1.2, linestyle="--", zorder=3)
    for threshold in [LOW, HIGH]:
        ax.axvline(threshold, color="#686868", linewidth=1.1, linestyle=(0, (3, 3)), zorder=3)
        ax.text(threshold, .985, f"{threshold:+g}", transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=14, color="#555555",
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1})
    ax.set(xlabel="Vertical deformation rate (mm/yr)", ylabel="PS point count (×10³)",
           xlim=(edges[0], edges[-1]), ylim=(0, bottom.max()*1.19))
    ax.set_xticks(np.arange(edges[0], edges[-1]+.01, 6))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, pos: f"{value/1000:,.0f}"))
    ax.tick_params(direction="out", length=4)
    ax.text(.95, .915, "Rate statistics (mm/yr)", transform=ax.transAxes,
            ha="right", va="top", fontsize=15)
    statistic_rows = [
        ("N", f"{summary['valid_rate_points']:,}"),
        ("Min.", f"{summary['min']:.2f}"),
        ("Max.", f"{summary['max']:.2f}"),
        ("Mean", f"{summary['mean']:.2f}"),
        ("Median", f"{summary['median']:.2f}"),
        ("Std. dev.", f"{summary['std_ddof0']:.2f}"),
    ]
    for index, (label, value) in enumerate(statistic_rows):
        y = .84-index*.066
        ax.text(.70, y, label, transform=ax.transAxes, ha="left", va="top", fontsize=16)
        ax.text(.95, y, value, transform=ax.transAxes, ha="right", va="top", fontsize=16)

    angles, flatten = draw_extruded_pie(pie_ax, summary["class_counts"])
    percentages = summary["class_percentages"]
    pie_ax.text(0, -.08, f"{percentages[1]:.2f}%", ha="center", va="center", fontsize=30, zorder=6)
    for index, xytext in [(0, (-.78, .96)), (2, (.78, .96))]:
        angle = np.deg2rad((angles[index]+angles[index+1])/2)
        xy = (np.cos(angle)*.99, flatten*np.sin(angle)*.99)
        pie_ax.annotate(f"{percentages[index]:.2f}%", xy=xy, xytext=xytext,
                        ha="center", va="center", fontsize=17, color=COLORS[index], zorder=7,
                        arrowprops={"arrowstyle": "-", "color": COLORS[index], "linewidth": 1.2,
                                    "connectionstyle": "angle,angleA=0,angleB=90,rad=0"})
    pie_ax.set(xlim=(-1.23, 1.23), ylim=(-.95, 1.10), aspect="equal")
    pie_ax.set_axis_off()
    handles = [Patch(facecolor=c, edgecolor="none", label=label) for c, label in zip(COLORS, LABELS)]
    pie_ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, -.015),
                  fontsize=14, handlelength=1.05, handleheight=.9, labelspacing=.35, borderaxespad=.2)
    return fig


def export(fig, final, work, dpi):
    # Remove unused locator labels beyond the displayed axes limits before QA.
    ax = fig.axes[0]
    ymin, ymax = ax.get_ylim()
    ticks = ax.get_yticks()
    ax.set_yticks(ticks[(ticks >= ymin) & (ticks <= ymax)])
    ax.set_ylim(ymin, ymax)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for text in fig.findobj(Text):
        if text.get_visible() and text.get_text():
            bounds = text.get_window_extent(renderer)
            if bounds.x0 < -1 or bounds.y0 < -1 or bounds.x1 > fig.bbox.width+1 or bounds.y1 > fig.bbox.height+1:
                raise ValueError(f"Text outside canvas: {text.get_text()}")
    for suffix in ["pdf", "svg"]:
        path = work/f"{SLUG}.{suffix}"
        fig.savefig(path)
        if path.resolve() != (final/path.name).resolve():
            shutil.copy2(path, final/path.name)
    fig.savefig(work/f"{SLUG}_preview.png", dpi=100)
    shutil.copy2(work/f"{SLUG}_preview.png", final/f"{SLUG}_1286x552.png")
    fig.savefig(final/f"{SLUG}_{dpi}dpi.png", dpi=dpi)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--tables", type=Path, default=TABLES)
    parser.add_argument("--output", type=Path, default=WORK)
    parser.add_argument("--final", type=Path, default=FINAL)
    parser.add_argument("--bin-width", type=float, default=.5)
    parser.add_argument("--dpi", type=int, default=1200)
    args = parser.parse_args()
    if not np.isfinite(args.bin_width) or args.bin_width <= 0 or not 100 <= args.dpi <= 1200:
        raise ValueError("Expected positive finite bin width and 100–1200 dpi")
    for path in [args.tables, args.output, args.final]:
        path.mkdir(parents=True, exist_ok=True)
    before = args.input.stat()
    values, total, source_counts = read_data(args.input)
    summary, edges, histograms = summarize(values, total, source_counts, args.bin_width)
    pd.DataFrame({"rate_interval_mm_yr": LABELS, "color": COLORS,
                  "ps_count": summary["class_counts"], "percentage": summary["class_percentages"]}).to_csv(
        args.tables/"deformation_rate_classes.csv", index=False)
    pd.DataFrame({"lower_mm_yr": edges[:-1], "upper_mm_yr": edges[1:],
                  "ps_count": histograms.sum(axis=0), "below_minus_4_5": histograms[0],
                  "minus_4_5_to_plus_4_5_inclusive": histograms[1], "above_plus_4_5": histograms[2]}).to_csv(
        args.tables/"deformation_rate_histogram.csv", index=False)
    pd.DataFrame([{
        "valid_ps_count": summary["valid_rate_points"], "unit": "mm/yr",
        "minimum": summary["min"], "maximum": summary["max"], "mean": summary["mean"],
        "median": summary["median"], "std_population_ddof0": summary["std_ddof0"],
        "p25": summary["p25"], "p75": summary["p75"],
    }]).to_csv(args.tables/"deformation_rate_summary.csv", index=False)
    font = style()
    export(build_figure(summary, edges, histograms), args.final, args.output, args.dpi)
    after = args.input.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("Source input changed during plotting")
    metadata = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                "source": {"path": str(args.input.resolve()), "bytes": before.st_size,
                           "mtime_ns": before.st_mtime_ns, "sha256": sha256(args.input)},
                "code_sha256": sha256(__file__), "summary": summary,
                "map_classification_source": str(WORKSPACE_ROOT/"plot/shared/qgis/scripts/build_tsx_deformation_layout.py"),
                "figure": {"size_inches": [12.86, 5.52], "size_reference_pixels": [1286, 552],
                           "font": "Arial Bold", "font_file": font, "colors": COLORS,
                           "title": None, "panel_labels": None, "layout": "compact histogram and pie",
                           "pie_style": "3D extrusion, parallel projection; vector top and shaded front wall",
                           "pie_vertical_scale": .66, "pie_extrusion_depth": .18,
                           "pie_angle_basis": "class point counts / total point count; no exploded sectors",
                           "statistics_row_step_axes": .066, "statistics_column_positions_axes": [.70, .95],
                           "font_sizes_pt": {"axis_labels": 18, "ticks": 14, "statistics": 16,
                                             "small_percentages": 17, "main_percentage": 30, "legend": 14},
                           "visible_statistics": ["N", "min", "max", "mean", "median", "std_ddof0"],
                           "final_png_dpi": args.dpi, "all_text_inside_canvas": True}}
    encoded = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    (args.tables/"run_manifest.json").write_text(encoded, encoding="utf-8")
    (args.output/"plot_metadata.json").write_text(encoded, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Figure exported: {args.final/SLUG}")


if __name__ == "__main__":
    main()
