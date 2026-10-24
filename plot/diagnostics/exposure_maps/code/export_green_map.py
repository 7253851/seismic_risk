"""Export a recolored, separately saved QGIS map; never save the source project."""
from pathlib import Path
import hashlib
import json
import os
import sys
import re
import xml.etree.ElementTree as ET

from qgis.core import *
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def restore_svg_map_clip(path, main):
    """Qt's SVG Tiny backend drops painter clipping; restore the map frame."""
    tree = ET.parse(path); root = tree.getroot()
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    paint = next(node for node in root if node.tag == f"{{{ns}}}g")
    groups = list(paint)
    units = float(root.get("viewBox").split()[2]) / 195
    left, top = main.pos().x() * units, main.pos().y() * units
    def at_map_origin(node):
        values = [float(value) for value in re.findall(r"[-+0-9.eE]+", node.get("transform", "").replace("matrix", ""))]
        return len(values) == 6 and abs(values[4] - left) < .03 and abs(values[5] - top) < .03
    start = next(index for index, node in enumerate(groups) if at_map_origin(node))
    end = next(index for index, node in enumerate(groups) if index > start and at_map_origin(node)
               and any(child.tag == f"{{{ns}}}polyline" for child in node))
    defs = next(node for node in root if node.tag == f"{{{ns}}}defs")
    clip = ET.SubElement(defs, f"{{{ns}}}clipPath", {"id": "native_map_frame_clip", "clipPathUnits": "userSpaceOnUse"})
    ET.SubElement(clip, f"{{{ns}}}rect", {"x": str(left), "y": str(top),
                  "width": str(main.sizeWithUnits().width() * units),
                  "height": str(main.sizeWithUnits().height() * units)})
    wrapped = ET.Element(f"{{{ns}}}g", {"clip-path": "url(#native_map_frame_clip)"})
    for node in groups[start:end]:
        paint.remove(node); wrapped.append(node)
    paint.insert(start, wrapped)
    root.set("version", "1.1"); root.attrib.pop("baseProfile", None)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def run(config_path):
    config = json.loads(Path(config_path).read_text())
    source = Path(config["source_project"])
    work = Path(config["work_directory"])
    stats = Path(config["statistics_directory"])
    source_hash = digest(source)
    project = QgsProject()
    assert project.read(str(source))
    layout = project.layoutManager().layoutByName("Kunming_Exposure")
    main = layout.referenceMap()
    extent = main.extent().toString(12)
    active_layers = list(main.layers())
    assert len(active_layers) == 9 and all(layer.isValid() for layer in active_layers)
    input_hashes = {layer.source().split("|")[0]: digest(layer.source().split("|")[0]) for layer in active_layers}
    building = next(layer for layer in active_layers if layer.customProperty("seismic_building/result_key", "") == "exposure")
    assert building.featureCount() == 53513 and not building.subsetString()
    overrides = main.layerStyleOverrides()
    QgsMapLayerStyle(overrides[building.id()]).writeToLayer(building)
    rules = building.renderer().rootRule().children()
    original_filters = [rule.filterExpression() for rule in rules]
    original_labels = [rule.label() for rule in rules]
    assert original_labels == config["class_names"]
    for index, (rule, color) in enumerate(zip(rules, config["class_colors"])):
        symbol = rule.symbol().clone()
        symbol.setColor(QColor(color))
        for fill in symbol.symbolLayers():
            if isinstance(fill, QgsSimpleFillSymbolLayer):
                fill.setStrokeColor(QColor(color).darker(130))
        rule.setSymbol(symbol)
        swatch = layout.itemById(f"Legend_class_{index}")
        patch = swatch.symbol().clone()
        patch.setColor(QColor(color))
        for fill in patch.symbolLayers():
            if isinstance(fill, QgsSimpleFillSymbolLayer):
                fill.setStrokeColor(QColor(color))
        swatch.setSymbol(patch)
    style = QgsMapLayerStyle()
    style.readFromLayer(building)
    updated = dict(overrides)
    updated[building.id()] = style.xmlData()
    main.setLayerStyleOverrides(updated)
    assert all(updated[key] == value for key, value in overrides.items() if key != building.id())
    assert [rule.filterExpression() for rule in rules] == original_filters
    assert [rule.label() for rule in rules] == original_labels

    scale = config["map_width_inches"] / (195 / 25.4)
    label_audit = []
    for item in layout.items():
        if not isinstance(item, QgsLayoutItemLabel):
            continue
        ident = item.id()
        target_pt = (24 if ident in {"Wuhua", "Panlong", "Xishan", "Guandu", "Chenggong", "Dian_Lake"}
                     else 18 if ident == "North_text" else 16)
        native_pt = target_pt / scale
        if ident == "Legend_title":
            item.setText("Exposure")
        format_ = item.textFormat()
        font = QFont("Arial")
        font.setBold(True)
        font.setItalic(False)
        font.setPointSizeF(native_pt)
        format_.setFont(font)
        format_.setSize(native_pt)
        item.setTextFormat(format_)
        item.setMargin(0)
        old_x, old_y = item.pos().x(), item.pos().y()
        old_w, old_h = item.sizeWithUnits().width(), item.sizeWithUnits().height()
        metrics = QFontMetricsF(font)
        lines = item.text().split("\n")
        dpi = metrics.fontDpi()
        width = max(old_w, max(metrics.horizontalAdvance(line) for line in lines) / dpi * 25.4 + .4)
        height = max(old_h, metrics.height() * len(lines) / dpi * 25.4 + .4)
        item.attemptResize(QgsLayoutSize(width, height))
        item.attemptMove(QgsLayoutPoint(old_x - (width - old_w) / 2, old_y - (height - old_h) / 2))
        if ident == "Legend_title":
            item.attemptMove(QgsLayoutPoint(28 - width, item.pos().y()))
        label_audit.append({"id": ident, "text": item.text(), "font": "Arial Bold", "final_pt": target_pt,
                            "native_pt": native_pt, "x_mm": item.pos().x(), "y_mm": item.pos().y(),
                            "width_mm": width, "height_mm": height})
    grid_format = main.grid().annotationTextFormat()
    font = QFont("Arial"); font.setBold(True); font.setPointSizeF(16 / scale)
    grid_format.setFont(font); grid_format.setSize(16 / scale)
    main.grid().setAnnotationTextFormat(grid_format)
    scale_bar = layout.itemById("Overview_scale")
    scale_format = scale_bar.textFormat()
    scale_format.setFont(font); scale_format.setSize(16 / scale)
    scale_bar.setTextFormat(scale_format)
    assert main.extent().toString(12) == extent
    layout.refresh()
    exporter = QgsLayoutExporter(layout)
    image_settings = QgsLayoutExporter.ImageExportSettings(); image_settings.dpi = 180
    preview = work / "building_exposure_BuGn_preview.png"
    assert exporter.exportToImage(str(preview), image_settings) == QgsLayoutExporter.Success
    print("Green map preview: " + str(preview), flush=True)
    pdf_settings = QgsLayoutExporter.PdfExportSettings()
    pdf_settings.dpi = 600
    pdf_settings.forceVectorOutput = True
    pdf_settings.rasterizeWholeImage = False
    pdf_settings.simplifyGeometries = False
    pdf_settings.appendGeoreference = False
    pdf_settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysOutlines
    pdf = work / "building_exposure_BuGn.pdf"
    assert exporter.exportToPdf(str(pdf), pdf_settings) == QgsLayoutExporter.Success
    svg_settings = QgsLayoutExporter.SvgExportSettings()
    svg_settings.dpi = 600
    svg_settings.forceVectorOutput = True
    svg_settings.simplifyGeometries = False
    svg_settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysOutlines
    svg = work / "building_exposure_BuGn.svg"
    assert exporter.exportToSvg(str(svg), svg_settings) == QgsLayoutExporter.Success
    restore_svg_map_clip(svg, main)
    # Save a local derivative with absolute data paths and only the active layers.
    project.removeMapLayers([ident for ident in project.mapLayers() if ident not in {layer.id() for layer in active_layers}])
    project.setFilePathStorage(Qgis.FilePathType.Absolute)
    derivative = work / "building_exposure_BuGn.qgz"
    project.setFileName(str(derivative))
    assert project.write()
    assert digest(source) == source_hash
    assert all(digest(path) == before for path, before in input_hashes.items())
    report = {"source_project": str(source), "source_project_unchanged": True, "input_files_unchanged": True,
              "source_hashes": input_hashes, "extent": extent, "extent_unchanged": True,
              "source_n": 53513, "mapped_n": 53395, "class_names": original_labels,
              "class_filters": original_filters, "class_colors": config["class_colors"], "class_breaks": config["class_breaks"],
              "classifications_unchanged": True, "other_layer_styles_unchanged": True,
              "final_scale_factor": scale, "typography": label_audit,
              "raster_content": "Original local hillshade background only; PDF/SVG export forces vector geometry and outlined text",
              "native_raster_export_dpi": 600, "pdf": str(pdf), "svg": str(svg), "preview": str(preview),
              "svg_map_geometry_clipped_to_original_frame": True,
              "editable_project": str(derivative)}
    (stats / "map_export_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("Native map PDF/SVG and derivative project exported", flush=True)


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.setPrefixPath("/Applications/QGIS.app/Contents/Resources/qgis", True)
    app.initQgis()
    run(sys.argv[1])
    os._exit(0)
