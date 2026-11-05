"""Four-panel publication figure: map, histogram, 3D pie and GNSS time series."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-deformation-composite-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.patheffects as patheffects
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.font_manager import findfont, get_font
from matplotlib.patches import Patch, Rectangle
from matplotlib.text import Text
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"project/code"))
from Validation.gnss_velocity import time_axis

SOURCE_MAP = ROOT/"plot/06_insar_deformation/output/qgis/tsx_deformation/Kunming_TSX_Vertical_Deformation.pdf"
MAP_PROJECT = ROOT/"plot/06_insar_deformation/qgis/projects/06_insar_deformation.qgz"
RATE = ROOT/"result/statistics/Deformation"
GNSS = ROOT/"result/validation/gnss_velocity/current"
WORK = ROOT/"plot/06_insar_deformation/output"
FINAL = ROOT/"plot/06_insar_deformation/output"
PAPER = ROOT/"plot/06_insar_deformation/output/final/figure06.png"
SLUG = "InSAR_Deformation_GNSS_Combined_abcd"
WIDTH, HEIGHT = 180., 163.
MAP_LEFT, MAP_TOP, MAP_WIDTH = .3, -.5, 112.
MAP_ENLARGEMENT = MAP_WIDTH/100.5
HISTOGRAM_BOX = (124.5, 4.4, 52.5, 47.)
PIE_BOX = (116., 58.8, 61., 43.2)
MAP_LEGEND_BOX = (116., 108., 61., 8.5)
MAP_SCALE_BOX = (8., 105.5, 13., 6.3)
GRID_LEFT, GRID_RIGHT = 6.04, 177.
GNSS_BOX = (GRID_LEFT, 126.5, GRID_RIGHT-GRID_LEFT, 30.5)
COLORS = ["#B2182B", "#8AC65A", "#18558C"]
TIME_SERIES_COLORS = {"GNSS U": COLORS[2], "PS U": COLORS[0]}
STATISTICS_FONT_PT, STATISTICS_ROW_STEP = 7., .073
PIE_SMALL_PERCENT_PT, PIE_MAIN_PERCENT_PT, PIE_LEGEND_FONT_PT = 8., 12., 6.8
PIE_MAIN_PERCENT_COLOR = "#1B4D24"
GNSS_Y_LABEL_FONT_PT = 7.
NODES = [(-18, "#B2182B"), (-12, "#E34A33"), (-6, "#ECD6A8"),
         (-3, "#C8E6AE"), (0, "#8AC65A"), (3, "#C5E4B5"),
         (6, "#92C7DC"), (12, "#4C91BF"), (18, "#18558C")]


def fingerprint(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b""):
            h.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def axes_mm(fig, left, top, width, height):
    return fig.add_axes([left/WIDTH, 1-(top+height)/HEIGHT, width/WIDTH, height/HEIGHT])


def text_mm(fig, left, top, text, size=8., **kwargs):
    return fig.text(left/WIDTH, 1-top/HEIGHT, text, fontsize=size, **kwargs)


def map_details(fig):
    # Native place/fault labels remain the source QGIS vectors. Only the colourbar
    # is redrawn here; the map legend is placed outside the map in the right column.
    def map_x(value):
        return MAP_LEFT+(value-.3)*MAP_ENLARGEMENT
    def map_y(value):
        return MAP_TOP+(value-1.5)*MAP_ENLARGEMENT
    fig.add_artist(Rectangle((map_x(0)/WIDTH, 1-map_y(114.1)/HEIGHT), 101.2*MAP_ENLARGEMENT/WIDTH, 10.*MAP_ENLARGEMENT/HEIGHT,
                             transform=fig.transFigure, facecolor="white", edgecolor="none", zorder=-1))
    bar = axes_mm(fig, map_x(7.2), map_y(105.), 88.5*MAP_ENLARGEMENT, 1.7*MAP_ENLARGEMENT)
    bar.set(xlim=(-18, 18), ylim=(0, 1))
    bar.set_axis_off()
    cmap = LinearSegmentedColormap.from_list("source_deformation", [((v+18)/36, c) for v, c in NODES], N=512)
    breaks = np.linspace(-18, 18, 361)
    for left, right in zip(breaks[:-1], breaks[1:]):
        bar.add_patch(Rectangle((left, 0), right-left, 1, facecolor=cmap((left+right+36)/72), edgecolor="none"))
    bar.add_patch(Rectangle((-18, 0), 36, 1, facecolor="none", edgecolor="#444444", linewidth=.35))
    for value, _ in NODES:
        tick_x = 7.2+(value+18)/36*88.5
        text_mm(fig, map_x(tick_x), map_y(107.7), f"{value:g}", size=6.8, ha="center", va="center")
    text_mm(fig, map_x(51.45), map_y(110.2), "Vertical deformation rate (mm/y)", size=8., ha="center", va="center")


def prepare_map():
    script = Path(__file__).with_name("export_deformation_map.py")
    map_pdf = WORK/"map_without_legend.pdf"
    record_file = WORK/"map_export_manifest.json"
    record = json.loads(record_file.read_text()) if record_file.exists() else {}
    sources = {str(path): fingerprint(path)["sha256"] for path in [SOURCE_MAP, MAP_PROJECT]}
    if (record.get("source_hashes") != sources or record.get("script_sha256") != fingerprint(script)["sha256"]
            or not map_pdf.exists() or record.get("output_sha256") != fingerprint(map_pdf)["sha256"]):
        subprocess.run([str(ROOT/"plot/shared/qgis/scripts/run_pyqgis.sh"), str(script)], check=True)
        record = json.loads(record_file.read_text())
    probe = subprocess.run([sys.executable, "-c",
                            "import json,sys; from pypdf import PdfReader; "
                            "p=PdfReader(sys.argv[1]).pages[0]; "
                            "print(json.dumps([float(p.mediabox.width)*25.4/72,float(p.mediabox.height)*25.4/72]))",
                            str(map_pdf)], check=True, capture_output=True, text=True)
    record["pdf_page_mm"] = json.loads(probe.stdout)
    return map_pdf, record


def map_legend(fig):
    ax = axes_mm(fig, *MAP_LEGEND_BOX)
    ax.set(xlim=(0, MAP_LEGEND_BOX[2]), ylim=(MAP_LEGEND_BOX[3], 0))
    ax.set_axis_off()
    for x, y, label in [(6.5, 2., "Earthquakes"), (6.5, 6.2, "GNSS station"),
                         (40., 2., "Faults"), (40., 6.2, "Left-lateral")]:
        ax.text(x, y, label, fontsize=7., ha="left", va="center")
    ax.scatter([2.8], [2.], marker="^", s=27, color="#E22D32", edgecolor="white", linewidth=.4)
    ax.scatter([2.8], [6.2], marker="*", s=40, color="#E22D32", edgecolor="white", linewidth=.4)
    ax.plot([34.3, 38.3], [2., 2.], color="#A54E3D", linewidth=.7)
    ax.annotate("", xy=(34.3, 6.2), xytext=(38.3, 6.2),
                arrowprops={"arrowstyle": "->", "color": "#A54E3D", "lw": .65, "mutation_scale": 5})
    return {"box_mm": MAP_LEGEND_BOX}


def map_scale(fig, map_export):
    ax = axes_mm(fig, *MAP_SCALE_BOX)
    ax.set(xlim=(0, MAP_SCALE_BOX[2]), ylim=(MAP_SCALE_BOX[3], 0))
    ax.set_axis_off()
    # Match the ruler's physical length to the source map's projected extent and
    # the exact PDF page width used by the compositor, irrespective of placement.
    state = map_export["main_map"]
    extent_width_km = (state["extent"][2]-state["extent"][0])/1000
    bar_length = state["size_mm"][0]*MAP_WIDTH/map_export["pdf_page_mm"][0]*2/extent_width_km
    line_halo = [patheffects.withStroke(linewidth=2., foreground="white")]
    text_halo = [patheffects.withStroke(linewidth=1.1, foreground="white")]
    ax.plot([1.5, 1.5+bar_length], [4.5, 4.5], color="#222222", linewidth=1., path_effects=line_halo)
    for x in [1.5, 1.5+bar_length]:
        ax.plot([x, x], [3.9, 5.1], color="#222222", linewidth=.6, path_effects=line_halo)
    ax.text(1.5, 2., "0", fontsize=6.7, ha="center", va="center", path_effects=text_halo)
    ax.text(1.5+bar_length, 2., "2 km", fontsize=6.7, ha="center", va="center", path_effects=text_halo)
    return {"box_mm": MAP_SCALE_BOX, "position": "inside map, lower left",
            "scale_bar_length_mm": bar_length, "scale_bar_distance_km": 2.}


def histogram(fig, summary, table):
    ax = axes_mm(fig, *HISTOGRAM_BOX)
    fields = ["below_minus_4_5", "minus_4_5_to_plus_4_5_inclusive", "above_plus_4_5"]
    bottom = np.zeros(len(table))
    for field, color in zip(fields, COLORS):
        values = table[field].to_numpy()
        ax.bar(table.lower_mm_yr, values, width=table.upper_mm_yr-table.lower_mm_yr,
               bottom=bottom, align="edge", color=color, edgecolor="white", linewidth=.18)
        bottom += values
    ax.set(xlim=(-18, 18), ylim=(0, bottom.max()*1.17),
           xlabel="Vertical rate (mm/y)", ylabel="PS count (×10³)")
    ax.yaxis.set_label_coords(-.13, .5)
    ax.set_xticks([-18, -12, -6, 0, 6, 12, 18])
    ax.set_yticks([0, 200000, 400000, 600000])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, pos: f"{value/1000:.0f}"))
    ax.axvline(0, color="#555555", linestyle="--", linewidth=.55)
    for threshold in [-4.5, 4.5]:
        ax.axvline(threshold, color="#888888", linestyle=(0, (3, 3)), linewidth=.5)
        ax.text(threshold, .98, f"{threshold:+g}", transform=ax.get_xaxis_transform(),
                va="top", ha="center", fontsize=7., bbox={"facecolor": "white", "edgecolor": "none", "pad": .5})
    for i, (label, value) in enumerate([
        ("N", f"{summary['valid_rate_points']:,}"), ("Min.", f"{summary['min']:.2f}"),
        ("Max.", f"{summary['max']:.2f}"), ("Mean", f"{summary['mean']:.2f}"),
        ("Median", f"{summary['median']:.2f}"), ("SD", f"{summary['std_ddof0']:.2f}"),
    ]):
        y = .90-i*STATISTICS_ROW_STEP
        ax.text(.70, y, label, transform=ax.transAxes, fontsize=STATISTICS_FONT_PT,
                fontweight="normal", ha="left", va="top")
        ax.text(.98, y, value, transform=ax.transAxes, fontsize=STATISTICS_FONT_PT,
                fontweight="normal", ha="right", va="top")


def pie(fig, summary):
    spec = importlib.util.spec_from_file_location("deformation_pie_source", ROOT/"plot/06_insar_deformation/code/draw_statistics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ax = axes_mm(fig, *PIE_BOX)
    angles, flatten = module.draw_extruded_pie(ax, summary["class_counts"])
    ax.set(xlim=(-1.28, 1.28), ylim=(-.88, .96), aspect="equal")
    ax.set_axis_off()
    ax.text(0, -.08, f"{summary['class_percentages'][1]:.2f}%", fontsize=PIE_MAIN_PERCENT_PT,
            color=PIE_MAIN_PERCENT_COLOR, ha="center", va="center", zorder=7)
    for index, place in [(0, (-.60, .81)), (2, (.60, .81))]:
        angle = np.deg2rad((angles[index]+angles[index+1])/2)
        ax.annotate(f"{summary['class_percentages'][index]:.2f}%", xy=(np.cos(angle)*.99, flatten*np.sin(angle)*.99),
                    xytext=place, ha="center", va="center", color=COLORS[index], fontsize=PIE_SMALL_PERCENT_PT, zorder=8,
                    arrowprops={"arrowstyle": "-", "color": COLORS[index], "lw": .65,
                                "connectionstyle": "angle,angleA=0,angleB=90,rad=0"})
    handles = [Patch(facecolor=color, edgecolor="none", label=label) for color, label in zip(COLORS, ["v < -4.5", "-4.5 ≤ v ≤ 4.5", "v > 4.5"])]
    fig.legend(handles=handles, prop={"family": "Arial", "weight": "normal", "size": PIE_LEGEND_FONT_PT},
               loc="upper center", ncol=3,
               bbox_to_anchor=(146.5/WIDTH, 1-(PIE_BOX[1]+PIE_BOX[3]+.6)/HEIGHT), frameon=False,
               handlelength=.8, handletextpad=.35, columnspacing=.65, borderaxespad=0)


def gnss_panel(fig):
    summary = pd.read_csv(GNSS/"validation_summary.csv").set_index("scene").loc["TSX2"]
    pairs = pd.read_csv(GNSS/"TSX2_paired_timeseries.csv", parse_dates=["date"])
    pairs = pairs.loc[pairs['rank'].eq(1)].sort_values("date")
    dates = pd.DatetimeIndex(pairs.date)
    if len(pairs) != int(summary.n_epochs) or int(pairs.PS_ID.iloc[0]) != int(summary.top1_PS_ID):
        raise ValueError("GNSS paired series do not match the selected Top1 record")
    t = time_axis(dates)
    ax = axes_mm(fig, *GNSS_BOX)
    for values, rate, color, marker, label in [
        (pairs.gnss_u_mm.to_numpy(), summary.gnss_rate_mm_yr, TIME_SERIES_COLORS["GNSS U"], "o", "GNSS U"),
        (pairs.insar_u_mm.to_numpy(), summary.top1_ps_rate_mm_yr, TIME_SERIES_COLORS["PS U"], "s", "PS U"),
    ]:
        ax.plot(dates, values, color=color, marker=marker, markersize=1.8, linewidth=.65, label=label)
        ax.plot(dates, values.mean()+rate*(t-t.mean()), color=color, linestyle="--", linewidth=.95,
                label="GNSS fit" if label == "GNSS U" else "PS fit")
    ax.set(xlabel="", ylabel="", ylim=(-24, 38))
    ax.text(0, 1.035, "Vertical displacement (mm)", transform=ax.transAxes,
            fontsize=GNSS_Y_LABEL_FONT_PT, fontweight="normal", ha="left", va="bottom")
    ax.margins(x=.02)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.set_yticks([-20, 0, 20])
    ax.tick_params(axis="y", pad=2.)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend([handles[i] for i in [0, 2, 1, 3]], [labels[i] for i in [0, 2, 1, 3]],
              loc="upper left", bbox_to_anchor=(0., 1.), ncol=4, fontsize=7.8,
              handlelength=2, columnspacing=1.3, borderaxespad=.35, frameon=False)
    ax.text(.99, .06, f"GNSS: {summary.gnss_rate_mm_yr:.3f}; PS: {summary.top1_ps_rate_mm_yr:.3f} mm/y\n"
            f"{summary.top1_distance_km:.2f} km from KMIN",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.6, linespacing=1.1)


def audit_fonts(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fonts = {}
    for text in fig.findobj(Text):
        if not text.get_visible() or not text.get_text():
            continue
        path = findfont(text.get_fontproperties(), fallback_to_default=False)
        font = get_font(path)
        if font.family_name != "Arial":
            raise ValueError(f"Non-Arial text: {text.get_text()}")
        fonts[path] = {"family": font.family_name, "style": font.style_name}
        bounds = text.get_window_extent(renderer)
        if bounds.x0 < -1 or bounds.y0 < -1 or bounds.x1 > fig.bbox.width+1 or bounds.y1 > fig.bbox.height+1:
            raise ValueError(f"Text outside figure: {text.get_text()}")
    return fonts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Copy the final 1200 dpi PNG to manuscript figure6.png")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    FINAL.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((RATE/"run_manifest.json").read_text())
    summary = manifest["summary"]
    table = pd.read_csv(RATE/"deformation_rate_histogram.csv")
    classes = pd.read_csv(RATE/"deformation_rate_classes.csv")
    if table.ps_count.sum() != summary["valid_rate_points"] or classes.ps_count.sum() != summary["valid_rate_points"]:
        raise ValueError("Statistical tables disagree with the rate summary")
    map_pdf, map_export = prepare_map()
    plt.rcParams.update({"font.family": "Arial", "font.weight": "bold", "font.size": 8.,
                         "axes.labelsize": 8.8, "axes.labelweight": "bold", "axes.linewidth": .7,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "xtick.labelsize": 7.8, "ytick.labelsize": 7.8,
                         "xtick.major.width": .65, "ytick.major.width": .65,
                         "xtick.major.size": 2.4, "ytick.major.size": 2.4,
                         "axes.labelpad": 3., "pdf.fonttype": 42, "svg.fonttype": "none",
                         "axes.unicode_minus": False, "figure.facecolor": "none"})
    fig = plt.figure(figsize=(WIDTH/25.4, HEIGHT/25.4))
    map_details(fig)
    legend_placement = map_legend(fig)
    scale_placement = map_scale(fig, map_export)
    histogram(fig, summary, table)
    pie(fig, summary)
    gnss_panel(fig)
    fonts = audit_fonts(fig)
    overlay = WORK/"vector_overlay.pdf"
    fig.savefig(overlay, transparent=True)
    plt.close(fig)
    destination = FINAL/f"{SLUG}.pdf"
    merge = subprocess.run([sys.executable, str(Path(__file__).with_name("merge_deformation_pdf.py")),
                            "--map", str(map_pdf), "--overlay", str(overlay), "--output", str(destination),
                            "--width-mm", str(WIDTH), "--height-mm", str(HEIGHT),
                            "--map-width-mm", str(MAP_WIDTH), "--map-left-mm", str(MAP_LEFT),
                            "--map-top-mm", str(MAP_TOP)], check=True, capture_output=True, text=True)
    map_placement = json.loads(merge.stdout)
    renderer = (shutil.which("pdftoppm") or "pdftoppm")
    subprocess.run([renderer, "-png", "-singlefile", "-r", "230", str(destination), str(WORK/"preview")], check=True)
    if not args.preview_only:
        subprocess.run([renderer, "-png", "-singlefile", "-r", "1200", str(destination), str(FINAL/f"{SLUG}_1200dpi")], check=True)
        if args.publish:
            import shutil
            shutil.copy2(FINAL/f"{SLUG}_1200dpi.png", PAPER)
    records = [fingerprint(path) for path in [SOURCE_MAP, MAP_PROJECT, map_pdf, RATE/"run_manifest.json", RATE/"deformation_rate_histogram.csv",
                                              RATE/"deformation_rate_classes.csv", GNSS/"TSX2_paired_timeseries.csv",
                                              GNSS/"validation_summary.csv"]]
    output = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
              "layout": "dominant map upper left; histogram and 3D pie on right; full-width GNSS at bottom; no panel labels",
              "panel_content": {"a": "vertical-rate map", "b": "PS-rate histogram", "c": "PS-rate class shares", "d": "GNSS comparison"},
              "map_placement": map_placement, "map_area_increase_percent": (MAP_ENLARGEMENT**2-1)*100,
              "map_legend_placement": legend_placement, "map_export": map_export,
              "map_scale_placement": scale_placement,
              "alignment_grid_mm": {"left": GRID_LEFT, "right": GRID_RIGHT,
                                     "right_column_left": PIE_BOX[0], "right_column_center": PIE_BOX[0]+PIE_BOX[2]/2},
              "panel_labels": None,
              "height_reduction_from_178_mm_percent": (1-HEIGHT/178.)*100,
              "panel_boxes_mm": {"b": HISTOGRAM_BOX, "c": PIE_BOX, "d": GNSS_BOX},
              "largest_panel": "a",
              "page_mm": [WIDTH, HEIGHT], "map_source_unchanged": True, "source_records": records,
              "font_audit": fonts, "font_sizes_pt": {"axis_labels": 8.8, "ticks": 7.8,
              "histogram_statistics": STATISTICS_FONT_PT,
              "pie_percentages": [PIE_SMALL_PERCENT_PT, PIE_MAIN_PERCENT_PT],
              "pie_legend": PIE_LEGEND_FONT_PT,
              "gnss_y_label": GNSS_Y_LABEL_FONT_PT,
              "map_legend": 7., "map_colourbar_ticks": 6.8, "map_colourbar_label": 8.},
              "statistics": summary, "gnss_source": "Original TSX2 Top1, same-date raw GNSS U, ref0",
              "gnss_series_colors": TIME_SERIES_COLORS,
              "gnss_ps_id_displayed": False,
              "gnss_axis_labels": {"x_title": None, "date_ticks_visible": True,
                                   "y_title": "Vertical displacement (mm)", "y_title_position": "horizontal above y axis"},
              "pie_main_percentage_color": PIE_MAIN_PERCENT_COLOR,
              "annotation_layout": {"statistics_font_weight": "normal", "statistics_row_pitch_mm": HISTOGRAM_BOX[3]*STATISTICS_ROW_STEP,
                                    "pie_callouts_xy": [[-.60, .81], [.60, .81]],
                                    "pie_legend_font_weight": "normal", "pie_legend_gap_mm": .6},
              "pdf": fingerprint(destination), "preview": str(WORK/"preview.png"),
              "published_to_manuscript": bool(args.publish and not args.preview_only)}
    (WORK/"layout_manifest.json").write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"pdf": str(destination), "preview": str(WORK/"preview.png"), "published": output["published_to_manuscript"]}, indent=2))


if __name__ == "__main__":
    main()
