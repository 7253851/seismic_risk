#!/usr/bin/env python3
"""Copy the current native study-area layout, preserving its labels and pixels."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

from PIL import Image

Image.MAX_IMAGE_PIXELS = 250_000_000

WORKSPACE = Path(__file__).resolve().parents[3]
OUTPUT = WORKSPACE / "plot/01_study_area/output"
FINAL_OUTPUT = OUTPUT
SOURCE = WORKSPACE / "plot/01_study_area/output/qgis/study_area/Study_Area_source_1200dpi.png"
DPI = 1200


def fingerprint(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with Image.open(path) as picture:
        dpi = picture.info.get("dpi")
        return {"path": str(path), "sha256": digest, "pixels": list(picture.size),
                "dpi": [float(value) for value in dpi] if dpi else None, "mode": picture.mode}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='Update the adopted figure and manuscript PNG')
    args = parser.parse_args()
    source_record = fingerprint(SOURCE)
    if not source_record["dpi"] or any(abs(value - DPI) > 1 for value in source_record["dpi"]):
        raise ValueError("The study-area source must have a native resolution of 1200 dpi")
    FINAL_OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = FINAL_OUTPUT / f"Study_Area_{DPI}dpi.png"
    stage = FINAL_OUTPUT / ".Study_Area_stage.png"
    shutil.copy2(SOURCE, stage)
    stage.replace(destination)
    with Image.open(SOURCE) as source:
        preview = source.copy()
    preview.thumbnail((2200, 1600), Image.Resampling.LANCZOS)
    preview.save(OUTPUT / "Study_Area_preview.png", dpi=(150, 150))
    for obsolete in FINAL_OUTPUT.glob("Study_Area_ab_*.png"):
        if obsolete != destination:
            obsolete.unlink()

    manifest_path = OUTPUT / "source_manifest.json"
    metadata = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    metadata["final_folder"] = str(FINAL_OUTPUT)
    metadata["study_area"] = {
        "source": source_record,
        "saved_layout_project": str(WORKSPACE / "plot/01_study_area/qgis/projects/01_study_area.qgz"),
        "final": fingerprint(destination),
        "layout_labels": "Preserved from the current QGIS layout; no panel letters added",
        "native_source_pixels_preserved": fingerprint(destination)["sha256"] == source_record["sha256"],
        "export_policy": "One canonical 1200 dpi PNG per final figure; replace the previous-resolution final on rebuild",
    }
    if args.publish:
        for target in [WORKSPACE / 'plot/01_study_area/output/final/figure01.png']:
            shutil.copy2(destination, target)
        index_path = WORKSPACE / 'plot/figure_index.json'
        index = json.loads(index_path.read_text(encoding='utf-8'))
        figure = next(item for item in index['figures'] if item['figure'] == 1)
        figure['adopted_sha256'] = fingerprint(destination)['sha256']
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        metadata['study_area']['published'] = True
    manifest_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata["study_area"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
