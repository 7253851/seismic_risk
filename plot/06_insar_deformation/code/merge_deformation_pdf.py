"""Merge the QGIS map export and vector chart overlay in paper coordinates."""
import argparse
from io import BytesIO
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width-mm", type=float, default=180.)
    parser.add_argument("--height-mm", type=float, default=163.)
    parser.add_argument("--map-width-mm", type=float, default=112.)
    parser.add_argument("--map-left-mm", type=float, default=.3)
    parser.add_argument("--map-top-mm", type=float, default=-.5)
    args = parser.parse_args()
    pt = 72/25.4
    width, height = args.width_mm*pt, args.height_mm*pt
    empty = BytesIO()
    document = canvas.Canvas(empty, pagesize=(width, height), pageCompression=1)
    document.setTitle("InSAR deformation and GNSS comparison")
    document.showPage()
    document.save()
    empty.seek(0)
    base = PdfReader(empty).pages[0]
    source = PdfReader(args.map).pages[0]
    scale = args.map_width_mm*pt/float(source.mediabox.width)
    map_height_mm = float(source.mediabox.height)*scale/pt
    bottom = height-args.map_top_mm*pt-float(source.mediabox.height)*scale
    base.merge_transformed_page(source, Transformation().scale(scale).translate(args.map_left_mm*pt, bottom))
    base.merge_page(PdfReader(args.overlay).pages[0])
    writer = PdfWriter()
    writer.add_page(base)
    writer.add_metadata({"/Title": "InSAR deformation and GNSS comparison", "/Author": "seismic_risk"})
    writer.write(args.output)
    print(json.dumps({"map_box_mm": [args.map_left_mm, args.map_top_mm, args.map_width_mm, map_height_mm],
                      "map_area_mm2": args.map_width_mm*map_height_mm,
                      "map_page_width_share": args.map_width_mm/args.width_mm}))


if __name__ == "__main__":
    main()
