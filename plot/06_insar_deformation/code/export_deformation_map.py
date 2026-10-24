"""Export the saved QGIS map with its movable legend omitted, without saving it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from qgis.core import Qgis, QgsApplication, QgsLayoutExporter, QgsLayoutItemMap, QgsProject

ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "plot/06_insar_deformation/qgis/projects/06_insar_deformation.qgz"
SOURCE_PDF = ROOT / "plot/06_insar_deformation/output/qgis/tsx_deformation/Kunming_TSX_Vertical_Deformation.pdf"
WORK = ROOT / "plot/06_insar_deformation/output"
OMIT = [
    "Historical_earthquakes_legend_symbol", "Historical_earthquakes_legend_label",
    "GNSS_legend_symbol", "GNSS_legend_label", "Fault_legend_symbol", "Fault_legend_label",
    "Left_lateral_legend_symbol", "Left_lateral_legend_label", "Deformation_Scale",
]


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def map_state(item):
    extent = item.extent()
    return {"id": item.id(), "crs": item.crs().authid(),
            "extent": [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()],
            "size_mm": [item.sizeWithUnits().width(), item.sizeWithUnits().height()],
            "layer_ids": [layer.id() for layer in item.layers()],
            "layer_style_sha256": {key: hashlib.sha256(value.encode()).hexdigest()
                                   for key, value in item.layerStyleOverrides().items()}}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    source_hashes = {str(path): fingerprint(path) for path in (PROJECT, SOURCE_PDF)}
    app = QgsApplication([], False)
    app.initQgis()
    project = QgsProject.instance()
    if not project.read(str(PROJECT)):
        raise RuntimeError(f"Could not open {PROJECT}")
    layout = project.layoutManager().layoutByName("Kunming_TSX_Vertical_Deformation")
    if layout is None:
        raise RuntimeError("Saved deformation layout not found")
    maps = [item for item in layout.items() if isinstance(item, QgsLayoutItemMap)]
    before = [map_state(item) for item in maps]
    for item_id in OMIT:
        item = layout.itemById(item_id)
        if item is None:
            raise RuntimeError(f"Legend item missing: {item_id}")
        item.setVisibility(False)
        item.setExcludeFromExports(True)
    after = [map_state(item) for item in maps]
    if before != after:
        raise RuntimeError("Map extent, layers, or styles changed while moving the legend")
    layout.refresh()
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = 1200
    settings.forceVectorOutput = True
    settings.rasterizeWholeImage = False
    settings.simplifyGeometries = False
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    settings.appendGeoreference = False
    output = WORK / "map_without_legend.pdf"
    result = QgsLayoutExporter(layout).exportToPdf(str(output), settings)
    if result != QgsLayoutExporter.Success:
        raise RuntimeError(f"QGIS PDF export failed: {result}")
    for path, digest in source_hashes.items():
        if fingerprint(path) != digest:
            raise RuntimeError(f"Source changed: {path}")
    main_map = max(after, key=lambda state: state["size_mm"][0]*state["size_mm"][1])
    record = {"source_hashes": source_hashes, "script_sha256": fingerprint(__file__),
              "excluded_items": OMIT, "map_states": after,
              "main_map": main_map, "source_project_saved": False,
              "output": str(output), "output_sha256": fingerprint(output)}
    (WORK / "map_export_manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"output": str(output), "excluded_items": OMIT}))
    project.clear()
    app.exitQgis()


if __name__ == "__main__":
    main()
