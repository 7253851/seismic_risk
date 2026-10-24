# -*- coding: utf-8 -*-
"""Build an independent TSX velocity map from the saved hazard layout style.

CLI: run_pyqgis.sh build_tsx_deformation_layout.py [--extent hazard|full]
Also runnable from the QGIS Python editor; the current GUI project is not changed.
The numerical inputs and hazard project are read only; the TIFF default QML is synced.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import numpy as np

from qgis.core import (
    Qgis, QgsApplication, QgsColorRampShader, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFillSymbol, QgsLayerTreeModel, QgsLayoutExporter, QgsLayoutItem,
    QgsLayoutItemLabel, QgsLayoutItemMap, QgsLayoutItemPage, QgsLayoutItemPicture,
    QgsLayoutItemPolyline, QgsLayoutItemScaleBar, QgsLayoutMeasurement,
    QgsLayoutPoint, QgsLayoutSize, QgsLineSymbol, QgsMapLayerStyle,
    QgsMapThemeCollection, QgsProject, QgsRasterBandStats, QgsRasterLayer,
    QgsReadWriteContext, QgsPathResolver, QgsRectangle, QgsReferencedRectangle, QgsRasterShader,
    QgsSingleBandPseudoColorRenderer, QgsSingleSymbolRenderer, QgsTextBufferSettings, QgsTextFormat,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt, QPointF, QDateTime
from qgis.PyQt.QtGui import QColor, QFont, QPolygonF

ROOT = Path(__file__).resolve().parents[3]
SOURCE_PROJECT = ROOT / "04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz"
STUDY_SCRIPT = ROOT / "01_study_area/qgis/layouts/study_area/build_layout.py"
STUDY_PROJECT = ROOT / "01_study_area/qgis/projects/01_study_area.qgz"
RASTER = ROOT / "../data/TSX_PS/TSX_merged_v_vertical_20m.tif"
LAYOUT_DIR = ROOT / "06_insar_deformation/qgis/layouts/tsx_deformation"
EXPORT_DIR = ROOT / "06_insar_deformation/output/qgis/tsx_deformation"
OUTPUT_PROJECT = ROOT / "06_insar_deformation/qgis/projects/06_insar_deformation.qgz"
NAME = "Kunming_TSX_Vertical_Deformation"
EXPORT_DPI = 1200
BACKGROUND = "#FFFFFF"
STABLE_LOW, STABLE_HIGH = -4.5, 4.5
RATE_COLORS = {"subsidence": "#B2182B", "stable": "#8AC65A", "uplift": "#18558C"}
GRADIENT_NODES = [
    (-18.0, "#B2182B"), (-12.0, "#E34A33"), (-6.0, "#ECD6A8"),
    (-3.0, "#C8E6AE"), (0.0, "#8AC65A"), (3.0, "#C5E4B5"),
    (6.0, "#92C7DC"), (12.0, "#4C91BF"), (18.0, "#18558C"),
]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def print_png(exporter, path, dpi):
    # QImage saving avoids GDAL's unsupported PNG update/georeference operation.
    image = exporter.renderPageToImage(0, dpi=dpi)
    if image.isNull():
        raise RuntimeError("Layout rendered an empty image.")
    image.setDotsPerMeterX(round(dpi / .0254))
    image.setDotsPerMeterY(round(dpi / .0254))
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save {path}")


def export_layout_files(layout):
    layout.refresh()
    exporter = QgsLayoutExporter(layout)
    preview = EXPORT_DIR / f"{NAME}_preview.png"
    print_png(exporter, preview, 180)
    png = EXPORT_DIR / f"{NAME}_{EXPORT_DPI}dpi.png"
    print_png(exporter, png, EXPORT_DPI)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = EXPORT_DPI
    settings.forceVectorOutput = True
    settings.rasterizeWholeImage = False
    settings.simplifyGeometries = False
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    settings.appendGeoreference = False
    pdf = EXPORT_DIR / f"{NAME}.pdf"
    assert exporter.exportToPdf(str(pdf), settings) == QgsLayoutExporter.Success
    return preview, png, pdf


def style_xml(layer):
    style = QgsMapLayerStyle()
    style.readFromLayer(layer)
    return style.xmlData()


def context_style_hash(layer):
    """Compare saved styles without project-specific attribute-table relations."""
    root = ET.fromstring(style_xml(layer))
    for parent in root.iter():
        for child in list(parent):
            if child.tag in ("referencedLayers", "referencingLayers"):
                parent.remove(child)
    canonical = ET.canonicalize(ET.tostring(root, encoding="unicode"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def text_format(size, bold=True, color="#24282B", halo=False):
    font = QFont("Arial")
    font.setPointSizeF(size)
    font.setBold(bold)
    fmt = QgsTextFormat()
    fmt.setFont(font)
    fmt.setSize(size)
    fmt.setColor(QColor(color))
    if halo:
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(.4)
        buffer.setColor(QColor("white"))
        fmt.setBuffer(buffer)
    return fmt


def label(layout, name, text, box, size=9, center=False, bold=True, halo=False):
    item = QgsLayoutItemLabel(layout)
    item.setId(name)
    item.setText(text)
    item.setTextFormat(text_format(size, bold=bold, halo=halo))
    item.setMargin(0)
    item.setHAlign(Qt.AlignHCenter if center else Qt.AlignLeft)
    item.setVAlign(Qt.AlignVCenter)
    item.setBackgroundEnabled(False)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(*box[:2]))
    item.attemptResize(QgsLayoutSize(*box[2:]))
    item.setZValue(8)
    return item


def line_key(layout, name, x, y, width, color):
    item = QgsLayoutItemPolyline(QPolygonF([QPointF(0, 0), QPointF(8.5, 0)]), layout)
    item.setId(name)
    item.setSymbol(QgsLineSymbol.createSimple({
        "line_color": color, "line_width": str(width), "capstyle": "round",
    }))
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y))
    item.setZValue(7)


def find_layer(project, key):
    base_key = {"earthquakes": "earthquakes_local"}.get(key, key)
    for layer in project.mapLayers().values():
        if (layer.customProperty("seismic_building/base_key", "") == base_key
                or layer.customProperty("seismic_building/print_base", "") == key
                or (key == "event_2026" and layer.customProperty("seismic_building/validation_role", "") == "epicenter")):
            if not layer.isValid():
                raise RuntimeError(f"Invalid context layer: {key}")
            return layer
    raise RuntimeError(f"Missing context layer: {key}")


def velocity_renderer(raster):
    """Continuous red-leaf-green-blue interpolation over the stable interval."""
    ramp = QgsColorRampShader(-18, 18)
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    ramp.setClassificationMode(QgsColorRampShader.Continuous)
    ramp.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(value, QColor(colour), f"{value:g}")
        for value, colour in GRADIENT_NODES
    ])
    ramp.setClip(False)
    shader = QgsRasterShader(-18, 18)
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(raster.dataProvider(), 1, shader)
    renderer.setClassificationMin(-18)
    renderer.setClassificationMax(18)
    raster.setRenderer(renderer)
    for value, colour in GRADIENT_NODES:
        ok, r, g, b, a = ramp.shade(value)
        assert ok and QColor(r, g, b, a).name() == QColor(colour).name()
    for value in np.linspace(STABLE_LOW, STABLE_HIGH, 5):
        ok, r, g, b, a = ramp.shade(value)
        assert ok and g >= r and g >= b


def study_point_overlays(project, contexts, input_hashes):
    """Reuse the study map's selected catalog, triangle renderer and GNSS helpers."""
    spec = importlib.util.spec_from_file_location("study_point_reference", STUDY_SCRIPT)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    reference = QgsProject()
    if not reference.read(str(STUDY_PROJECT)):
        raise RuntimeError("Could not read the study-area point reference project.")
    map_ = reference.layoutManager().layoutByName(helpers.NAME).itemById("C_Study_Area")
    point_info = {}
    for key in ("earthquakes", "event_2026"):
        original = next(l for l in map_.layers()
                        if l.customProperty("study_area/source_key", "") == key)
        layer = original.clone()
        if original.id() in map_.layerStyleOverrides():
            QgsMapLayerStyle(map_.layerStyleOverrides()[original.id()]).writeToLayer(layer)
        if not layer.isValid():
            raise RuntimeError(f"Invalid study-area point layer: {key}")
        layer.setLabelsEnabled(False)
        layer.setScaleBasedVisibility(False)
        layer.setCustomProperty("seismic_building/print_base", key)
        project.addMapLayer(layer, False)
        contexts[key] = layer
        filename = Path(layer.source().split("|")[0])
        for source in filename.parent.glob(filename.stem + ".*"):
            if source.is_file():
                input_hashes[str(source)] = digest(source)
        point_info[key] = {"source": layer.source(), "feature_count": layer.featureCount(),
                           "subset": layer.subsetString(), "symbol": "red triangle with white casing"}
    # The study map stores GNSS as a geographic layout anchor and vector SVG,
    # not as an independent observation dataset. Copy its SVGs locally.
    for name in ("EARTHQUAKE_TRIANGLE_SVG", "GNSS_STAR_SVG"):
        source = Path(getattr(helpers, name))
        input_hashes[str(source)] = digest(source)
        local = LAYOUT_DIR / source.name
        shutil.copy2(source, local)
        setattr(helpers, name, local)
    input_hashes[str(STUDY_SCRIPT)] = digest(STUDY_SCRIPT)
    input_hashes[str(STUDY_PROJECT)] = digest(STUDY_PROJECT)
    return helpers, point_info


def point_annotations(layout, project, main, contexts, helpers):
    events = helpers.event_annotations(layout, project, main, contexts)
    # The hazard viewport is shorter than the study map. Lift the 2023 callout
    # clear of the retained Xishan label and reconnect it to the same epicenter.
    event = next(e for e in events if e["id"] == "event_2023_label")
    item = layout.itemById(event["id"])
    box = list(event["label_box_mm"])
    box[1] -= 8
    item.attemptMove(QgsLayoutPoint(*box[:2]))
    anchor = helpers.map_position(project, main, event["longitude"], event["latitude"])
    vx, vy = box[0] + box[2]/2 - anchor[0], box[1] + box[3]/2 - anchor[1]
    distance = math.hypot(vx, vy)
    t_enter = max(1-(box[2]/2)/abs(vx) if vx else 0,
                  1-(box[3]/2)/abs(vy) if vy else 0)
    start = (anchor[0]+vx/distance*2.7, anchor[1]+vy/distance*2.7)
    end = (anchor[0]+vx*t_enter, anchor[1]+vy*t_enter)
    layout.removeLayoutItem(layout.itemById(event["id"]+"_leader"))
    leader = helpers.polyline(layout, event["id"]+"_leader", [start,end], helpers.line(helpers.RED,.30))
    leader.setZValue(22)
    event["label_box_mm"] = box
    event["leader_line"].update(start_mm=list(start), end_mm=list(end))
    station = helpers.add_gnss_station(layout, project, main, "GNSS_station", size_mm=7.0)
    station["label"] = helpers.gnss_annotation(layout, project, main)
    left, bottom = main.pos().x(), main.pos().y() + main.sizeWithUnits().height()
    # One triangle key covers the two events; the star is reserved for GNSS.
    for key, svg, text, y in [
        ("Historical_earthquakes", helpers.EARTHQUAKE_TRIANGLE_SVG, "Earthquakes", bottom-32),
        ("GNSS", helpers.GNSS_STAR_SVG, "GNSS station", bottom-26.5),
    ]:
        helpers.layout_point_icon(layout, key+"_legend_symbol", svg, left+2.5, y-1.35, size=4.8)
        label(layout, key+"_legend_label", text, (left+13, y, 40, 5), 9, halo=True)
    return {"earthquake_annotations": events, "gnss_station": station}


def colourbar(layout, raster, unit_label, main):
    """Continuous SVG gradient using the exact raster renderer's colour nodes."""
    renderer = raster.renderer()
    if renderer.type() != "singlebandpseudocolor":
        raise RuntimeError("The TIFF needs its existing same-name pseudocolour QML.")
    shader = renderer.shader().rasterShaderFunction()
    stops = shader.colorRampItemList()
    low, high = renderer.classificationMin(), renderer.classificationMax()
    if not low < 0 < high:
        raise RuntimeError("Expected a signed velocity colour ramp containing zero.")
    assert shader.colorRampType() == QgsColorRampShader.Interpolated
    svg_stops = ''.join(
        f'<stop offset="{(stop.value-low)/(high-low):.12f}" stop-color="{stop.color.name()}"/>'
        for stop in stops
    )
    svg = LAYOUT_DIR / "velocity_colourbar.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="172mm" height="3.5mm" '
        'viewBox="0 0 172 3.5"><defs><linearGradient id="velocity" x1="0%" y1="0%" '
        'x2="100%" y2="0%">' + svg_stops + '</linearGradient></defs>'
        '<rect x="0.1" y="0.1" width="171.8" height="3.3" fill="url(#velocity)" '
        'stroke="#333638" stroke-width="0.15"/></svg>\n'
    )
    left, bottom = main.pos().x(), main.pos().y() + main.sizeWithUnits().height()
    bar_x, bar_y, bar_width = left + 4, bottom + 2, 172
    picture = QgsLayoutItemPicture(layout)
    picture.setId("Velocity_Colourbar")
    picture.setBackgroundEnabled(False)
    # Qt's SVG intrinsic pixel dimensions can alter the aspect ratio in Zoom mode.
    # Stretch makes the gradient endpoints coincide with the numeric tick positions.
    picture.setResizeMode(QgsLayoutItemPicture.Stretch)
    layout.addLayoutItem(picture)
    picture.attemptMove(QgsLayoutPoint(bar_x, bar_y))
    picture.attemptResize(QgsLayoutSize(bar_width, 3.5))
    picture.setPicturePath(str(svg))
    picture.attemptResize(QgsLayoutSize(bar_width, 3.5))
    picture.setZValue(7)
    visible_unit = unit_label if unit_label and unit_label != "source units" else ""
    title = "Vertical deformation rate" + (f" ({visible_unit})" if visible_unit else "")
    label(layout, "Velocity_Legend_Title", title,
          (left, bottom + 11, main.sizeWithUnits().width(), 5.5), 10.5, center=True)
    ticks = [stop.value for stop in stops]
    for index, value in enumerate(ticks):
        x = bar_x + (value - low) / (high - low) * bar_width
        label(layout, f"Velocity_Tick_{index}", f"{value:g}",
              (x - 4.5, bar_y + 3.7, 9, 4.5), 9, center=True)
    return {"minimum": low, "maximum": high, "ticks": ticks,
            "renderer": "Interpolated", "continuous_gradient": True,
            "visible_unit_label": visible_unit, "footer_removed": True,
            "qualitative_captions_removed": True, "legend_title": title,
            "legend_title_position": "centered below colourbar",
            "bar_width_mm": bar_width,
            "stops": [["Infinity" if math.isinf(s.value) else s.value, s.color.name()] for s in stops],
            "classes": [
                {"label": "Subsidence", "expression": f"v_vertical < {STABLE_LOW:g}", "color": RATE_COLORS["subsidence"]},
                {"label": "Stable", "expression": f"{STABLE_LOW:g} <= v_vertical <= {STABLE_HIGH:g}", "color": RATE_COLORS["stable"]},
                {"label": "Uplift", "expression": f"v_vertical > {STABLE_HIGH:g}", "color": RATE_COLORS["uplift"]},
            ], "stable_interval_inclusive": [STABLE_LOW, STABLE_HIGH], "unit_label": unit_label,
            "sign_interpretation": "Subsidence negative; uplift positive, as requested by user"}


def build(extent_mode="hazard", unit_label="mm/y"):
    stamp = datetime.now(ZoneInfo("Asia/Shanghai"))
    record = ROOT / "history/changes" / (
        stamp.strftime("%Y-%m-%d_%H%M%S") + "_tsx_deformation_layout"
    )
    record.mkdir(parents=True)
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(__file__, record / Path(__file__).name)
    # Only previous outputs from this independent map are backed up on reruns.
    previous_outputs = [OUTPUT_PROJECT, RASTER.with_suffix(".qml"), *LAYOUT_DIR.glob("*"), *EXPORT_DIR.glob("*")]
    for path in previous_outputs:
        if path.is_file():
            target = record / "previous_outputs" / path.resolve().relative_to(ROOT.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    default_qml_before = digest(RASTER.with_suffix(".qml"))
    input_hashes = {str(p): digest(p) for p in [SOURCE_PROJECT, RASTER]}
    project = QgsProject()
    if not project.read(str(SOURCE_PROJECT)):
        raise RuntimeError("Could not read the saved hazard project.")
    layout = project.layoutManager().layoutByName("Kunming_Hazard_PGA")
    if not layout:
        raise RuntimeError("The source hazard layout was not found.")
    main = layout.itemById("Hazard_Main_Map")
    if not isinstance(main, QgsLayoutItemMap):
        raise RuntimeError("The source hazard map was not found.")
    original_extent = QgsRectangle(main.extent())
    original_box = [main.pos().x(), main.pos().y(), main.sizeWithUnits().width(), main.sizeWithUnits().height()]
    original_background = main.backgroundColor()
    original_layer_order = [layer.id() for layer in main.layers()]
    contexts = {key: find_layer(project, key) for key in [
        "districts", "dianchi", "faults", "roads", "waterways", "hillshade", "earthquakes", "event_2026",
    ]}
    for layer in contexts.values():
        path = Path(layer.source().split("|")[0])
        siblings = [path] if path.suffix != ".shp" else list(path.parent.glob(path.stem + ".*"))
        for source in siblings:
            if source.is_file():
                input_hashes[str(source)] = digest(source)
    overrides = main.layerStyleOverrides()
    for layer in contexts.values():
        if layer.id() in overrides:
            style = QgsMapLayerStyle(overrides[layer.id()])
            style.writeToLayer(layer)
        if isinstance(layer, QgsVectorLayer):
            layer.setLabelsEnabled(False)
    source_style_hashes = {key: context_style_hash(layer)
                           for key, layer in contexts.items()
                           if key not in ("earthquakes", "event_2026")}
    point_helpers, point_sources = study_point_overlays(project, contexts, input_hashes)
    rate = QgsRasterLayer(str(RASTER), "TSX vertical deformation rate · 20 m", "gdal")
    if not rate.isValid() or rate.crs().authid() != "EPSG:4543":
        raise RuntimeError("Invalid TSX velocity TIFF or CRS.")
    velocity_renderer(rate)
    message, ok = rate.saveNamedStyle(str(RASTER.with_suffix(".qml")))
    if not ok:
        raise RuntimeError(message)
    rate.setCustomProperty("seismic_building/deformation_role", "vertical_rate")
    rate.setCustomProperty("seismic_building/deformation_unit_label", unit_label)
    project.addMapLayer(rate, False)
    keep = {l.id() for l in contexts.values()} | {rate.id()}
    for other in list(project.layoutManager().layouts()):
        if other is not layout:
            project.layoutManager().removeLayout(other)
    # Keep the hazard background annotations/fault keys; use study-map point keys.
    for item in list(layout.items()):
        if isinstance(item, QgsLayoutItem) and item.id().startswith((
                "Legend_", "Historical_event_", "Event_2026_annotation", "Leader_Historical_event_",
                "Leader_Event_2026_annotation", "Historical_eq_legend_", "Event_2026_legend_")):
            layout.removeLayoutItem(item)
    for theme in project.mapThemeCollection().mapThemes():
        project.mapThemeCollection().removeMapTheme(theme)
    project.removeMapLayers([lid for lid in project.mapLayers() if lid not in keep])
    # Reuse saved hazard context styles, with district outlines above velocity.
    ordered = [contexts["event_2026"], contexts["earthquakes"], contexts["faults"],
               contexts["dianchi"], contexts["districts"], rate,
               contexts["waterways"], contexts["roads"], contexts["hillshade"]]
    assert ordered.index(contexts["districts"]) < ordered.index(rate)
    assert ordered[-1] is contexts["hillshade"]
    assert source_style_hashes == {key: context_style_hash(layer)
                                   for key, layer in contexts.items() if key in source_style_hashes}
    bridge = project.layerTreeRegistryBridge()
    bridge.setEnabled(False)
    root = project.layerTreeRoot()
    root.removeAllChildren()
    overlay_group = root.addGroup("01_上覆基础要素 · 危险性原样式")
    for layer in ordered[:5]:
        overlay_group.addLayer(layer)
    root.addGroup("02_形变速率").addLayer(rate)
    bottom_group = root.addGroup("03_底层基础要素 · 河流道路与地形")
    for layer in ordered[6:]:
        bottom_group.addLayer(layer)
    bridge.setEnabled(True)
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(ordered)
    for node in root.findLayers():
        node.setItemVisibilityChecked(True)
    crs = QgsCoordinateReferenceSystem("EPSG:4543")
    project.setCrs(crs)
    project.setBackgroundColor(original_background)
    main.setId("Deformation_Main_Map")
    main.setCrs(crs)
    main.setFollowVisibilityPreset(False)
    main.setFollowVisibilityPresetName("")
    main.setLayers(ordered)
    main.setKeepLayerSet(True)
    main.setKeepLayerStyles(True)
    main.setLayerStyleOverrides({l.id(): style_xml(l) for l in ordered})
    main.setBackgroundEnabled(True)
    main.setBackgroundColor(original_background)
    main.setFrameEnabled(True)
    main.setFrameStrokeWidth(QgsLayoutMeasurement(.45))
    main.setFrameStrokeColor(QColor("#24282B"))
    if extent_mode == "full":
        extent = QgsRectangle(rate.extent())
        extent.scale(1.015)
        main.zoomToExtent(extent)
        # Keep curated district/lake labels at their original geographic anchors.
        final = main.extent()
        for name in ["Wuhua", "Panlong", "Xishan", "Guandu", "Chenggong", "Dian_Lake"]:
            item = layout.itemById(name)
            if item:
                w, h = item.sizeWithUnits().width(), item.sizeWithUnits().height()
                px, py = item.pos().x() + w/2, item.pos().y() + h/2
                x = original_extent.xMinimum() + (px-original_box[0])/original_box[2]*original_extent.width()
                y = original_extent.yMaximum() - (py-original_box[1])/original_box[3]*original_extent.height()
                item.attemptMove(QgsLayoutPoint(
                    original_box[0]+(x-final.xMinimum())/final.width()*original_box[2]-w/2,
                    original_box[1]+(final.yMaximum()-y)/final.height()*original_box[3]-h/2,
                ))
    else:
        main.zoomToExtent(original_extent)
    layout.setName(NAME)
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(195, 217))
    layout.renderContext().setDpi(EXPORT_DPI)
    layout.setReferenceMap(main)
    layout.setCustomProperty("seismic_building/layout_subject", "TSX merged v_vertical")
    layout.setCustomProperty("seismic_building/extent_mode", extent_mode)
    scale = layout.itemById("Overview_scale")
    if isinstance(scale, QgsLayoutItemScaleBar):
        scale.setId("Deformation_Scale")
        scale.setLinkedMap(main)
        scale.setUnitsPerSegment(5 if extent_mode == "full" else 2)
        scale.setTextFormat(text_format(8))
        scale.setBackgroundEnabled(False)
    arrow = layout.itemById("True_North_Arrow")
    arrow_path = LAYOUT_DIR / "north_arrow.svg"
    shutil.copy2(ROOT / "04_seismic_hazard/qgis/layouts/hazard/north_arrow.svg", arrow_path)
    arrow.setPicturePath(str(arrow_path))
    arrow.setLinkedMap(main)
    arrow.setNorthMode(QgsLayoutItemPicture.TrueNorth)
    point_report = point_annotations(layout, project, main, contexts, point_helpers)
    ramp_report = colourbar(layout, rate, unit_label, main)
    styles_dir = LAYOUT_DIR / "print_styles"
    styles_dir.mkdir(exist_ok=True)
    for key, layer in {**contexts, "vertical_rate": rate}.items():
        message, ok = layer.saveNamedStyle(str(styles_dir / f"{key}.qml"))
        if not ok:
            raise RuntimeError(message)
    theme = QgsMapThemeCollection.createThemeFromCurrentState(root, QgsLayerTreeModel(root))
    project.mapThemeCollection().insert("TSX_Deformation_Print", theme)
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(main.extent(), crs))
    project.setTitle("Kunming TSX vertical deformation rate")
    metadata = project.metadata()
    metadata.setTitle("Kunming TSX vertical deformation rate")
    metadata.setAbstract(
        "Mean v_vertical from merged TSX PS observations, aggregated to 20 m cells. "
        f"Continuous red-leaf-green-blue colour ramp; {STABLE_LOW:g} through +{STABLE_HIGH:g} is the stable "
        "interpretation interval in fresh leaf-green hues. Negative values transition toward "
        "warm red for subsidence, positive values toward cool blue for uplift. "
        f"Empty cells are NoData; no spatial interpolation. Display units: {unit_label}, "
        "as explicitly requested by the user; no numerical unit conversion. "
        "Background styles and annotations are reused from the hazard layout, with "
        "district outlines above velocity. Context: "
        "faults, earthquakes, OSM roads/waterways, the 2016 reference shoreline of "
        "Dian Lake, and the local Esri World Hillshade cache. Earthquake catalog selection, "
        "red triangle symbols, the GNSS anchor (102.8 E, 25.03 N), red star and point "
        "annotations follow the saved study-area project and its authoring code."
    )
    metadata.setCreationDateTime(QDateTime.currentDateTime())
    metadata.setIdentifier("Kunming_TSX_Vertical_Deformation")
    metadata.setParentIdentifier("")
    project.setMetadata(metadata)
    project.setFileName(str(OUTPUT_PROJECT))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(LAYOUT_DIR / f"{NAME}.qpt")))
    if not layout.saveAsTemplate(str(LAYOUT_DIR / f"{NAME}.qpt"), context):
        raise RuntimeError("Could not save the layout template.")
    preview, png, pdf = export_layout_files(layout)
    for path, before in input_hashes.items():
        if digest(path) != before:
            raise RuntimeError(f"Input changed during map creation: {path}")
    staged = OUTPUT_PROJECT.with_name(".tsx_deformation_stage.qgz")
    assert project.write(str(staged))
    staged.replace(OUTPUT_PROJECT)
    stats = rate.dataProvider().bandStatistics(1, QgsRasterBandStats.All, rate.extent(), 0)
    report = {
        "created_at": stamp.isoformat(), "source_project": str(SOURCE_PROJECT),
        "project": str(OUTPUT_PROJECT), "template": str(LAYOUT_DIR / f"{NAME}.qpt"),
        "layout": NAME, "raster": str(RASTER), "source_hashes_unchanged": input_hashes,
        "default_raster_qml": str(RASTER.with_suffix(".qml")),
        "default_raster_qml_before_sha256": default_qml_before,
        "default_raster_qml_after_sha256": digest(RASTER.with_suffix(".qml")),
        "default_raster_qml_synced_to_user_classes": True,
        "extent_mode": extent_mode, "original_hazard_extent": original_extent.toString(),
        "final_extent": main.extent().toString(), "page_mm": [195, 217], "map_box_mm": original_box,
        "crs": crs.authid(), "raster_cell_size_m": [rate.rasterUnitsPerPixelX(), rate.rasterUnitsPerPixelY()],
        "raster_minimum": stats.minimumValue, "raster_maximum": stats.maximumValue,
        "raster_valid_cells": int(stats.elementCount), "raster_nodata": rate.dataProvider().sourceNoDataValue(1),
        "colourbar": ramp_report, "map_theme": "TSX_Deformation_Print",
        "point_reference_script": str(STUDY_SCRIPT), "point_reference_project": str(STUDY_PROJECT),
        "point_sources": point_sources, "point_overlays": point_report,
        "locked_layers": [l.name() for l in main.layers()],
        "locked_layer_ids": [l.id() for l in main.layers()],
        "original_hazard_layer_order": original_layer_order,
        "context_style_hashes_from_hazard": source_style_hashes,
        "background_context_styles_reused_without_changes": True,
        "point_styles_from_study_area": True,
        "district_boundaries_below_velocity_and_other_vector_context": False,
        "district_boundaries_above_velocity": True,
        "district_layer_index": ordered.index(contexts["districts"]),
        "velocity_layer_index": ordered.index(rate),
        "hillshade_layer_index": ordered.index(contexts["hillshade"]),
        "layers_locked": main.keepLayerSet(), "styles_locked": main.keepLayerStyles(),
        "follows_theme": main.followVisibilityPreset(), "old_PGA_content_removed": True,
        "existing_hazard_project_modified": False, "input_data_modified": False,
        "preview": str(preview), "png_1200dpi": str(png), "pdf": str(pdf),
        "export_dpi": EXPORT_DPI,
        "pdf_whole_page_rasterized": False, "pdf_context_vectors": True,
        "history": str(record),
    }
    dump(EXPORT_DIR / "layout_report.json", report)
    dump(record / "layout_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report


def export_saved():
    """Change only the saved map's export resolution, retaining its current design."""
    stamp = datetime.now(ZoneInfo("Asia/Shanghai"))
    record = Path(os.environ.get("TSX_EXPORT_RECORD", str(ROOT / "history/changes" /
                  (stamp.strftime("%Y-%m-%d_%H%M%S") + "_tsx_deformation_export"))))
    record.mkdir(parents=True, exist_ok=True)
    shutil.copy2(__file__, record / Path(__file__).name)
    for path in [OUTPUT_PROJECT, *LAYOUT_DIR.glob("*"), *EXPORT_DIR.glob("*")]:
        if path.is_file():
            target = record / "previous_outputs" / path.resolve().relative_to(ROOT.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
    previous = json.loads((EXPORT_DIR / "layout_report.json").read_text())
    before_project = digest(OUTPUT_PROJECT)
    project = QgsProject()
    assert project.read(str(OUTPUT_PROJECT))
    layout = project.layoutManager().layoutByName(NAME)
    assert layout and all(layer.isValid() for layer in project.mapLayers().values())
    main = layout.itemById("Deformation_Main_Map")
    before_extent = main.extent().toString(12)
    before_styles = dict(main.layerStyleOverrides())
    before_ids = [layer.id() for layer in main.layers()]
    inputs = {}
    for layer in main.layers():
        path = Path(layer.source().split("|")[0])
        files = path.parent.glob(path.stem+".*") if path.suffix == ".shp" else [path]
        for file in files:
            if file.is_file():
                inputs[str(file)] = digest(file)
    for asset in LAYOUT_DIR.glob("*.svg"):
        inputs[str(asset)] = digest(asset)
    layout.renderContext().setDpi(EXPORT_DPI)
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(LAYOUT_DIR / f"{NAME}.qpt")))
    assert layout.saveAsTemplate(str(LAYOUT_DIR / f"{NAME}.qpt"), context)
    preview, png, pdf = export_layout_files(layout)
    assert main.extent().toString(12) == before_extent
    assert main.layerStyleOverrides() == before_styles
    assert [layer.id() for layer in main.layers()] == before_ids
    for path, expected in inputs.items():
        assert digest(path) == expected, f"Input changed while exporting: {path}"
    assert digest(OUTPUT_PROJECT) == before_project, "Saved project changed concurrently."
    staged = OUTPUT_PROJECT.with_name(".tsx_deformation_export_stage.qgz")
    assert project.write(str(staged))
    staged.replace(OUTPUT_PROJECT)
    previous.pop("png_600dpi", None)
    previous.update(created_at=stamp.isoformat(), history=str(record),
                    export_dpi=EXPORT_DPI, png_1200dpi=str(png), pdf=str(pdf), preview=str(preview),
                    layout_export_only=True, saved_layout_appearance_unchanged=True,
                    source_hashes_unchanged=inputs, project_before_sha256=before_project,
                    previous_layout_report=str(record / "previous_outputs/mapping/exports/tsx_deformation/layout_report.json"))
    dump(EXPORT_DIR / "layout_report.json", previous)
    dump(record / "layout_report.json", previous)
    # The old current PNG has already been archived above.
    (EXPORT_DIR / f"{NAME}_600dpi.png").unlink(missing_ok=True)
    print(json.dumps({k: previous[k] for k in ["project", "export_dpi", "png_1200dpi", "pdf", "history"]},
                     ensure_ascii=False, indent=2), flush=True)
    return previous


if __name__ in ("__main__", "__console__"):
    gui = QgsApplication.instance() is not None
    if not gui:
        app = QgsApplication([], False)
        app.setPrefixPath("/Applications/QGIS.app/Contents/Resources/qgis", True)
        app.initQgis()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extent", choices=["hazard", "full"], default="hazard")
    parser.add_argument("--export-only", action="store_true",
                        help="Export the current saved deformation layout without rebuilding its design.")
    parser.add_argument("--unit-label", default="mm/y",
                        help="Displayed unit text only; does not convert source values.")
    args = parser.parse_args([] if gui else None)
    if args.export_only:
        export_saved()
    else:
        build(args.extent, args.unit_label)
    if not gui:
        sys.stdout.flush()
        os._exit(0)
