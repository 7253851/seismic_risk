"""Render an A4 figure PDF at 600 dpi and crop it to a 600-dpi RGB LZW TIFF.

The crop starts from the box used for the adopted 2026-10-21 TIFF and is only
expanded (by whole pixels) where new content, such as panel letters, falls
outside it, keeping a small white margin around that content.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
DPI = 600
MARGIN_PX = 24


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render(pdf):
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp)/'page'
        subprocess.run(['pdftoppm', '-r', str(DPI), '-png', '-singlefile', '-f', '1', '-l', '1', str(pdf), str(stem)], check=True)
        return Image.open(f'{stem}.png').convert('RGB')


def content_box(image, threshold=250):
    data = np.asarray(image)
    ink = (data < threshold).any(axis=2)
    rows, cols = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
    return [int(cols[0]), int(rows[0]), int(cols[-1])+1, int(rows[-1])+1]


def export(pdf, out, reference_box):
    page = render(pdf)
    ink = content_box(page)
    box = [min(reference_box[0], ink[0]-MARGIN_PX), min(reference_box[1], ink[1]-MARGIN_PX),
           max(reference_box[2], ink[2]+MARGIN_PX), max(reference_box[3], ink[3]+MARGIN_PX)]
    box = [max(0, box[0]), max(0, box[1]), min(page.width, box[2]), min(page.height, box[3])]
    figure = page.crop(box)
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.save(out, compression='tiff_lzw', dpi=(DPI, DPI))
    png = out.with_suffix('.png')
    figure.save(png, dpi=(DPI, DPI))
    check = Image.open(out)
    assert check.mode == 'RGB' and check.size == figure.size and round(check.info['dpi'][0]) == DPI
    return {'source_pdf': str(pdf), 'source_sha256': sha(pdf), 'reference_crop_px': reference_box,
            'content_bbox_px': ink, 'crop_bbox_px': box, 'pixels': list(figure.size),
            'physical_mm': [figure.width/DPI*25.4, figure.height/DPI*25.4], 'dpi': DPI, 'mode': 'RGB',
            'compression': 'LZW', 'tiff': str(out), 'tiff_sha256': sha(out), 'png': str(png)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('pdf', type=Path)
    parser.add_argument('tiff', type=Path)
    parser.add_argument('--reference-box', type=int, nargs=4, default=[354, 590, 4607, 4441])
    args = parser.parse_args()
    report = export(args.pdf, args.tiff, args.reference_box)
    args.tiff.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
