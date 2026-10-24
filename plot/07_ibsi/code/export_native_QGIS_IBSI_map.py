"""Reuse the user's saved QGIS layout, saving only an IBSI draft derivative.

plot/shared/qgis/scripts/run_pyqgis.sh plot/07_ibsi/code/export_native_QGIS_IBSI_map.py
"""
from pathlib import Path
import bisect
import csv
import hashlib
import json
import math
import os
import sqlite3

from qgis.core import *
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QPolygonF

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "plot/07_ibsi/output"
PROJECT = ROOT / "plot/04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz"
SOURCE = ROOT / "result/vulnerability/scs_paper_method/01_building_vulnerability_metrics.gpkg"
CLASS_COLORS = ["#F4D35E", "#9CCD73", "#45B7A5", "#287FB8", "#443983"]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(2**20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    app = QgsApplication([], False)
    app.initQgis()
    source_hash = sha(PROJECT)
    project = QgsProject()
    assert project.read(str(PROJECT))
    layout = project.layoutManager().layoutByName("Kunming_Hazard_PGA")
    main_map = layout.referenceMap()
    old_extent = QgsRectangle(main_map.extent())
    active = list(main_map.layers())
    assert len(active) == 9 and all(layer.isValid() for layer in active)
    # Apply the saved map's own style overrides before replacing its thematic layer.
    original_overrides = main_map.layerStyleOverrides()
    for layer in active:
        if layer.id() in original_overrides:
            QgsMapLayerStyle(original_overrides[layer.id()]).writeToLayer(layer)
    old_buildings = next(layer for layer in active if layer.customProperty("seismic_building/result_key", "") == "hazard")
    consulted = {str(PROJECT): source_hash, str(SOURCE): sha(SOURCE)}
    for layer in active:
        path = Path(layer.source().split("|")[0])
        if path.is_file():
            consulted[str(path)] = sha(path)
    building = QgsVectorLayer(str(SOURCE) + "|layername=building_vulnerability_metrics", "IBSI · saved building inventory", "ogr")
    assert building.isValid() and building.featureCount() == 57228 and not building.subsetString()
    project.addMapLayer(building, False)
    # Display-only quintiles from the stored IBSI column. No model or stored
    # indicator is recomputed, normalized, clipped, or overwritten.
    with sqlite3.connect(SOURCE.as_uri() + "?mode=ro", uri=True) as con:
        values = sorted(float(row[0]) for row in con.execute(
            'SELECT IBSI FROM building_vulnerability_metrics WHERE Vul_Valid=1'))
    assert len(values) == 41939 and values[0] == 0 and 0 < values[-1] <= 1
    def quantile(p):
        rank = (len(values) - 1) * p
        lo, hi = math.floor(rank), math.ceil(rank)
        return values[lo] + (values[hi] - values[lo]) * (rank - lo)
    edges = [quantile(p) for p in [0, .2, .4, .6, .8, 1]]
    counts = [0] * 5
    visible_counts = [0] * 5
    for value in values:
        counts[bisect.bisect_left(edges[1:], value)] += 1
    expression = 'CASE WHEN "Vul_Valid"!=1 OR "IBSI" IS NULL THEN \'#b6b6b6\' '
    for upper, color in zip(edges[1:], CLASS_COLORS):
        expression += f'WHEN "IBSI"<={upper:.17g} THEN \'{color}\' '
    expression += "ELSE '#443983' END"
    symbol = QgsFillSymbol.createSimple({"color": "#b6b6b6", "outline_color": "#b6b6b6",
                                         "outline_width": "0.08", "outline_width_unit": "Point",
                                         "joinstyle": "miter"})
    sl = symbol.symbolLayer(0)
    sl.setDataDefinedProperty(QgsSymbolLayer.PropertyFillColor, QgsProperty.fromExpression(expression))
    sl.setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeColor, QgsProperty.fromExpression(expression))
    building.setRenderer(QgsSingleSymbolRenderer(symbol))
    active = [building if layer.id() == old_buildings.id() else layer for layer in active]
    main_map.setLayers(active)
    overrides = {k: v for k, v in original_overrides.items() if k != old_buildings.id()}
    style = QgsMapLayerStyle(); style.readFromLayer(building)
    overrides[building.id()] = style.xmlData()
    main_map.setLayerStyleOverrides(overrides)
    main_map.setKeepLayerSet(True); main_map.setKeepLayerStyles(True)
    # The user's requested map extent, scale and frame are exactly the existing
    # QGIS layout. Record coverage explicitly; do not change the histogram cohort.
    transform = QgsCoordinateTransform(building.crs(), main_map.crs(), project)
    envelope = QgsRectangle()
    old_inside = 0; valid_count = 0; intersects_count = 0; visible_valid = 0
    geometries = []
    for feature in building.getFeatures():
        geom = QgsGeometry(feature.geometry()); geom.transform(transform)
        box = geom.boundingBox(); envelope.combineExtentWith(box)
        geometries.append((int(feature["Build_ID"]), box))
        old_inside += int(old_extent.contains(box))
        valid_count += int(feature["Vul_Valid"] == 1)
        intersects_count += int(geom.intersects(QgsGeometry.fromRect(old_extent)))
        visible_valid += int(feature["Vul_Valid"] == 1 and geom.intersects(QgsGeometry.fromRect(old_extent)))
        if feature["Vul_Valid"] == 1 and geom.intersects(QgsGeometry.fromRect(old_extent)):
            visible_counts[bisect.bisect_left(edges[1:], float(feature["IBSI"]))] += 1
    assert valid_count == 41939
    new_extent = QgsRectangle(old_extent)
    assert main_map.extent() == old_extent
    # Existing manually positioned geographic labels are moved with their
    # geographic anchors. Their fonts, colors, halos and rotations are reused.
    left, top = main_map.pos().x(), main_map.pos().y()
    map_width, map_height = main_map.sizeWithUnits().width(), main_map.sizeWithUnits().height()
    zoom = old_extent.width() / new_extent.width()
    def remap(point):
        gx = old_extent.xMinimum() + (point.x() - left) / map_width * old_extent.width()
        gy = old_extent.yMaximum() - (point.y() - top) / map_height * old_extent.height()
        return QPointF(left + (gx - new_extent.xMinimum()) / new_extent.width() * map_width,
                       top + (new_extent.yMaximum() - gy) / new_extent.height() * map_height)
    geographic_ids = {"Wuhua", "Panlong", "Xishan", "Guandu", "Chenggong", "Dian_Lake",
                      "Historical_event_0", "Event_2026_annotation", "GNSS_station_label",
                      "GNSS_station_symbol"}
    label_report = []
    for item in layout.items():
        if not isinstance(item, QgsLayoutItem):
            continue
        ident = item.id()
        if ident in geographic_ids or ident.startswith("Fault_") and "legend" not in ident:
            if isinstance(item, QgsLayoutItemLabel):
                # Map the true item center to preserve its geographic placement,
                # including rotated fault labels.
                old_center = item.mapToScene(item.rect().center())
                target = remap(old_center)
                delta = target - old_center
                item.setPos(item.pos() + delta)
            elif isinstance(item, QgsLayoutItemMarker):
                item.attemptMove(QgsLayoutPoint(remap(item.pos())))
        if ident.startswith("Leader_") and isinstance(item, QgsLayoutItemPolyline):
            points = [remap(item.mapToScene(p)) for p in item.nodes()]
            minimum_x = min(p.x() for p in points); minimum_y = min(p.y() for p in points)
            item.setNodes(QPolygonF([QPointF(p.x() - minimum_x, p.y() - minimum_y) for p in points]))
            item.attemptMove(QgsLayoutPoint(minimum_x, minimum_y))
        if ident == "Legend_title" or ident.startswith("Legend_range_") or ident.startswith("Legend_class_"):
            item.setVisibility(False); item.setExcludeFromExports(True)
        if isinstance(item, QgsLayoutItemLabel) and item.isVisible():
            fmt = item.textFormat()
            previous_size = float(fmt.size())
            previous_width = item.sizeWithUnits().width()
            previous_height = item.sizeWithUnits().height()
            previous_center = item.mapToScene(item.rect().center())
            size = max(previous_size, 15.2)
            font = fmt.font(); font.setFamily("Arial"); font.setPointSizeF(size)
            fmt.setFont(font); fmt.setSize(size)
            item.setTextFormat(fmt)
            metrics = QFontMetricsF(font)
            text_width = max(metrics.horizontalAdvance(line) for line in item.text().split("\n")) / metrics.fontDpi() * 25.4
            text_height = metrics.height() * len(item.text().split("\n")) / metrics.fontDpi() * 25.4
            growth = max(1, size / previous_size) * 1.06
            item.attemptResize(QgsLayoutSize(max(previous_width * growth, text_width + 1.5),
                                             max(previous_height * growth, text_height + .5)))
            item.setPos(item.pos() + previous_center - item.mapToScene(item.rect().center()))
            if ident == "GNSS_station_label":
                item.setPos(item.pos() + QPointF(0, 7))
            if ident == "Fault_Machang":
                item.setPos(item.pos() + QPointF(5, 3))
            label_report.append({"id": ident, "text": item.text(), "native_pt": size,
                                 "rotation": item.itemRotation()})
    fmt = main_map.grid().annotationTextFormat()
    font = fmt.font(); font.setFamily("Arial"); font.setPointSizeF(15.2)
    fmt.setFont(font); fmt.setSize(15.2)
    main_map.grid().setAnnotationTextFormat(fmt)
    scale = layout.itemById("Overview_scale")
    fmt = scale.textFormat(); font = fmt.font(); font.setFamily("Arial"); font.setPointSizeF(15.2)
    fmt.setFont(font); fmt.setSize(15.2); scale.setTextFormat(fmt)
    # Transparent, aligned context legend inside the map. The IBSI numeric
    # legend is composed separately below the map, with no background box.
    def text(ident, value, x, y, w, h, size=15.2):
        item = QgsLayoutItemLabel(layout); item.setId(ident); item.setText(value)
        fmt = QgsTextFormat(); font = QFont("Arial"); font.setBold(True); font.setPointSizeF(size)
        fmt.setFont(font); fmt.setSize(size); fmt.setColor(QColor("#222a30"))
        buffer = QgsTextBufferSettings(); buffer.setEnabled(True)
        buffer.setColor(QColor("white")); buffer.setSize(.6); fmt.setBuffer(buffer)
        item.setTextFormat(fmt); item.setMargin(0)
        item.setBackgroundEnabled(False); item.setFrameEnabled(False)
        item.setHAlign(Qt.AlignLeft); item.setVAlign(Qt.AlignVCenter)
        layout.addLayoutItem(item); item.attemptMove(QgsLayoutPoint(x, y))
        item.attemptResize(QgsLayoutSize(w, h)); item.setZValue(22)
        return item
    legend_positions = {
        "Earthquake_legend_symbol": (17.5, 165), "Earthquake_legend_label": (25, 162),
        "GNSS_legend_symbol": (17.5, 172), "GNSS_legend_label": (25, 169),
        "Fault_legend_symbol": (13.25, 179), "Fault_legend_label": (25, 176),
        "Left_lateral_legend_symbol": (12.25, 186), "Left_lateral_legend_label": (25, 183)}
    for ident, (x, y) in legend_positions.items():
        item = layout.itemById(ident)
        assert item is not None
        item.setPos(QPointF(x, y)); item.setZValue(22)
        item.setBackgroundEnabled(False); item.setFrameEnabled(False)
        if isinstance(item, QgsLayoutItemMarker):
            item.setPos(QPointF(x, y) - item.rect().center())
        if isinstance(item, QgsLayoutItemLabel):
            # Fresh fixed-height labels avoid inherited minimum sizes from the
            # original large layout while keeping its wording and symbols.
            value = item.text()
            item.setVisibility(False); item.setExcludeFromExports(True)
            text("Compact_" + ident, value, x, y, 46, 6)
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(195, 200))
    # Use only existing local print layers. No remote base map is rendered.
    project.removeMapLayers([ident for ident in project.mapLayers() if ident not in {layer.id() for layer in active}])
    project.setFilePathStorage(Qgis.FilePathType.Absolute)
    layout.setName("Kunming_IBSI_review")
    derivative = ROOT / "plot/07_ibsi/qgis/projects/07_ibsi.qgz"
    assert project.write(str(derivative))
    layout.refresh()
    exporter = QgsLayoutExporter(layout)
    # Exclude only the old thematic legend row and bottom margin. Retain native
    # graticule labels, context legend, scale bar, north arrow and map border.
    crop = QRectF(0, 0, 195, 200)
    for dpi, filename in [(600, "IBSI_native_QGIS_map.png"), (180, "IBSI_native_QGIS_map_preview.png")]:
        image = exporter.renderRegionToImage(crop, dpi=dpi)
        assert not image.isNull() and image.save(str(OUT / filename), "PNG")
    classification = {"method": "Five display-only quantile classes (P20/P40/P60/P80)",
                      "basis": "All 41939 saved valid IBSI observations, including zeros",
                      "interval_rule": "first interval includes minimum; subsequent lower bounds exclusive; all upper bounds inclusive",
                      "legend_precision": "3 decimals; classification uses full-precision boundaries",
                      "breaks": edges, "colors": CLASS_COLORS, "counts": counts,
                      "visible_counts": visible_counts, "model_or_indicator_changed": False}
    (OUT / "IBSI_display_classification.json").write_text(json.dumps(classification, indent=2) + "\n")
    with (OUT / "IBSI_display_classes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["class", "lower", "upper", "upper_inclusive", "color", "N", "share_percent", "visible_N"])
        writer.writeheader()
        for i in range(5):
            writer.writerow({"class": i + 1, "lower": edges[i], "upper": edges[i + 1], "upper_inclusive": True,
                             "color": CLASS_COLORS[i], "N": counts[i], "share_percent": counts[i] / len(values) * 100,
                             "visible_N": visible_counts[i]})
    assert all(sha(path) == expected for path, expected in consulted.items())
    manifest = {"source_project": str(PROJECT), "source_layout": "Kunming_Hazard_PGA",
                "source_project_sha256": source_hash, "source_project_saved": False,
                "draft_derivative": str(derivative), "map_crs": main_map.crs().authid(),
                "native_page_crop_mm": [0, 0, 195, 200], "native_map_size_mm": [map_width, map_height],
                "context_legend_inside_map": True,
                "IBSI_legend_location": "below map in composite",
                "legend_background": "transparent; no background shape or frame",
                "context_legend_bounds_native_mm": [11.5, 160, 61.5, 30],
                "original_extent": [old_extent.xMinimum(), old_extent.yMinimum(), old_extent.xMaximum(), old_extent.yMaximum()],
                "extent": [new_extent.xMinimum(), new_extent.yMinimum(), new_extent.xMaximum(), new_extent.yMaximum()],
                "inventory_N": 57228, "valid_IBSI_N": 41939, "invalid_IBSI_N": 15289,
                "complete_footprints_in_original_frame_N": old_inside,
                "complete_footprints_in_draft_frame_N": old_inside,
                "footprints_intersecting_frame_N": intersects_count,
                "valid_IBSI_footprints_intersecting_frame_N": visible_valid,
                "invalid_IBSI_footprints_intersecting_frame_N": intersects_count - visible_valid,
                "inventory_outside_frame_N": 57228 - intersects_count,
                "valid_IBSI_outside_frame_N": 41939 - visible_valid,
                "frame_extent_and_scale_identical_to_source": True,
                "map_fit": "Exact existing QGIS extent, scale, map size and frame, as explicitly requested; contextual layers and footprints clipped normally at this same frame; histogram cohort unchanged",
                "building_source": str(SOURCE), "building_color_expression": expression,
                "color_range": [0, values[-1]], "display_classification": classification,
                "context_styles_reused": [layer.name() for layer in active if layer.id() != building.id()],
                "native_labels": label_report,
                "protected_sources_sha256": consulted, "protected_sources_unchanged": True,
                "model_run": False, "model_or_manuscript_modified": False}
    (OUT / "native_QGIS_map_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"derivative": str(derivative), "source_map_frame_reused_exactly": True,
                      "intersecting_footprints": intersects_count, "visible_valid_IBSI": visible_valid,
                      "protected_sources_unchanged": True}), flush=True)
    # Avoid QGIS/Qt teardown ownership issues after all writes and checks finish.
    os._exit(0)


if __name__ == "__main__":
    main()
