#!/usr/bin/env python3
"""Export a green exposure map; optional statistics recreate the earlier composite."""
from __future__ import annotations

from datetime import datetime
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zlib
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-risk-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic-risk-cache")
CODE = Path(__file__).resolve().parent
ROOT = next(parent for parent in CODE.parents if (parent / "project/code/paths.py").is_file())
sys.path.insert(0, str(ROOT / "project/code"))
from paths import PLOT_OUTPUT_ROOT, STATISTICS_ROOT

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex
import numpy as np
from PIL import Image

RUNTIME = Path("/Users/bin/.cache/codex-runtimes/codex-primary-runtime/dependencies")
PDF_PYTHON = RUNTIME / "python/bin/python3"
PDFTOPPM = RUNTIME / "bin/override/pdftoppm"
SHARED_SOURCE = ROOT / "plot/diagnostics/exposure_distribution/code/draw_exposure_2x2.py"
spec = importlib.util.spec_from_file_location("exposure_statistics", SHARED_SOURCE)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
WIDTH, HEIGHT = 17.2, 19.4
MAP_LEFT, MAP_BOTTOM, MAP_WIDTH = .20, .70, 16.8
MAP_HEIGHT = MAP_WIDTH * 211 / 195
STATS_LEFT, STATS_BOTTOM, STATS_WIDTH, STATS_HEIGHT = 16.80, .10, 10.85, 19.1
MAIN_TOP = MAP_BOTTOM + MAP_HEIGHT - MAP_WIDTH * 8.5 / 195
MAIN_BOTTOM = MAP_BOTTOM + MAP_WIDTH * 12.5 / 195
PANEL_HEIGHT = 3.18
PANEL_ID_TOP_PAD_PT = 2
ROW_GAP = (MAIN_TOP - MAIN_BOTTOM - 4 * PANEL_HEIGHT) / 3
ROW_BOTTOMS = [(MAIN_TOP - index * (PANEL_HEIGHT + ROW_GAP) - PANEL_HEIGHT - STATS_BOTTOM) / STATS_HEIGHT
               for index in range(4)]
AX_HEIGHT = PANEL_HEIGHT / STATS_HEIGHT
STEM = "exposure_map_only"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def run_command(command):
    subprocess.run([str(value) for value in command], check=True)


def labels_bcde(fig, axes):
    width, height = fig.get_size_inches()
    return [fig.text(ax.get_position().x0 - 8 / (72 * width), ax.get_position().y1 + PANEL_ID_TOP_PAD_PT / (72 * height),
                     f"({letter})", fontsize=24, ha="right", va="bottom", bbox=None)
            for letter, ax in zip("bcde", axes)]


def check_vertical_layout(fig, axes, identifiers, annotations):
    for axis in axes:
        axis.xaxis.labelpad = 6
        axis.tick_params(axis="x", pad=5)
    fig.canvas.draw(); renderer = fig.canvas.get_renderer()
    texts = [*identifiers, *annotations]
    for axis in fig.axes:
        texts.extend([axis.xaxis.label, axis.yaxis.label])
        for coordinate in (axis.xaxis, axis.yaxis):
            low, high = sorted(coordinate.get_view_interval())
            for tick in coordinate.get_major_ticks():
                if low - 1e-12 <= tick.get_loc() <= high + 1e-12:
                    texts.extend([tick.label1, tick.label2])
    texts = [text for text in texts if text.get_visible() and text.get_text()]
    boxes = [text.get_window_extent(renderer) for text in texts]
    for text, box in zip(texts, boxes):
        if box.x0 < -.2 or box.y0 < -.2 or box.x1 > fig.bbox.width + .2 or box.y1 > fig.bbox.height + .2:
            raise ValueError("Clipped text: " + text.get_text())
    for index, (text, box) in enumerate(zip(texts, boxes)):
        for other, other_box in zip(texts[index + 1:], boxes[index + 1:]):
            if box.overlaps(other_box):
                raise ValueError(f"Overlapping text: {text.get_text()} / {other.get_text()}")
    right_edges = [text.get_window_extent(renderer).x1 for text in identifiers]
    assert max(right_edges) - min(right_edges) < 1e-6
    return {"text_inside_canvas": True, "no_text_overlap": True, "panel_ids_in_one_aligned_column": True,
            "main_axes_same_size": all(np.allclose(axis.get_position().bounds[2:], axes[0].get_position().bounds[2:]) for axis in axes)}


def merge_svg(config):
    work = Path(config["work_directory"])
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}svg", {"width": f"{WIDTH}in", "height": f"{HEIGHT}in",
                                        "viewBox": f"0 0 {WIDTH * 72} {HEIGHT * 72}"})
    ET.SubElement(root, f"{{{ns}}}rect", {"width": "100%", "height": "100%", "fill": "white"})
    items = [("building_exposure_BuGn.svg", "map_", MAP_LEFT, MAP_BOTTOM, MAP_WIDTH, MAP_HEIGHT)]
    if config["include_statistics"]:
        items.append(("statistical_panels_bcde.svg", "stats_", STATS_LEFT, STATS_BOTTOM, STATS_WIDTH, STATS_HEIGHT))
    items.append(("panel_a_and_sample_note.svg", "overlay_", 0, 0, WIDTH, HEIGHT))
    for filename, prefix, left, bottom, width, height in items:
        tree = ET.parse(work / filename)
        source = tree.getroot()
        identities = {item.get("id"): prefix + item.get("id") for item in source.iter() if item.get("id")}
        for item in source.iter():
            if item.get("id"):
                item.set("id", identities[item.get("id")])
            for key, value in list(item.attrib.items()):
                if key == "id":
                    continue
                for old, new in identities.items():
                    value = value.replace(f"url(#{old})", f"url(#{new})")
                    if value == f"#{old}":
                        value = f"#{new}"
                item.set(key, value)
        nested = ET.SubElement(root, f"{{{ns}}}svg", {"x": str(left * 72), "y": str((HEIGHT - bottom - height) * 72),
                                                    "width": str(width * 72), "height": str(height * 72),
                                                    "viewBox": source.get("viewBox"), "preserveAspectRatio": "none"})
        nested.extend(list(source))
    path = work / f"{STEM}.svg"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def png_chunk(handle, name, payload):
    handle.write(struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", zlib.crc32(name + payload) & 0xffffffff))


def render_streamed_png(pdf, output, work, dpi=1200):
    """Render strips with Poppler, keeping memory independent of the full canvas."""
    width, height = round(WIDTH * dpi), round(HEIGHT * dpi)
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Path(output).open("wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n")
            png_chunk(handle, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            pixels_per_metre = round(dpi / .0254)
            png_chunk(handle, b"pHYs", struct.pack(">IIB", pixels_per_metre, pixels_per_metre, 1))
            compressor = zlib.compressobj(level=6)
            for top in range(0, height, 1536):
                strip_height = min(1536, height - top)
                prefix = work / ".render_strip"
                run_command([PDFTOPPM, "-f", 1, "-l", 1, "-r", dpi, "-x", 0, "-y", top,
                             "-W", width, "-H", strip_height, "-singlefile", "-png", pdf, prefix])
                band = prefix.with_suffix(".png")
                with Image.open(band) as image:
                    assert image.size == (width, strip_height), image.size
                    rgb = image.convert("RGB")
                    pixels = rgb.tobytes()
                stride = width * 3
                for row in range(strip_height):
                    data = compressor.compress(b"\x00" + pixels[row * stride:(row + 1) * stride])
                    if data:
                        png_chunk(handle, b"IDAT", data)
                del pixels, rgb
                band.unlink()
                print(f"1200-dpi PNG: {min(top + strip_height, height)}/{height} rows", flush=True)
            png_chunk(handle, b"IDAT", compressor.flush())
            png_chunk(handle, b"IEND", b"")
        with Image.open(output) as image:
            assert image.size == (width, height)
            assert abs(image.info["dpi"][0] - dpi) < .1
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def run(include_statistics=False):
    global WIDTH, STEM
    WIDTH = 27.85 if include_statistics else 17.2
    STEM = "exposure_map_statistics_abcde" if include_statistics else "exposure_map_only"
    created = datetime.now(ZoneInfo("Asia/Shanghai"))
    run_id = created.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    work = PLOT_OUTPUT_ROOT / "diagnostics/exposure_maps/output" / run_id
    final = PLOT_OUTPUT_ROOT / "diagnostics/exposure_maps/output/final" / run_id
    numeric = STATISTICS_ROOT / "Exposure/map_distribution_composite" / run_id
    for directory in (work, final, numeric):
        directory.mkdir(parents=True, exist_ok=False)
    # Guard this figure's inputs. Other chats can independently rebuild or edit
    # manuscript files, so their state cannot be a plotting precondition.
    protected = {path for path in shared.protected_files() if "manuscript" not in path.parts}
    protected.add(ROOT / "plot/08_vulnerability_exposure/qgis/projects/08b_exposure.qgz")
    protected.add(ROOT / "plot/08_vulnerability_exposure/output/qgis/map_sources/Kunming_Building_Exposure_1200dpi.png")
    protected.add(SHARED_SOURCE)
    before = {str(path): shared.sha256(path) for path in sorted(protected)}
    write_json(numeric / "input_hashes_before.json", before)
    map_reference = json.loads((ROOT / "plot/08_vulnerability_exposure/output/qgis/exposure/exposure_jenks_update.json").read_text())
    # Expand the lightness gap above Moderate to emphasize High/Very High.
    colors = ["#edf8f6", "#ccece6", "#99d8c9", "#238b45", "#00441b"]
    config = {"run_id": run_id, "created_Asia_Shanghai": created.isoformat(), "work_directory": str(work),
              "final_directory": str(final), "statistics_directory": str(numeric),
              "source_project": str(ROOT / "plot/08_vulnerability_exposure/qgis/projects/08b_exposure.qgz"),
              "class_colors": colors, "class_names": ["Very Low", "Low", "Moderate", "High", "Very High"],
              "palette_intent": "Low-to-moderate classes are pale teal; High is saturated green and Very High is dark green; original class thresholds remain unchanged",
              "class_breaks": map_reference["breaks"], "width_inches": WIDTH, "height_inches": HEIGHT,
              "map_left_inches": MAP_LEFT, "map_bottom_inches": MAP_BOTTOM, "map_width_inches": MAP_WIDTH,
              "map_height_inches": MAP_HEIGHT, "stats_left_inches": STATS_LEFT, "stats_bottom_inches": STATS_BOTTOM,
              "stats_width_inches": STATS_WIDTH, "stats_height_inches": STATS_HEIGHT}
    config["map_share_of_figure_width"] = MAP_WIDTH / WIDTH
    config["include_statistics"] = include_statistics
    config["figure_stem"] = STEM
    config["statistical_layout"] = ("Four equal-height panels stacked vertically on the right, with compact equal spacing and single-line x labels"
                                    if include_statistics else "No statistical panels; canvas trimmed to map and footer")
    if include_statistics:
        config["statistical_panel_height_inches"] = PANEL_HEIGHT
        config["statistical_row_gap_inches"] = ROW_GAP
    config["panel_identifier_top_pad_pt"] = PANEL_ID_TOP_PAD_PT
    config["map_footer_retained"] = "All five exposure legend classes and mapped/total sample-size note"
    configuration = work / "composition_config.json"
    write_json(configuration, config)
    run_command([ROOT / "plot/shared/qgis/scripts/run_pyqgis.sh", CODE / "export_green_map.py", configuration])
    map_audit = json.loads((numeric / "map_export_audit.json").read_text())
    details, correlation = {"panels": []}, None
    shared.set_style()
    if include_statistics:
        print("Drawing statistical panels (b-e)", flush=True)
        frame, audit = shared.read_existing_results()
        tables = shared.histogram_tables(frame, audit, numeric)
        pairs, correlation = shared.paired_analysis(frame, numeric)
        write_json(numeric / "sample_audit.json", audit)
        shared.FIGURE_SIZE = (STATS_WIDTH, STATS_HEIGHT)
        shared.AXIS_BOUNDS = tuple((.12, bottom, .70, AX_HEIGHT) for bottom in ROW_BOTTOMS)
        shared.COLORBAR_BOUNDS = (.86, ROW_BOTTOMS[-1], .017, AX_HEIGHT)
        shared.LABELS = {field: label.replace("\n", " ") for field, label in shared.LABELS.items()}
        shared.aligned_identifiers = labels_bcde
        shared.check_layout = check_vertical_layout
        fig, details = shared.create_figure(tables, audit, pairs, correlation, numeric)
        for letter, panel in zip("bcde", details["panels"]):
            panel["panel"] = letter
        for extension in ("pdf", "svg"):
            fig.savefig(work / f"statistical_panels_bcde.{extension}", facecolor="white", transparent=False)
        plt.close(fig)
    overlay = plt.figure(figsize=(WIDTH, HEIGHT), dpi=100, facecolor="none")
    map_spine_left = MAP_LEFT + MAP_WIDTH * 10 / 195
    overlay.text((map_spine_left - 8 / 72) / WIDTH, (MAIN_TOP + PANEL_ID_TOP_PAD_PT / 72) / HEIGHT,
                 "(a)", fontsize=24, ha="right", va="bottom", fontfamily="Arial", fontweight="bold", bbox=None)
    sample_note = f"Mapped buildings: N = {map_audit['mapped_n']:,}; total sample: N = {map_audit['source_n']:,}"
    overlay.text((MAP_LEFT + MAP_WIDTH / 2) / WIDTH, .24 / HEIGHT,
                 sample_note, fontsize=18, ha="center", va="bottom",
                 fontfamily="Arial", fontweight="bold")
    for extension in ("pdf", "svg"):
        overlay.savefig(work / f"panel_a_and_sample_note.{extension}", transparent=True)
    plt.close(overlay)
    run_command([PDF_PYTHON, CODE / "assemble_pdf.py", configuration])
    svg = merge_svg(config)
    pdf = work / f"{STEM}.pdf"
    preview_prefix = work / f"{STEM}_preview"
    run_command([PDFTOPPM, "-f", 1, "-l", 1, "-r", 150, "-singlefile", "-png", pdf, preview_prefix])
    print("Composite preview: " + str(preview_prefix.with_suffix(".png")), flush=True)
    png = work / f"{STEM}_1200dpi.png"
    render_streamed_png(pdf, png, work)
    final_files = {}
    for path in (png, pdf, svg):
        target = final / path.name
        shutil.copy2(path, target)
        assert shared.sha256(path) == shared.sha256(target)
        final_files[path.suffix[1:]] = str(target)
    after = {str(path): shared.sha256(path) for path in sorted(protected)}
    assert before == after, "Original exposure project, model/result or map was modified"
    write_json(numeric / "protected_input_hashes.json", {"unchanged": True, "sha256_before_and_after": before})
    parameters = {**config, "font_sizes_pt": shared.FONT_SIZES, "statistical_panels": details,
                  "histogram_edges": shared.EDGES.tolist() if include_statistics else None, "spearman": correlation,
                  "source_n": map_audit["source_n"], "mapped_n": map_audit["mapped_n"], "map_extent_unchanged": True,
                  "sample_note": sample_note,
                  "native_map_vector_content": "Buildings, boundaries, symbols and outlined text; original terrain is raster",
                  "panel_identifiers": list("abcde") if include_statistics else ["a"],
                  "identifier_alignment": ("(a) and (b) share the same main-spine top and label baseline; (b-e) share one x position"
                                           if include_statistics else "(a) retained outside the upper-left map corner"),
                  "final_files": final_files, "preview": str(preview_prefix.with_suffix(".png")),
                  "export_dpi": 1200, "png_dimensions": [round(WIDTH * 1200), round(HEIGHT * 1200)],
                  "plot_code_sha256": {str(path): shared.sha256(path) for path in CODE.glob("*.py")}}
    write_json(numeric / "composition_parameters.json", parameters)
    write_json(work / "figure_manifest.json", parameters)
    shutil.copy2(work / "figure_manifest.json", final / "figure_manifest.json")
    for path in CODE.glob("*.py"):
        shutil.copy2(path, numeric / path.name)
    print(json.dumps({"work": str(work), "statistics": str(numeric), "final": str(final), "preview": parameters["preview"]}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-statistics", action="store_true", help="Recreate the earlier five-panel composite; default exports only the map")
    run(include_statistics=parser.parse_args().with_statistics)
