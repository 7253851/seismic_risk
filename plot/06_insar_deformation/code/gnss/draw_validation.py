"""Project-style figures for the supplementary GNSS/PS matching experiment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-gnss-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.ticker import MaxNLocator
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[4]/"project/code"))
from paths import RESULT_ROOT, PLOT_OUTPUT_ROOT
from Validation.gnss_velocity import time_axis

GNSS = "#2D667E"
SCENE_COLORS = {"TSX1": "#B2182B", "TSX2": "#DE8531"}


def style() -> str:
    font = findfont(FontProperties(family="Arial", weight="bold"), fallback_to_default=False)
    plt.rcParams.update({
        "font.family": "Arial", "font.weight": "bold", "font.size": 12,
        "axes.labelweight": "bold", "axes.labelsize": 15, "axes.titlesize": 15,
        "axes.titleweight": "bold", "axes.linewidth": 1.25,
        "xtick.labelsize": 11, "ytick.labelsize": 11,
        "xtick.major.width": 1.2, "ytick.major.width": 1.2,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "pdf.fonttype": 42, "svg.fonttype": "none", "legend.frameon": False,
        "legend.fontsize": 10, "axes.unicode_minus": False})
    return font


def panel(ax, letter, title):
    ax.set_title(f"({letter})  {title}", loc="left", pad=12)
    ax.tick_params(direction="out", length=4)


def check_layout(fig) -> dict:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    for item in fig.findobj(Text):
        if item.get_visible() and item.get_text():
            box = item.get_window_extent(renderer)
            if box.x0 < -1 or box.y0 < -1 or box.x1 > fig.bbox.width+1 or box.y1 > fig.bbox.height+1:
                outside.append(item.get_text())
    if outside:
        raise ValueError(f"Labels outside figure: {outside}")
    return {"all_text_within_figure": True}


def save(fig, slug: str, output: Path, final: Path, dpi: int, preview_dpi: int = 140) -> dict:
    # Locators can create tick Text artists beyond view limits; remove those
    # unused ticks so the text-bound audit checks only rendered labels.
    for ax in fig.axes:
        for name in ("x", "y"):
            limits = getattr(ax, f"get_{name}lim")()
            low, high = sorted(limits)
            ticks = getattr(ax, f"get_{name}ticks")()
            getattr(ax, f"set_{name}ticks")(ticks[(ticks >= low) & (ticks <= high)])
            getattr(ax, f"set_{name}lim")(limits)
    audit = check_layout(fig)
    # Rasterize only PNG exports; PDF/SVG keep the plotted curves and labels vector.
    for suffix in ("pdf", "svg"):
        fig.savefig(output/f"{slug}.{suffix}")
        shutil.copy2(output/f"{slug}.{suffix}", final/f"{slug}.{suffix}")
    fig.savefig(output/f"{slug}_preview.png", dpi=preview_dpi)
    fig.savefig(final/f"{slug}_{dpi}dpi.png", dpi=dpi)
    record = {"name": slug, "size_inches": list(fig.get_size_inches()), "final_png_dpi": dpi, **audit}
    plt.close(fig)
    return record


def timeseries(ax, pairs, summary, color):
    dates = pd.DatetimeIndex(pairs.date)
    t = time_axis(dates)
    g, p = pairs.gnss_u_mm.to_numpy(), pairs.insar_u_mm.to_numpy()
    ax.plot(dates, g, "o-", color=GNSS, markersize=3.4, linewidth=1.35, label="GNSS U")
    ax.plot(dates, p, "s-", color=color, markersize=3.0, linewidth=1.2, label="PS U")
    for values, rate, c, label in ((g, summary.gnss_rate_mm_yr, GNSS, "GNSS fit"),
                                 (p, summary.top1_ps_rate_mm_yr, color, "PS fit")):
        ax.plot(dates, values.mean()+rate*(t-t.mean()), color=c, linestyle="--", linewidth=2, label=label)
    ax.set(xlabel="Acquisition date", ylabel="Vertical displacement (mm)")
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.margins(x=.02, y=.30)
    ax.legend(loc="upper left", ncol=2, columnspacing=1.1, handlelength=2)
    ax.text(.98, .035, f"GNSS: {summary.gnss_rate_mm_yr:.3f} mm/yr\n"
            f"PS: {summary.top1_ps_rate_mm_yr:.3f} mm/yr\n"
            f"PS {int(summary.top1_PS_ID)}  |  {summary.top1_distance_km:.2f} km",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=10,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 3})


def scatter(ax, pairs, summary, color):
    g, p = pairs.gnss_u_mm.to_numpy(), pairs.insar_u_mm.to_numpy()
    minimum, maximum = min(g.min(), p.min()), max(g.max(), p.max())
    padding = max((maximum-minimum)*.12, 1)
    limits = [minimum-padding, maximum+padding]
    ax.plot(limits, limits, color="#727272", linestyle="--", linewidth=1.4, label="1:1")
    fit = stats.linregress(g, p)
    ax.plot(limits, fit.intercept+fit.slope*np.array(limits), color=color, linewidth=1.7, label="OLS diagnostic")
    ax.scatter(g, p, s=30, facecolor=color, edgecolor="white", linewidth=.5, alpha=.9, zorder=3)
    ax.set(xlabel="GNSS vertical displacement (mm)", ylabel="InSAR vertical displacement (mm)",
           xlim=limits, ylim=limits, aspect="equal")
    ax.legend(loc="lower right")
    ax.text(.035, .965, f"n = {int(summary.n_epochs)} epochs\n"
            f"r = {summary.top1_pearson_r:.3f}\nRMSE = {summary.top1_rmse_mm:.2f} mm",
            transform=ax.transAxes, ha="left", va="top", fontsize=11,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85, "pad": 2})


def rate_points(ax, frame, summary, color):
    y = frame['rank'].to_numpy()
    ax.axvline(summary.gnss_rate_mm_yr, color=GNSS, linewidth=2, linestyle="--", label="GNSS fit")
    for _, row in frame.iterrows():
        ax.plot([row.v_vertical_stored, row.k_ps], [row['rank'], row['rank']], color="#C4C4C4", linewidth=1, zorder=1)
    ax.scatter(frame.k_ps, y, c=color, s=36, label="PS time-series fit", zorder=3)
    ax.scatter(frame.v_vertical_stored, y, edgecolor="#555555", facecolor="white", marker="s", s=30,
               label="Stored v / cos(inc)", zorder=2)
    ax.set(xlabel="Vertical rate (mm/yr)", ylabel="Selected PS rank", yticks=y,
           ylim=(len(frame)+.65, -.7))
    ax.legend(loc="upper left", ncol=3, bbox_to_anchor=(-.01, 1.025), fontsize=8.4,
              handlelength=1.8, columnspacing=1.0)
    ax.margins(x=.13)


def residuals(ax, frame, color):
    x = frame.rate_residual_mm_yr.to_numpy()
    # Display every selected point; violin spread is descriptive, not an uncertainty CI.
    if len(x)>2 and np.ptp(x)>1e-12:
        parts = ax.violinplot(x, positions=[1], widths=.65, showextrema=False)
        for body in parts["bodies"]:
            body.set_facecolor(color)
            body.set_edgecolor(color)
            body.set_alpha(.18)
    offsets = .15*np.sin(np.arange(len(x))*2.399963)
    ax.scatter(1+offsets, x, s=30, color=color, edgecolor="white", linewidth=.5, zorder=3)
    q1, median, q3 = np.percentile(x, [25, 50, 75])
    ax.plot([1, 1], [q1, q3], color="#333333", linewidth=5, zorder=4)
    ax.scatter([1], [median], c="white", edgecolors="#333333", s=32, zorder=5)
    ax.axhline(0, color="#777777", linewidth=1.2, linestyle="--")
    ax.set(xlim=(.35, 2.1), xticks=[], ylabel="PS - GNSS rate (mm/yr)")
    ax.ticklabel_format(axis="y", style="sci", scilimits=(-2, 3), useOffset=False)
    ax.margins(y=.3)
    ax.text(.98, .96, f"Selected PS: n = {len(x)}\nMean = {np.mean(x):+.5f}\n"
            f"RMSE = {np.sqrt(np.mean(x*x)):.5f}", transform=ax.transAxes,
            ha="right", va="top", fontsize=10)


def draw_tsx2_timeseries(results: Path, output: Path, final: Path, dpi: int = 600) -> dict:
    """Export the requested TSX2 panel with the 1286:552 reference aspect ratio."""
    if not 100 <= dpi <= 1200:
        raise ValueError("PNG dpi must be between 100 and 1200")
    output.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    font = style()
    summaries = pd.read_csv(results/"validation_summary.csv")
    selected = summaries.loc[summaries.scene.eq("TSX2")]
    if len(selected) != 1:
        raise ValueError("Expected exactly one TSX2 validation summary")
    summary = next(selected.itertuples())
    pairs = pd.read_csv(results/"TSX2_paired_timeseries.csv", parse_dates=["date"])
    pairs = pairs.loc[pairs['rank'].eq(1)].sort_values("date")
    if len(pairs) != summary.n_epochs or pairs.PS_ID.nunique() != 1 or int(pairs.PS_ID.iloc[0]) != int(summary.top1_PS_ID):
        raise ValueError("TSX2 paired data do not match the Top1 summary")
    # At 100 dpi the canvas is exactly the supplied 1286 x 552 pixel reference.
    fig, ax = plt.subplots(figsize=(12.86, 5.52))
    fig.subplots_adjust(left=.075, right=.985, bottom=.155, top=.95)
    ax.tick_params(direction="out", length=4)
    timeseries(ax, pairs, summary, SCENE_COLORS["TSX2"])
    slug = "gnss_tsx2_timeseries"
    figure = save(fig, slug, output, final, dpi, preview_dpi=100)
    exact_size_png = final/f"{slug}_1286x552.png"
    shutil.copy2(output/f"{slug}_preview.png", exact_size_png)
    metadata = {"selection": "TSX2 Top1 time series only", "reference_size_pixels": [1286, 552],
                "title": None, "panel_label": None,
                "aspect_ratio": 1286/552, "font_family": "Arial", "font_weight": "bold",
                "font_file": font, "results": str(results), "n_epochs": int(summary.n_epochs),
                "PS_ID": int(summary.top1_PS_ID), "figures": [figure],
                "exact_size_png": str(exact_size_png),
                "pairing": "Original acquisition dates and series; display size only"}
    (output/f"{slug}_metadata.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    return metadata


def draw_all(results: Path, output: Path, final: Path, dpi: int = 600) -> dict:
    if not 100 <= dpi <= 1200:
        raise ValueError("PNG dpi must be between 100 and 1200")
    output.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    font = style()
    summaries = pd.read_csv(results/"validation_summary.csv")
    if len(summaries) != 2:
        raise ValueError("The paper figure layout expects two TSX scenes")
    frames, paired = {}, {}
    for summary in summaries.itertuples():
        frames[summary.scene] = pd.read_csv(results/f"{summary.scene}_rate_validation.csv")
        pairs = pd.read_csv(results/f"{summary.scene}_paired_timeseries.csv", parse_dates=["date"])
        paired[summary.scene] = pairs.loc[pairs['rank'].eq(1)]
    figures = []
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 10.4))
    fig.subplots_adjust(left=.075, right=.985, bottom=.095, top=.95, wspace=.27, hspace=.43)
    for i, summary in enumerate(summaries.itertuples()):
        color = SCENE_COLORS[summary.scene]
        panel(axes[0, i], "ab"[i], f"{summary.scene}: selected Top1 time series")
        timeseries(axes[0, i], paired[summary.scene], summary, color)
        panel(axes[1, i], "cd"[i], f"{summary.scene}: same-date comparison")
        scatter(axes[1, i], paired[summary.scene], summary, color)
    fig.text(.5, .021, "KMIN  |  Trend-selected matches; descriptive consistency", ha="center", fontsize=11, color="#555555")
    figures.append(save(fig, "gnss_timeseries_scatter", output, final, dpi))

    fig, axes = plt.subplots(2, 2, figsize=(12.8, 9.7))
    fig.subplots_adjust(left=.085, right=.985, bottom=.09, top=.94, wspace=.29, hspace=.44)
    for i, summary in enumerate(summaries.itertuples()):
        color = SCENE_COLORS[summary.scene]
        panel(axes[0, i], "ab"[i], f"{summary.scene}: fitted and stored rates")
        rate_points(axes[0, i], frames[summary.scene], summary, color)
        panel(axes[1, i], "cd"[i], f"{summary.scene}: selected rate residuals")
        residuals(axes[1, i], frames[summary.scene], color)
    fig.text(.5, .021, "Top10 selected by rate agreement  |  Dots: individual matches; bar: IQR; white dot: median",
             ha="center", fontsize=10, color="#555555")
    figures.append(save(fig, "gnss_rate_validation", output, final, dpi))

    # Spatial separation matters when the existing algorithm searches a whole scene.
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.6))
    fig.subplots_adjust(left=.075, right=.985, bottom=.16, top=.88, wspace=.27)
    for i, summary in enumerate(summaries.itertuples()):
        ax, frame = axes[i], frames[summary.scene]
        color = SCENE_COLORS[summary.scene]
        panel(ax, "ab"[i], f"{summary.scene}: selected point locations")
        lon0, lat0 = frame.gnss_lon.iloc[0], frame.gnss_lat.iloc[0]
        transform = Transformer.from_crs("EPSG:4326", f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m", always_xy=True)
        east, north = transform.transform(frame.lon.to_numpy(), frame.lat.to_numpy())
        east, north = east/1000, north/1000
        ax.scatter(east, north, color=color, s=43, edgecolors="white", linewidth=.7, zorder=3, label="Selected Top10 PS")
        ax.scatter(0, 0, marker="*", color="#E22D32", s=220,
                   edgecolor="white", linewidth=1, zorder=5, label="KMIN GNSS")
        ax.scatter([east[0]], [north[0]], facecolors="none", edgecolors="#222222", s=110, linewidth=1.4, zorder=4, label="Top1")
        all_east, all_north = np.r_[east, 0], np.r_[north, 0]
        span = max(np.ptp(all_east), np.ptp(all_north), 1)*1.45
        center_east, center_north = (all_east.max()+all_east.min())/2, (all_north.max()+all_north.min())/2
        ax.set(xlabel="East of KMIN (km)", ylabel="North of KMIN (km)",
               xlim=(center_east-span/2, center_east+span/2),
               ylim=(center_north-span/2, center_north+span/2), aspect="equal")
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.legend(loc="upper left")
        ax.text(.98, .03, f"Distance: {summary.distance_min_km:.2f}-{summary.distance_max_km:.2f} km",
                transform=ax.transAxes, ha="right", fontsize=10)
    fig.text(.5, .025, "WGS84 local azimuthal equidistant projection centered on KMIN", ha="center", fontsize=10, color="#555555")
    figures.append(save(fig, "gnss_selected_point_locations", output, final, dpi))
    metadata = {"font_family": "Arial", "font_weight": "bold", "font_file": font,
                "gnss_color": GNSS, "scene_colors": SCENE_COLORS, "results": str(results),
                "pairing": "Original acquisition dates, ref0; no lag or fitted scaling applied",
                "selection": "Existing supplementary global Top10 trend match",
                "figures": figures}
    (output/"plot_metadata.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULT_ROOT/"validation/gnss_velocity/current")
    parser.add_argument("--output", type=Path, default=PLOT_OUTPUT_ROOT/"06_insar_deformation/output/gnss")
    parser.add_argument("--final", type=Path, default=PLOT_OUTPUT_ROOT/"06_insar_deformation/output/gnss/final")
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--all", action="store_true", help="Also generate the earlier three composite figures")
    args = parser.parse_args()
    draw_tsx2_timeseries(args.results, args.output, args.final, args.dpi)
    if args.all:
        draw_all(args.results, args.output, args.final, args.dpi)


if __name__ == "__main__":
    main()
