#!/usr/bin/env python3
"""Save the current 1200 dpi PGA PNG as a lossless single-page PDF."""
from pathlib import Path
import hashlib
import json

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

Image.MAX_IMAGE_PIXELS = 300_000_000
WORKSPACE = Path(__file__).resolve().parents[3]
FINAL = WORKSPACE / "plot/04_seismic_hazard/output"
SOURCE = WORKSPACE / "plot/04_seismic_hazard/output/final/figure04.png"
DESTINATION = FINAL / "PGA_Combined_abcd.pdf"
WORK = WORKSPACE / "plot/04_seismic_hazard/output"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    with Image.open(SOURCE) as picture:
        width, height = picture.size
        assert picture.mode == "RGB"
        assert all(abs(value - 1200) < 1 for value in picture.info["dpi"])
        picture.verify()
    source_hash = sha256(SOURCE)
    layout = json.loads((WORK / "layout_metadata.json").read_text())
    assert source_hash == layout["final_sha256"], "PNG differs from the current layout record"
    page_size = (width / 1200 * 72, height / 1200 * 72)
    stage = FINAL / ".PGA_Combined_abcd_stage.pdf"
    document = canvas.Canvas(str(stage), pagesize=page_size, pageCompression=1)
    document.setTitle("PGA composite figure")
    document.drawImage(ImageReader(str(SOURCE)), 0, 0, width=page_size[0], height=page_size[1])
    document.showPage()
    document.save()
    reader = PdfReader(stage)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert abs(float(page.mediabox.width) - page_size[0]) < 0.01
    assert abs(float(page.mediabox.height) - page_size[1]) < 0.01
    images = [item.get_object() for item in page["/Resources"]["/XObject"].values()
              if item.get_object().get("/Subtype") == "/Image"]
    assert len(images) == 1
    assert images[0]["/Width"] == width and images[0]["/Height"] == height
    assert "/DCTDecode" not in images[0].get("/Filter", []), "Lossy image compression is not permitted"
    stage.replace(DESTINATION)
    report = {"source_png": str(SOURCE), "source_sha256": source_hash,
              "pdf": str(DESTINATION), "pdf_sha256": sha256(DESTINATION),
              "pages": 1, "page_size_pt": page_size, "embedded_image_pixels": [width, height],
              "effective_image_dpi": 1200, "lossless_image_embedding": True,
              "layout_preserved": True}
    (WORK / "pdf_export.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
