#!/usr/bin/env python3
"""Compose four labelled panels: map, ranking, pie and full-width histogram."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
import gc
import hashlib
import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic_risk_mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patheffects
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.font_manager import findfont, get_font
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = 300_000_000
WORKSPACE = Path(__file__).resolve().parents[3]
DATA = WORKSPACE / "plot/04_seismic_hazard/data"
WORK = WORKSPACE / "plot/04_seismic_hazard/output"
FINAL = WORKSPACE / "plot/04_seismic_hazard/output"
MAP = WORKSPACE / "plot/04_seismic_hazard/output/qgis/Kunming_Building_Hazard_1200dpi.png"
SOURCE_LAYOUT = WORKSPACE / "plot/04_seismic_hazard/data/map_crop_manifest.json"
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# Dimensions in inches; all panels share this physical layout at every DPI.
WIDTH = 12.12
OUTER = 0.10
MAP_WIDTH = 7.40
COLUMN_GAP = 0.24
TOP_Y = 0.12
ROW_GAP = 0.10
HISTOGRAM_HEIGHT = 3.80
LABEL_A_PT = 24
LABEL_OTHER_PT = 20
AXIS_PT = 20
TICK_PT = 16
STATISTICS_PT = 16
LINE_LEGEND_PT = 18
CLASS_PT = 14
THRESHOLD_PT = 18
FAULT_LABEL_PT = 14
PIE_LEGEND_PT = 14
PIE_PERCENT_PT = 20
FONT_AUDIT = {}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_csv(path):
    return pd.read_csv(path, encoding="utf-8-sig", float_precision="round_trip")


def set_style():
    plt.rcParams.update({
        "font.family": "Arial", "font.weight": "bold", "font.size": TICK_PT,
        "axes.labelsize": AXIS_PT, "axes.labelweight": "bold",
        "xtick.labelsize": TICK_PT, "ytick.labelsize": TICK_PT,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 1.15, "xtick.major.width": 1.15, "ytick.major.width": 1.15,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "savefig.bbox": None,
    })


def check_text(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    texts = [text for ax in fig.axes for text in ax.texts]
    for ax in fig.axes:
        if ax.axison:
            texts.extend([ax.xaxis.label, ax.yaxis.label, *ax.get_xticklabels(), *ax.get_yticklabels()])
    for ax in fig.axes:
        if ax.get_legend():
            texts.extend(ax.get_legend().get_texts())
    for text in texts:
        if not text.get_visible() or not text.get_text():
            continue
        font_path = findfont(text.get_fontproperties(), fallback_to_default=False)
        actual_font = get_font(font_path)
        assert actual_font.family_name == "Arial", (text.get_text(), actual_font.family_name)
        FONT_AUDIT[font_path] = {"family": actual_font.family_name, "style": actual_font.style_name}
        box = text.get_window_extent(renderer)
        assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= fig.bbox.width + 1 and box.y1 <= fig.bbox.height + 1, (text.get_text(), tuple(box.bounds), tuple(fig.bbox.bounds))
    return renderer


def map_frame_top(crop):
    """Find the long dark upper frame in the native map, below its coordinate labels."""
    width, height = crop[2]-crop[0], crop[3]-crop[1]
    with Image.open(MAP) as picture:
        band = np.asarray(picture.crop((crop[0]+int(width*0.05), crop[1],
                                        crop[2]-int(width*0.05), crop[1]+int(height*0.12))).convert("L"))
    rows = np.flatnonzero((band < 110).mean(axis=1) > 0.90)
    assert rows.size, "Could not identify the map's upper frame"
    return float(rows[0]) * MAP_WIDTH / width


def render_fault_panels(path, width, height, dpi, ranking, pie, aligned_top_in):
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([0.075, 0.39, 0.91, 0.59])
    values = ranking.Mean_Scenario_PGA_g.to_numpy(float)
    fraction = (values - values.min()) / np.ptp(values)
    bars = ax.barh(np.arange(len(values)), values, height=0.86,
            color=plt.get_cmap("YlOrRd")(0.20 + 0.65 * fraction), edgecolor="white", linewidth=0.7)
    display = {
        "Western branch of the Xiaojiang fault system (middle segment)": "Xiaojiang fault system\n(western middle branch)",
        "Eastern branch of the Xiaojiang fault system (middle segment)": "Xiaojiang fault system\n(eastern middle branch)",
        "Xiaojiang fault system (Southern segment)": "Xiaojiang fault system\n(southern segment)",
    }
    for y, name in enumerate(ranking.Fault_Name_Display):
        ax.text(values.max() * 0.015, y, display.get(name, name), fontsize=FAULT_LABEL_PT,
                ha="left", va="center", linespacing=0.92, color="#222222",
                path_effects=[patheffects.withStroke(linewidth=2.0, foreground="white")])
    # Align the first bar with the native map frame while keeping the lower axis fixed.
    lower_y = -0.6
    first_bar_top = len(values) - 1 + 0.86/2
    top_fraction = (height - aligned_top_in - 0.39*height) / (0.59*height)
    assert 0 < top_fraction < 1
    upper_y = lower_y + (first_bar_top - lower_y) / top_fraction
    ax.set(ylim=(lower_y, upper_y), xlim=(0, values.max() * 1.06),
           xlabel="Mean scenario PGA (g)")
    # Stop the y axis at the upper edge of the first bar, below the label space.
    ax.spines["left"].set_bounds(-0.6, len(values) - 1 + 0.86/2)
    ax.set_yticks([])
    ax.set_xticks([0, 0.10, 0.20], ["0.00", "0.10", "0.20"])
    ax.xaxis.labelpad = 9
    ax.tick_params(pad=5)
    pie_ax = fig.add_axes([0.0, 0.012, 0.45, 0.278])
    wedges, _ = pie_ax.pie(pie.Building_Count, colors=pie.Color_Hex,
                           startangle=90, counterclock=False,
                           wedgeprops={"edgecolor": "white", "linewidth": 1.5})
    for wedge, row in zip(wedges, pie.itertuples()):
        angle = np.deg2rad((wedge.theta1 + wedge.theta2) / 2)
        radius = 0.50 if row.Share_pct > 50 else 0.57
        text = pie_ax.text(radius * np.cos(angle), radius * np.sin(angle), f"{row.Share_pct:.1f}%",
                           ha="center", va="center", fontsize=PIE_PERCENT_PT,
                           color="white" if row.Share_pct > 50 else "#222222")
        if row.Share_pct < 50:
            text.set_path_effects([patheffects.withStroke(linewidth=1.2, foreground="white")])
    pie_ax.set(aspect="equal", xlim=(-1.05, 1.05), ylim=(-1.05, 1.05))
    legend_ax = fig.add_axes([0.465, 0.015, 0.52, 0.27])
    legend_ax.set_axis_off()
    legend_names = ["Puduhe fault", "Western branch of the\nXiaojiang fault system\n(middle segment)"]
    for index, row in enumerate(pie.itertuples()):
        y = [0.98, 0.64][index]
        legend_ax.add_patch(Rectangle((0, y - 0.045), 0.04, 0.045, facecolor=row.Color_Hex, edgecolor="none"))
        legend_ax.text(0.07, y, legend_names[index], va="top", ha="left", fontsize=PIE_LEGEND_PT, linespacing=1.0)
        count_y = [0.80, 0.28][index]
        legend_ax.text(0.07, count_y, f"{row.Building_Count:,} buildings", va="top", ha="left", fontsize=PIE_LEGEND_PT)
    renderer = check_text(fig)
    first_bar_box = bars[-1].get_window_extent(renderer)
    first_bar_top_in = height - first_bar_box.y1 / fig.dpi
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return {"first_bar_top_in": first_bar_top_in}


def render_d(path, width, height, dpi, bins, stats, classes):
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([0.09, 0.21, 0.895, 0.69])
    left = bins.Lower_PGA_g.to_numpy(float)
    right = bins.Upper_PGA_g.to_numpy(float)
    cmap = LinearSegmentedColormap.from_list("warm_pga", [
        (0.00, "#F7D889"), (0.18, "#F3B24B"), (0.35, "#EB8A36"),
        (0.55, "#E35B2D"), (1.00, "#B7252B")], N=512)
    norm = Normalize(vmin=left[0], vmax=right[-1])
    ax.bar(left, bins.Building_Count, width=right-left, align="edge",
           color=cmap(norm((left+right)/2)), edgecolor="white", linewidth=0.45, zorder=2)
    ax.set(xlim=(0.185, 0.485), ylim=(0, bins.Building_Count.max() * 1.13),
           xlabel="Final PGA (g)", ylabel="Building count")
    ax.set_xticks(np.arange(0.20, 0.46, 0.05))
    ax.set_yticks([0, 500, 1000, 1500])
    ax.xaxis.labelpad = 9
    ax.yaxis.labelpad = 10
    ax.tick_params(pad=6)
    thresholds = classes.upper_break.to_numpy(float)[:-1]
    for value in thresholds:
        ax.axvline(value, color="#777777", linestyle=(0, (3, 3)), linewidth=1.25, zorder=3)
        ax.text(value, 0.985, f"{value:.3f}", transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=THRESHOLD_PT, color="#444444", zorder=7,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})
    numeric = stats.set_index("Statistic").Value
    mean = ax.axvline(numeric["Mean"], color="#E76F51", linestyle="--", linewidth=2, label="Mean", zorder=4)
    median = ax.axvline(numeric["Median"], color="#264653", linestyle="-.", linewidth=2, label="Median", zorder=5)
    strip_edges = np.r_[ax.get_xlim()[0], thresholds, ax.get_xlim()[1]]
    for lo, hi, row in zip(strip_edges[:-1], strip_edges[1:], classes.itertuples()):
        ax.add_patch(Rectangle((lo, 1.025), hi-lo, 0.068, transform=ax.get_xaxis_transform(),
                               facecolor=row.Color_Hex, edgecolor="white", linewidth=1, clip_on=False))
        ax.text((lo+hi)/2, 1.059, row.PGA_Class, transform=ax.get_xaxis_transform(),
                ha="center", va="center", fontsize=CLASS_PT,
                color="white" if row.PGA_Class in ["High", "Very High"] else "#292929")
    statistic_texts = []
    for index, row in enumerate(stats.itertuples()):
        y = 0.92 - index * 0.085
        statistic_texts.extend([
            ax.text(0.745, y, row.Statistic, transform=ax.transAxes,
                    fontsize=STATISTICS_PT, fontweight="bold", ha="left", va="center"),
            ax.text(0.945, y, row.Figure_Label, transform=ax.transAxes,
                    fontsize=STATISTICS_PT, fontweight="bold", ha="right", va="center"),
        ])
    boundary = Line2D([], [], color="#777777", linestyle=(0, (3, 3)), linewidth=1.25, label="PGA class boundary")
    legend = ax.legend(handles=[mean, median, boundary], loc="upper left", bbox_to_anchor=(0.685, 0.36),
                       frameon=False, fontsize=LINE_LEGEND_PT, handlelength=1.8, handletextpad=0.4,
                       labelspacing=0.12, borderaxespad=0, borderpad=0)
    renderer = check_text(fig)
    statistics_bottom = min(text.get_window_extent(renderer).y0 for text in statistic_texts)
    legend_top = statistics_bottom - 6 * fig.dpi / 72
    legend.set_bbox_to_anchor((0.685, (legend_top - ax.bbox.y0) / ax.bbox.height))
    renderer = check_text(fig)
    assert legend.get_window_extent(renderer).y0 > ax.bbox.y0 + 2, "Histogram legend touches the axis baseline"
    for index, text in enumerate(statistic_texts):
        assert text.get_fontweight() == "bold" and text.get_fontsize() == STATISTICS_PT
        box = text.get_window_extent(renderer)
        assert not box.overlaps(legend.get_window_extent(renderer)), "Histogram statistics overlap legend"
        for other in statistic_texts[index+1:]:
            assert not box.overlaps(other.get_window_extent(renderer)), "Histogram statistics overlap each other"
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def main(dpi=1200, preview_only=False):
    if dpi < 100:
        raise ValueError("Use at least 100 DPI")
    WORK.mkdir(parents=True, exist_ok=True)
    source_metadata = json.loads(SOURCE_LAYOUT.read_text())
    data_metadata = json.loads((DATA / "manifest.json").read_text())
    for relative, entry in data_metadata["files"].items():
        assert sha256(DATA / relative) == entry["sha256"], relative
    assert sha256(MAP) == source_metadata["sources"][0]["sha256"], "Map differs from saved source; update its crop metadata first"
    ranking = read_csv(DATA / "b_fault_contributions/top10_fault_ranking.csv")
    pie = read_csv(DATA / "b_fault_contributions/dominant_fault_shares.csv")
    bins = read_csv(DATA / "c_pga_histogram/histogram_bins.csv")
    stats = read_csv(DATA / "c_pga_histogram/summary_statistics.csv")
    classes = read_csv(DATA / "c_pga_histogram/pga_class_breaks.csv")
    total = int(stats.set_index("Statistic").loc["Buildings", "Value"])
    assert total == int(bins.Building_Count.sum()) == int(pie.Building_Count.sum()) == int(classes.Building_Count.sum())
    crop = source_metadata["content_crops"]["a"]
    map_height = MAP_WIDTH * (crop[3]-crop[1]) / (crop[2]-crop[0])
    map_frame_top_in = map_frame_top(crop)
    right_x = OUTER + MAP_WIDTH + COLUMN_GAP
    right_width = WIDTH - right_x - OUTER
    d_y = TOP_Y + map_height + ROW_GAP
    full_height = d_y + HISTOGRAM_HEIGHT + OUTER
    set_style()
    print(f"Rendering panels at {dpi} dpi...", flush=True)
    bc_file, d_file = WORK / "bc_fault_panels.png", WORK / "d_histogram_panel.png"
    fault_geometry = render_fault_panels(bc_file, right_width, map_height, dpi, ranking, pie,
                                        aligned_top_in=map_frame_top_in)
    assert abs(fault_geometry["first_bar_top_in"] - map_frame_top_in) < 1e-6
    gc.collect()
    render_d(d_file, WIDTH-2*OUTER, HISTOGRAM_HEIGHT, dpi, bins, stats, classes)
    gc.collect()
    px = lambda value: round(value*dpi)
    canvas = Image.new("RGB", (px(WIDTH), px(full_height)), "white")
    with Image.open(MAP) as original:
        picture = original.crop(crop).convert("RGB")
    picture = picture.resize((px(MAP_WIDTH), px(map_height)), Image.Resampling.LANCZOS)
    canvas.paste(picture, (px(OUTER), px(TOP_Y)))
    del picture
    for path, x, y in [(bc_file, right_x, TOP_Y), (d_file, OUTER, d_y)]:
        with Image.open(path) as picture:
            canvas.paste(picture.convert("RGB"), (px(x), px(y)))
    draw = ImageDraw.Draw(canvas)
    label_sizes = {"a": LABEL_A_PT, **dict.fromkeys("bcd", LABEL_OTHER_PT)}
    fonts = {letter: ImageFont.truetype(FONT, round(size*dpi/72))
             for letter, size in label_sizes.items()}
    assert all(font.getname()[0] == "Arial" for font in fonts.values())
    # Right-align b/c within the white gutter, clear of the ranking's y axis.
    fault_axis_left = right_x + 0.075 * right_width
    gutter_right = px(fault_axis_left - 0.08)
    bc_width = max(draw.textbbox((0, 0), f"({letter})", font=fonts[letter], anchor="lt")[2]
                   for letter in "bc")
    bc_x = gutter_right - bc_width
    label_positions = {"a": (px(OUTER + 0.65), px(TOP_Y + 0.30)),
                       "b": (bc_x, px(TOP_Y + fault_geometry["first_bar_top_in"])),
                       "c": (bc_x, px(TOP_Y + map_height * 0.71 + 0.02)),
                       "d": (px(0.15), px(d_y + 0.15))}
    assert label_positions["b"][1] == px(TOP_Y + fault_geometry["first_bar_top_in"])
    assert label_positions["b"][0] == label_positions["c"][0]
    label_boxes = {letter: draw.textbbox(position, f"({letter})", font=fonts[letter], anchor="lt")
                   for letter, position in label_positions.items()}
    assert label_boxes["b"][0] >= px(OUTER + MAP_WIDTH + 0.02)
    assert label_boxes["b"][2] <= px(fault_axis_left - 0.06)
    histogram_axis_left = OUTER + 0.09 * (WIDTH - 2*OUTER)
    assert label_boxes["d"][2] < px(histogram_axis_left - 0.08)
    # The c label sits outside the circular pie, including its curved corner.
    pie_center_x = right_x + 0.225 * right_width
    pie_center_y = TOP_Y + (1 - 0.012 - 0.278/2) * map_height
    pie_radius = min(0.45 * right_width, 0.278 * map_height) / 2.1
    box = label_boxes["c"]
    nearest_x = np.clip(px(pie_center_x), box[0], box[2])
    nearest_y = np.clip(px(pie_center_y), box[1], box[3])
    assert np.hypot(nearest_x - px(pie_center_x), nearest_y - px(pie_center_y)) > px(pie_radius + 0.02)
    for letter, position in label_positions.items():
        # Draw glyphs directly: transparent label backgrounds, no masking boxes.
        draw.text(position, f"({letter})", font=fonts[letter], fill="#111111", anchor="lt")
    preview = canvas.copy()
    preview.thumbnail((1500, 1500), Image.Resampling.LANCZOS)
    preview.save(WORK / "preview.png", dpi=(150, 150))
    del preview
    output = None
    if not preview_only:
        FINAL.mkdir(parents=True, exist_ok=True)
        output = FINAL / "PGA_Combined_abcd_1200dpi.png"
        if dpi != 1200:
            raise ValueError("Final figure must be exported at 1200 DPI")
        print("Saving final 1200 dpi PNG...", flush=True)
        stage = FINAL / ".PGA_Combined_abcd_stage.png"
        canvas.save(stage, dpi=(dpi, dpi))
        stage.replace(output)
        # Retire only the immediately preceding version of this final figure.
        with Image.open(output) as verification:
            assert verification.size == canvas.size
            assert all(abs(value - 1200) < 1 for value in verification.info["dpi"])
            verification.verify()
        (FINAL / "PGA_Combined_abc_1200dpi.png").unlink(missing_ok=True)
        for obsolete in [WORK / "b_fault_panel.png", WORK / "c_histogram_panel.png"]:
            obsolete.unlink(missing_ok=True)
    metadata = {
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "layout": "(a) map upper left; (b) ranking upper right; (c) pie below ranking; (d) full-width histogram below",
        "final": str(output) if output else None, "dpi": dpi, "pixels": list(canvas.size),
        "data_directory": str(DATA), "map_source": str(MAP), "map_crop": crop,
        "data_total": total, "histogram_bins": len(bins), "ranking_bars": len(ranking),
        "label_positions_pixels": label_positions, "label_boxes_pixels": label_boxes,
        "label_font": "Arial Bold", "label_font_pt": label_sizes,
        "label_background": "transparent",
        "alignment": {"b_top_aligned_with_first_bar": True, "b_c_same_x": True,
                      "first_bar_aligned_with_map_upper_frame": True,
                      "labels_clear_of_chart_axes_and_pie": True,
                      "a_on_map_bcd_in_white_gutters": True},
        "first_ranking_bar_top_y_pixels": px(TOP_Y + fault_geometry["first_bar_top_in"]),
        "map_upper_frame_y_pixels": px(TOP_Y + map_frame_top_in),
        "font_sizes_pt": {"axis_labels": AXIS_PT, "ticks": TICK_PT, "statistics": STATISTICS_PT,
                          "line_legend": LINE_LEGEND_PT, "class_names": CLASS_PT, "thresholds": THRESHOLD_PT,
                          "ranking_labels": FAULT_LABEL_PT, "pie_legend": PIE_LEGEND_PT,
                          "pie_percentages": PIE_PERCENT_PT},
        "layout_inches": {"canvas_width": WIDTH, "map_width": MAP_WIDTH,
                          "map_height": map_height, "right_column_width": right_width,
                          "histogram_height": HISTOGRAM_HEIGHT},
        "map_size_change_from_previous": MAP_WIDTH / 6.95,
        "map_embedded_pixel_scale": px(MAP_WIDTH) / (crop[2] - crop[0]),
        "statistics_and_legend_overlap_check_passed": True,
        "statistics_font_family": "Arial", "statistics_font_weight": "bold",
        "statistics_layout": {"label_x_axes": 0.745, "value_x_axes": 0.945, "row_step_axes": 0.085},
        "rendered_font_files": FONT_AUDIT,
        "ranking_y_axis_stops_at_top_bar": True,
        "code_source": str(Path(__file__).resolve()),
        "png_integrity_verified": output is not None,
        "final_sha256": sha256(output) if output else None,
    }
    (WORK / ("preview_metadata.json" if preview_only else "layout_metadata.json")).write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+"\n")
    if not preview_only and (WORK / "font_audit.json").exists():
        audit = json.loads((WORK / "font_audit.json").read_text())
        audit.update(statistical_font_files=FONT_AUDIT, statistics_weight="bold",
                     statistics_size_pt=STATISTICS_PT, final_sha256=metadata["final_sha256"])
        (WORK / "font_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-only", action="store_true", help="Render a small working preview without updating the final")
    parser.add_argument("--a4", action="store_true", help="Build the editable A4 draft at manuscript size, without panel identifiers")
    parser.add_argument("--output", type=Path, help="A4 draft output directory; default plot/04_seismic_hazard/layout/work, restricted to that directory or workspace/drafts")
    args = parser.parse_args()
    if args.a4:
        if args.preview_only:
            parser.error('--a4 and --preview-only are separate workflows')
        import subprocess
        import sys
        command = [sys.executable, str(Path(__file__).with_name('build_a4_figure.py'))]
        if args.output:
            command.extend(['--output', str(args.output)])
        subprocess.run(command, check=True)
    else:
        if args.output:
            parser.error('--output requires --a4')
        main(dpi=150 if args.preview_only else 1200, preview_only=args.preview_only)
