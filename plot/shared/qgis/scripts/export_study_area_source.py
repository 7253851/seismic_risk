#!/usr/bin/env python3
"""Render the saved study-area layout at 1200 dpi without changing its project."""
from pathlib import Path
import hashlib
import json
import os

from qgis.core import QgsApplication, QgsProject, QgsLayoutExporter


WORKSPACE = Path(__file__).resolve().parents[4]
OUTPUT = WORKSPACE / "plot/01_study_area/output/qgis/study_area"
OUTPUT.mkdir(parents=True, exist_ok=True)
SOURCE = WORKSPACE / "plot/01_study_area/qgis/projects/01_study_area.qgz"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


app = QgsApplication([], False)
app.setPrefixPath("/Applications/QGIS.app/Contents/Resources/qgis", True)
app.initQgis()
before = sha256(SOURCE)
project = QgsProject()
if not project.read(str(SOURCE)):
    raise RuntimeError(f"Cannot read {SOURCE}")
layout = project.layoutManager().layoutByName("Kunming_Study_Area")
if layout is None:
    raise RuntimeError("Saved study-area layout is missing")
layout.renderContext().setDpi(1200)
layout.refresh()
settings = QgsLayoutExporter.ImageExportSettings()
settings.dpi = 1200
settings.exportMetadata = False
stage = OUTPUT / ".Study_Area_source_1200dpi_stage.png"
destination = OUTPUT / "Study_Area_source_1200dpi.png"
print("Rendering saved study-area layout at 1200 dpi...", flush=True)
result = QgsLayoutExporter(layout).exportToImage(str(stage), settings)
if result != QgsLayoutExporter.Success:
    raise RuntimeError(f"QGIS export failed: {result}")
stage.replace(destination)
if sha256(SOURCE) != before:
    raise RuntimeError("Saved study-area project changed during export")
print(json.dumps({"path": str(destination), "dpi": 1200,
                  "project_unchanged": True, "project_sha256": before}), flush=True)
os._exit(0)
