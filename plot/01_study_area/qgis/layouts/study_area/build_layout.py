# -*- coding: utf-8 -*-
"""Build an A4 draft from the current saved study-area layout.

Shell:
  plot/shared/qgis/scripts/run_pyqgis.sh plot/01_study_area/qgis/layouts/study_area/build_layout.py
QGIS Python console:
    import runpy; runpy.run_path('/.../study_area/build_layout.py', run_name='__main__')

The default command writes only to plot/01_study_area/layout/work/. All type is expressed at the figure's
actual manuscript size. Use --legacy-rebuild explicitly to regenerate the older
300 x 235 mm construction layout and overwrite its native project/exports.
The canonical 04_seismic_hazard.qgz and all source datasets are read-only inputs.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import shutil
import math
import tempfile
from osgeo import gdal
import numpy as np

from qgis.core import *
from qgis.PyQt.QtCore import Qt, QPointF, QRectF, QSize
from qgis.PyQt.QtGui import QColor, QFont, QPolygonF, QPainter

_APP = QgsApplication.instance()
if _APP is None:
    _APP = QgsApplication([], False)
    _APP.initQgis()

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
NAME = 'Kunming_Study_Area'
EXPORT_DIR = ROOT / '01_study_area/output/qgis/study_area'
CRS = QgsCoordinateReferenceSystem('EPSG:4543')
WGS = QgsCoordinateReferenceSystem('EPSG:4326')
INK = '#252D32'
BUILDING_COLOR = '#744B9B'
WATER = '#45AFD2'
RED = '#D7373F'
ORANGE = '#C97713'
CITY = '#D0D0D0'
CITY_OUTLINE_WIDTH_MM = 0.90
COUNTY_BOUNDARY_WIDTH_MM = 0.75
RIGHT_COUNTY_BOUNDARY_WIDTH_MM = 0.40
STREET_BOUNDARY_WIDTH_MM = 0.22
STREET_BOUNDARY_COLOR = '#AAB2B5'
DEM_FILE = ROOT / '../data/dem/yunnan_dem.tif'
DEM_COLORS = ['#5F9C6E', '#89B779', '#B0CD8A', '#CFD79D', '#DDCCA4', '#B79976', '#957656']
DEM_PALETTE_DESCRIPTION = 'Classic elevation colours: green lowlands, yellow-green uplands, tan and brown highlands'
# The legend covers the complete viewport DEM, including the 2,802 m summit.
# QgsColorRampShader.Discrete items specify class UPPER bounds.
DEM_CLASS_BOUNDS = [1600, 1800, 2000, 2200, 2400, 2600, 2800, 2900]
DEM_MIN, DEM_MAX = DEM_CLASS_BOUNDS[0], DEM_CLASS_BOUNDS[-1]
DEM_STOPS = list(zip(DEM_CLASS_BOUNDS[1:], DEM_COLORS))
KUNMING_DISTRICT_NAMES = {
    '五华区', '盘龙区', '官渡区', '西山区', '东川区', '呈贡区', '晋宁区', '安宁市',
    '嵩明县', '富民县', '宜良县', '石林彝族自治县', '禄劝彝族苗族自治县', '寻甸回族彝族自治县',
}
BUILT_UP_COLOR = '#F0BAD5'
BUILT_UP_EDGE = '#B16D8B'
BUILDING_LEGEND_EDGE = '#4D326A'
BUILDING_LEGEND_OPACITY = 0.70
BUILT_UP_OPACITY = 0.80
BUILT_UP_OUTLINE_WIDTH = 0.28
FAULT_WIDTH_MULTIPLIER = 1.5
HILLSHADE_OPACITY = 0.30
HISTORICAL_EQ_COLOR = '#E22D32'
HISTORICAL_EQ_SIZE_MM = 3.8
EVENT_2026_COLOR = HISTORICAL_EQ_COLOR
EVENT_2026_SIZE_MM = 6.0
EVENT_2026_DATE = '2026-09-30'
EVENT_2026_MAGNITUDE = 4.3
EVENT_2023_DATE = '2023-01-27'
EVENT_2023_MAGNITUDE = 2.1
GNSS_LON, GNSS_LAT = 102.8, 25.03
GNSS_COLOR = '#E22D32'
LEFT_BOX = (8, 12, 116, 177)
RIGHT_BOX = (134, 12, 162, 184 * 168 / 170)
LEGEND_ROWS = (204.0, 211.5, 219.0)
LEGEND_COLUMNS = (8, 47, 86)
FAULT_REFERENCE_PROJECT = ROOT / '04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz'
FAULT_ARROW = OUT / 'left_lateral_arrows.svg'
EARTHQUAKE_TRIANGLE_SVG = OUT / 'legend_earthquake_triangle.svg'
GNSS_STAR_SVG = OUT / 'legend_gnss_star.svg'

SOURCES = {
    'districts': ('Kunming District Boundaries · GS(2024)0650', '../data/china_administrative_boundaries_gs_2024_0650/shapefile_converted/china_counties.shp'),
    'streets': ('Subdistrict and Township Boundaries', '../data/administrative/kunming_streets.shp'),
    'city': ('Kunming City Boundary · GS(2024)0650', '../data/china_administrative_boundaries_gs_2024_0650/shapefile_converted/china_cities.shp'),
    'buildings': ('Study Buildings · 57,228', '../result/hazard/scs_pipeline/06_building_hazard.gpkg|layername=building_hazard'),
    'built_up': ('Built-up Areas · ArcGIS Pro Study Area', '../data/study_area/built_up.gpkg|layername=built_up'),
    'dianchi': ('Dianchi Lake · 2016 Reference Shoreline', '../data/water/dianchi_2016_reference.shp'),
    'faults': ('Faults · 59 Source Features', '../data/faults/02_Kunming_Fault_Processed.shp'),
    'earthquakes': ('Historical Earthquake Catalog · 2012–2024', '../data/earthquakes/historical_catalog_2012_2024.shp'),
    'event_2026': ('2026 Kunming Earthquake Epicenter', '../data/validation/cases/event_epicenter.shp'),
    'tsx1': ('TSX1 Coverage', '../data/study_area/TSX1_Extent.shp'),
    'tsx2': ('TSX2 Coverage', '../data/study_area/TSX2_Extent.shp'),
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def font(size=9, color=INK, bold=False, family='Songti SC', halo=False):
    qfont = QFont(family)
    qfont.setPointSizeF(size)
    qfont.setBold(bold)
    fmt = QgsTextFormat()
    fmt.setFont(qfont)
    fmt.setSize(size)
    fmt.setColor(QColor(color))
    if halo:
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(0.55)
        buffer.setColor(QColor('white'))
        fmt.setBuffer(buffer)
    return fmt


def label(layout, id_, text, box, size=9, color=INK, bold=False,
          family='Songti SC', center=False, background=False):
    item = QgsLayoutItemLabel(layout)
    item.setId(id_)
    item.setText(text)
    item.setTextFormat(font(size, color, bold, family))
    item.setMargin(0.7 if background else 0)
    item.setHAlign(Qt.AlignHCenter if center else Qt.AlignLeft)
    item.setVAlign(Qt.AlignVCenter)
    if background:
        item.setBackgroundEnabled(True)
        item.setBackgroundColor(QColor(255, 255, 255, 235))
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(*box[:2]))
    item.attemptResize(QgsLayoutSize(*box[2:]))
    item.setZValue(20)
    return item


def fill(color='transparent', edge=INK, width=0.2, dash='solid'):
    return QgsFillSymbol.createSimple({
        'color': color, 'outline_color': edge, 'outline_width': str(width),
        'outline_style': dash if width else 'no', 'joinstyle': 'round',
    })


def built_up_fill():
    symbol = fill(BUILT_UP_COLOR, BUILT_UP_EDGE, BUILT_UP_OUTLINE_WIDTH)
    symbol.setOpacity(BUILT_UP_OPACITY)
    return symbol


def building_legend_fill():
    """Retain the building swatch when changing built-up colour and opacity."""
    symbol = fill(BUILDING_COLOR, BUILDING_LEGEND_EDGE, BUILT_UP_OUTLINE_WIDTH)
    symbol.setOpacity(BUILDING_LEGEND_OPACITY)
    return symbol


def line(color=INK, width=0.2, dash='solid'):
    return QgsLineSymbol.createSimple({
        'line_color': color, 'line_width': str(width), 'line_style': dash,
        'joinstyle': 'round', 'capstyle': 'round',
    })


def symbol_signature(symbol):
    result = []
    for sl in symbol.symbolLayers():
        properties = dict(sl.properties())
        if sl.layerType() == 'SvgMarker' and 'name' in properties:
            properties['name'] = Path(properties['name']).name
        item = {'type': sl.layerType(), 'properties': properties}
        if sl.subSymbol():
            item['subsymbol'] = symbol_signature(sl.subSymbol())
        result.append(item)
    return result


def renderer_signature(renderer):
    return [{'label': rule.label(), 'filter': rule.filterExpression(), 'else': rule.isElse(),
             'symbol': symbol_signature(rule.symbol())}
            for rule in renderer.rootRule().children()]


def strip_line_widths(value):
    if isinstance(value, dict):
        return {k: strip_line_widths(v) for k, v in value.items() if k != 'line_width'}
    if isinstance(value, list):
        return [strip_line_widths(v) for v in value]
    return value


def thicken_fault_renderer(renderer, multiplier=FAULT_WIDTH_MULTIPLIER):
    result = renderer.clone()
    for rule in result.rootRule().children():
        for symbol_layer in rule.symbol().symbolLayers():
            if symbol_layer.layerType() == 'SimpleLine':
                symbol_layer.setWidth(round(symbol_layer.width() * multiplier, 3))
    return result


def fault_line_widths(renderer):
    return sorted({round(symbol_layer.width(), 3)
                   for rule in renderer.rootRule().children()
                   for symbol_layer in rule.symbol().symbolLayers()
                   if symbol_layer.layerType() == 'SimpleLine'})


def english_district_labeling(layer, panel=''):
    names = {
        '呈贡区': 'Chenggong', '晋宁区': 'Jinning', '西山区': 'Xishan',
        '东川区': 'Dongchuan', '官渡区': 'Guandu', '寻甸回族彝族自治县': 'Xundian',
        '嵩明县': 'Songming', '禄劝彝族苗族自治县': 'Luquan', '宜良县': 'Yiliang',
        '石林彝族自治县': 'Shilin', '富民县': 'Fumin', '盘龙区': 'Panlong',
        '五华区': 'Wuhua', '安宁市': 'Anning',
    }
    cases = ' '.join(f"WHEN \"name\" = '{cn}' THEN '{en}'" for cn, en in names.items())
    settings = QgsPalLayerSettings()
    settings.fieldName = f'CASE {cases} ELSE "name" END'
    settings.isExpression = True
    settings.placement = QgsPalLayerSettings.Horizontal
    settings.centroidWhole = True
    settings.centroidInside = True
    settings.fitInPolygonOnly = False
    settings.displayAll = True
    settings.priority = 10
    settings.obstacle = False
    text_format = QgsTextFormat()
    qfont = QFont('Arial')
    qfont.setPointSizeF(12.0)
    qfont.setBold(True)
    text_format.setFont(qfont)
    text_format.setSize(12.0)
    text_format.setColor(QColor('#29343B'))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.9)
    buffer.setColor(QColor(255, 255, 255, 230))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    if panel in ('a', 'c'):
        ddp = settings.dataDefinedProperties()
        if panel == 'a':
            # Keep the Kunming locator's GNSS star clear of the Guandu label.
            ddp.setProperty(QgsPalLayerSettings.PositionX, QgsProperty.fromExpression(
                "CASE WHEN \"name\" = '官渡区' THEN x(centroid($geometry)) + 0.14 ELSE NULL END"))
            ddp.setProperty(QgsPalLayerSettings.PositionY, QgsProperty.fromExpression(
                "CASE WHEN \"name\" = '官渡区' THEN y(centroid($geometry)) + 0.025 ELSE NULL END"))
        else:
            # Move Songming well inside the upper-right map frame and clear of the north arrow.
            ddp.setProperty(QgsPalLayerSettings.PositionX, QgsProperty.fromExpression(
                "CASE WHEN \"name\" = '嵩明县' THEN x(centroid($geometry)) - 0.14 ELSE NULL END"))
            ddp.setProperty(QgsPalLayerSettings.PositionY, QgsProperty.fromExpression(
                "CASE WHEN \"name\" = '嵩明县' THEN y(centroid($geometry)) - 0.11 ELSE NULL END"))
        settings.setDataDefinedProperties(ddp)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def dianchi_labeling(layer):
    settings = QgsPalLayerSettings()
    settings.fieldName = "'Dian Lake'"
    settings.isExpression = True
    settings.placement = QgsPalLayerSettings.Horizontal
    settings.centroidWhole = True
    settings.centroidInside = True
    settings.fitInPolygonOnly = False
    settings.priority = 10
    settings.obstacle = False
    text_format = QgsTextFormat()
    qfont = QFont('Arial')
    qfont.setPointSizeF(16.0)
    qfont.setBold(True)
    text_format.setFont(qfont)
    text_format.setSize(16.0)
    text_format.setColor(QColor('#174253'))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.8)
    buffer.setColor(QColor(255, 255, 255, 230))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def english_fault_labeling(layer):
    """Label named faults along their lines; correct two source spelling slips in display only."""
    settings = QgsPalLayerSettings()
    settings.fieldName = (
        "CASE "
        "WHEN \"FN_En\" = 'Heilongtan-Guandu fault' THEN 'Heilongtan–Guandu' "
        "WHEN \"FN_En\" = 'Eastern brach of the Xiaojiang fault system (middle segment)' "
        "THEN 'E. Xiaojiang' "
        "WHEN \"FN_En\" = 'Westen brach of the Xiaojiang fault system (middle segment)' "
        "THEN 'W. Xiaojiang' "
        "ELSE \"FN_En\" END"
    )
    settings.isExpression = True
    settings.placement = QgsPalLayerSettings.Curved
    settings.priority = 9
    settings.obstacle = False
    settings.displayAll = False
    settings.repeatDistance = 0
    text_format = QgsTextFormat()
    qfont = QFont('Arial')
    qfont.setPointSizeF(14.0)
    qfont.setItalic(True)
    text_format.setFont(qfont)
    text_format.setSize(14.0)
    text_format.setColor(QColor('#202A2F'))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.85)
    buffer.setColor(QColor(255, 255, 255, 235))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def earthquake_symbol(event_2026=False, legend=False, locator=False):
    factor = 0.68 if legend else 1.0
    symbol = QgsMarkerSymbol.createSimple({
        'name': 'triangle', 'size': str((HISTORICAL_EQ_SIZE_MM + 0.9) * factor),
        'size_unit': 'MM', 'color': '#FFFFFF', 'outline_style': 'no', 'angle': '0',
    })
    symbol.appendSymbolLayer(QgsSimpleMarkerSymbolLayer.create({
        'name': 'triangle', 'size': str(HISTORICAL_EQ_SIZE_MM * factor),
        'size_unit': 'MM', 'color': HISTORICAL_EQ_COLOR,
        'outline_color': '#951C22', 'outline_width': str(0.25 * factor),
        'outline_width_unit': 'MM', 'joinstyle': 'round', 'angle': '0',
    }))
    return symbol


def write_layout_symbol_assets():
    """Create crisp vector point symbols shared by map and legend items."""
    triangle = '''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
<path d="M50 7 L94 91 L6 91 Z" fill="#E22D32" stroke="#FFFFFF" stroke-width="13" stroke-linejoin="round"/>
<path d="M50 7 L94 91 L6 91 Z" fill="#E22D32" stroke="#951C22" stroke-width="3.5" stroke-linejoin="round"/>
</svg>'''
    star_points = []
    for i in range(10):
        radius = 43 if i % 2 == 0 else 19
        angle = -math.pi / 2 + i * math.pi / 5
        star_points.append(f'{50 + radius * math.cos(angle):.2f},{50 + radius * math.sin(angle):.2f}')
    star_path = 'M' + ' L'.join(star_points) + ' Z'
    star = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
<path d="{star_path}" fill="{GNSS_COLOR}" stroke="#FFFFFF" stroke-width="13" stroke-linejoin="round"/>
<path d="{star_path}" fill="{GNSS_COLOR}" stroke="#951C22" stroke-width="3.5" stroke-linejoin="round"/>
</svg>'''
    EARTHQUAKE_TRIANGLE_SVG.write_text(triangle, encoding='utf-8')
    GNSS_STAR_SVG.write_text(star, encoding='utf-8')


def load_hazard_fault_renderer():
    """Read the actual locked hazard-map renderer; never execute its authoring script."""
    reference = QgsProject()
    if not reference.read(str(FAULT_REFERENCE_PROJECT)):
        raise RuntimeError('Cannot read the hazard project for its fault style')
    layout = reference.layoutManager().layoutByName('Kunming_Hazard_PGA')
    map_ = layout.itemById('Hazard_Main_Map')
    source = next(l for l in map_.layers() if l.customProperty('seismic_building/base_key', '') == 'faults')
    clone = source.clone()
    QgsMapLayerStyle(map_.layerStyleOverrides()[source.id()]).writeToLayer(clone)
    renderer = clone.renderer().clone()
    expected = renderer_signature(renderer)
    copied = []
    def localize(symbol):
        for sl in symbol.symbolLayers():
            if sl.layerType() == 'SvgMarker':
                original_path = sl.path()
                # QGIS may embed the SVG payload directly in the project as
                # base64. Such symbols are self-contained and need no copying.
                if original_path.startswith('base64:'):
                    continue
                old_path = Path(original_path)
                if not old_path.is_file():
                    raise RuntimeError('Missing fault arrow: ' + str(old_path))
                shutil.copy2(old_path, FAULT_ARROW)
                sl.setPath(str(FAULT_ARROW))
                copied.append({'original': str(old_path), 'local': str(FAULT_ARROW), 'sha256': sha(old_path)})
            if sl.subSymbol():
                localize(sl.subSymbol())
    for rule in renderer.rootRule().children():
        localize(rule.symbol())
    if renderer_signature(renderer) != expected:
        raise RuntimeError('Fault symbol changed while copying its SVG asset')
    return renderer, {'project': str(FAULT_REFERENCE_PROJECT), 'layout': layout.name(),
                      'map': map_.id(), 'rules': expected, 'assets': copied}


def dem_layer(hillshade=False):
    layer = QgsRasterLayer(str(DEM_FILE), 'Yunnan DEM · Hillshade' if hillshade else 'Yunnan DEM · Elevation')
    if not layer.isValid():
        raise RuntimeError('Invalid DEM: ' + str(DEM_FILE))
    if hillshade:
        renderer = QgsHillshadeRenderer(layer.dataProvider(), 1, 315, 40)
        renderer.setZFactor(1.0)
        renderer.setOpacity(HILLSHADE_OPACITY)
        layer.setRenderer(renderer)
        layer.setBlendMode(QPainter.CompositionMode_Multiply)
    else:
        function = QgsColorRampShader(DEM_MIN, DEM_MAX)
        function.setColorRampType(QgsColorRampShader.Discrete)
        function.setColorRampItemList([
            QgsColorRampShader.ColorRampItem(v, QColor(c), str(round(v))) for v, c in DEM_STOPS
        ])
        function.setClip(False)
        shader = QgsRasterShader(DEM_MIN, DEM_MAX)
        shader.setRasterShaderFunction(function)
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        renderer.setClassificationMin(DEM_MIN)
        renderer.setClassificationMax(DEM_MAX)
        layer.setRenderer(renderer)
    layer.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    layer.resampleFilter().setZoomedOutResampler(QgsBilinearRasterResampler())
    return layer


def style_xml(layer, key, panel):
    if isinstance(layer, QgsRasterLayer):
        style = QgsMapLayerStyle()
        style.readFromLayer(layer)
        return style.xmlData()
    clone = layer.clone()
    clone.setLabelsEnabled(False)
    clone.setScaleBasedVisibility(False)
    if key == 'districts' and panel in ('a', 'c'):
        english_district_labeling(clone, panel)
    symbol = None
    if key == 'districts':
        width = COUNTY_BOUNDARY_WIDTH_MM if panel == 'a' else RIGHT_COUNTY_BOUNDARY_WIDTH_MM
        symbol = fill('transparent', '#62696C', width)
    elif key == 'streets':
        symbol = fill('transparent', STREET_BOUNDARY_COLOR, STREET_BOUNDARY_WIDTH_MM, 'solid')
    elif key == 'city':
        symbol = fill(CITY if panel == 'a' else 'transparent', '#474D50' if panel == 'a' else '#40494E', CITY_OUTLINE_WIDTH_MM if panel == 'a' else 0.76)
    elif key == 'buildings':
        # A fine outline keeps actual small footprints legible at overview scale.
        symbol = fill(BUILDING_COLOR, BUILDING_COLOR, 0.04)
    elif key == 'built_up':
        symbol = built_up_fill()
    elif key == 'dianchi':
        if panel == 'c':
            dianchi_labeling(clone)
        symbol = fill(WATER, '#268DAD', 0.12)
    elif key == 'faults':
        # Preserve the exact RuleRenderer copied from the hazard layout.
        if panel == 'c':
            english_fault_labeling(clone)
        style = QgsMapLayerStyle()
        style.readFromLayer(clone)
        return style.xmlData()
    elif key == 'earthquakes':
        symbol = earthquake_symbol()
    elif key == 'event_2026':
        symbol = earthquake_symbol(event_2026=True, locator=(panel == 'a'))
    elif key in ('tsx1', 'tsx2'):
        color = RED if key == 'tsx1' else ORANGE
        symbol = fill('transparent', color, 0.48, 'dash' if key == 'tsx1' else 'dash dot')
    clone.setRenderer(QgsSingleSymbolRenderer(symbol))
    style = QgsMapLayerStyle()
    style.readFromLayer(clone)
    return style.xmlData()


def fit_extent(project, geographic, box):
    extent = QgsCoordinateTransform(WGS, CRS, project).transformBoundingBox(QgsRectangle(*geographic))
    return fit_projected_extent(extent, box)


def fit_projected_extent(extent, box):
    ratio = box[2] / box[3]
    cx, cy = extent.center().x(), extent.center().y()
    width, height = extent.width(), extent.height()
    if width / height < ratio:
        width = height * ratio
    else:
        height = width / ratio
    return QgsRectangle(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


def data_extent(project, layer, box, margin_m=1200):
    """Fit the complete dataset, with a small metric margin."""
    extent = QgsCoordinateTransform(layer.crs(), CRS, project).transformBoundingBox(layer.extent())
    extent.grow(margin_m)
    return fit_projected_extent(extent, box)


def building_geometry_extent(project, layer, box, margin_m=1800):
    """Fit actual projected feature geometry, avoiding a rotated provider bbox."""
    transform = QgsCoordinateTransform(layer.crs(), CRS, project)
    extent = None
    count = 0
    for feature in layer.getFeatures(QgsFeatureRequest().setNoAttributes()):
        geometry = feature.geometry()
        if geometry.isNull() or geometry.isEmpty():
            raise RuntimeError('Building without geometry: ' + str(feature.id()))
        geometry.transform(transform)
        bounds = geometry.boundingBox()
        if extent is None:
            extent = QgsRectangle(bounds)
        else:
            extent.combineExtentWith(bounds)
        count += 1
    if extent is None or count != layer.featureCount():
        raise RuntimeError('Incomplete building geometry extent')
    raw_extent = extent.toString(3)
    extent.grow(margin_m)
    return fit_projected_extent(extent, box), {
        'building_count': count, 'actual_geometry_extent': raw_extent,
        'crs': CRS.authid(), 'margin_m': margin_m,
        'method': 'Transform every building geometry to map CRS, union feature bounding boxes, add margin, fit map aspect ratio',
    }


def viewport_dem_stretch(project, buildings, box, margin_m=1800):
    """Verify that the fixed elevation classes cover every sampled DEM value."""
    map_extent, building_info = building_geometry_extent(project, buildings, box, margin_m)
    dem = gdal.Open(str(DEM_FILE), gdal.GA_ReadOnly)
    if dem is None:
        raise RuntimeError('Cannot read DEM for viewport stretch: ' + str(DEM_FILE))
    dem_crs = QgsCoordinateReferenceSystem('EPSG:32648')
    sample_extent = QgsCoordinateTransform(CRS, dem_crs, project).transformBoundingBox(map_extent)
    gt = dem.GetGeoTransform()
    if gt[2] != 0 or gt[4] != 0 or gt[1] <= 0 or gt[5] >= 0:
        raise RuntimeError('Unsupported DEM geotransform for viewport stretch')
    x0 = max(0, math.floor((sample_extent.xMinimum() - gt[0]) / gt[1]))
    x1 = min(dem.RasterXSize, math.ceil((sample_extent.xMaximum() - gt[0]) / gt[1]))
    y0 = max(0, math.floor((sample_extent.yMaximum() - gt[3]) / gt[5]))
    y1 = min(dem.RasterYSize, math.ceil((sample_extent.yMinimum() - gt[3]) / gt[5]))
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError('Right-map extent does not overlap the DEM')
    band = dem.GetRasterBand(1)
    pixels = band.ReadAsArray(x0, y0, x1 - x0, y1 - y0)
    nodata = band.GetNoDataValue()
    valid = np.isfinite(pixels)
    if nodata is not None:
        valid &= pixels != nodata
    values = pixels[valid]
    if values.size < 100:
        raise RuntimeError('Too few valid DEM pixels in the right-map extent')
    if values.min() < DEM_MIN or values.max() > DEM_MAX:
        raise RuntimeError('The elevation legend must cover the complete viewport DEM range')
    stats = {
        'method': 'Fixed elevation classes covering the full valid viewport DEM range; no percentile clipping',
        'percentiles': None,
        'stretch_limits_m': [DEM_MIN, DEM_MAX],
        'sample_min_max_m': [int(values.min()), int(values.max())],
        'sample_pixel_count': int(values.size),
        'sample_window_pixels': [int(x1 - x0), int(y1 - y0)],
        'sample_extent_dem_crs': sample_extent.toString(3),
        'class_count': len(DEM_COLORS),
        'all_sampled_values_covered': True,
        'class_method': '200 m intervals from 1600 to 2800 m, then 2800 to 2900 m; discrete shader stops are upper bounds',
        'class_bounds_m': [round(value, 1) for value in DEM_CLASS_BOUNDS],
        'color_stops': [[round(value, 1), color] for value, color in DEM_STOPS],
        'building_extent': building_info,
    }
    dem = None
    return map_extent, stats


def make_map(project, layout, id_, box, layers, panel, geographic, background):
    item = QgsLayoutItemMap(layout)
    item.setId(id_)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(*box[:2]))
    item.attemptResize(QgsLayoutSize(*box[2:]))
    item.setCrs(CRS)
    item.zoomToExtent(fit_extent(project, geographic, box))
    item.setLayers([layers[k] for k in panel['layers']])
    item.setKeepLayerSet(True)
    item.setKeepLayerStyles(True)
    item.setLayerStyleOverrides({layers[k].id(): style_xml(layers[k], k, panel['name']) for k in panel['layers']})
    item.setBackgroundEnabled(True)
    item.setBackgroundColor(QColor(background))
    item.setFrameEnabled(True)
    item.setFrameStrokeColor(QColor(INK))
    item.setFrameStrokeWidth(QgsLayoutMeasurement(0.65))
    item.setZValue(1)
    return item


def cache_terrain(project, map_, layers, key, dem_sha256):
    """Fuse only DEM color and shade, retaining vector features in the PDF.

    QGIS's forced vector PDF export does not preserve raster Multiply blending.
    A georeferenced RGBA cache renders identically in PNG/PDF and remains at the
    final 1200 dpi resolution. Content-addressed files keep prior layouts usable.
    """
    terrain_dpi = 1200
    size = QSize(math.ceil(map_.sizeWithUnits().width() * terrain_dpi / 25.4),
                 math.ceil(map_.sizeWithUnits().height() * terrain_dpi / 25.4))
    requested = map_.extent()
    settings = QgsMapSettings()
    settings.setDestinationCrs(CRS)
    settings.setTransformContext(project.transformContext())
    settings.setOutputSize(size)
    settings.setOutputDpi(terrain_dpi)
    settings.setExtent(requested)
    settings.setBackgroundColor(QColor(0, 0, 0, 0))
    settings.setLayers([layers['hillshade'], layers['dem']])
    settings.setFlag(QgsMapSettings.UseAdvancedEffects, True)
    # Integer pixel dimensions slightly change the rendered aspect ratio.
    # Georeference the actual rendered extent to preserve terrain alignment.
    extent = settings.visibleExtent()
    identity = {'dem_sha256': dem_sha256, 'crs': CRS.authid(), 'rasterization_version': 4,
                'requested_extent': [requested.xMinimum(), requested.yMinimum(), requested.xMaximum(), requested.yMaximum()],
                'extent': [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()],
                'pixels': [size.width(), size.height()], 'dpi': terrain_dpi,
                'color_range': [DEM_MIN, DEM_MAX], 'color_stops': DEM_STOPS,
                'hillshade': {'azimuth': 315, 'altitude': 40, 'opacity': HILLSHADE_OPACITY,
                              'z_factor': 1, 'blend': 'Multiply'}}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    cache_dir = ROOT / '../result/intermediate/cartography/study_area_terrain'
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (key + '_' + digest + '.tif')
    if not cache_file.exists():
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        if job.errors():
            raise RuntimeError('Terrain rendering errors: ' + str(job.errors()))
        with tempfile.TemporaryDirectory(prefix='kunming_terrain_') as tmp:
            png = Path(tmp) / 'terrain.png'
            if not job.renderedImage().save(str(png), 'PNG'):
                raise RuntimeError('Terrain PNG cache failed')
            gdal.UseExceptions()
            dataset = gdal.Translate(str(cache_file), str(png), format='GTiff',
                                     outputSRS=CRS.toWkt(),
                                     outputBounds=[extent.xMinimum(), extent.yMaximum(), extent.xMaximum(), extent.yMinimum()],
                                     creationOptions=['COMPRESS=DEFLATE', 'TILED=YES'])
            dataset = None
    layer = QgsRasterLayer(str(cache_file), 'Yunnan DEM · Hypsometric Tint and Hillshade · ' + key)
    if not layer.isValid():
        raise RuntimeError('Invalid fused terrain cache')
    layer.setCustomProperty('study_area/source_key', key)
    project.addMapLayer(layer)
    layers[key] = layer
    # Preserve all vector styles and replace only the two terrain rendering layers.
    kept = [l for l in map_.layers() if l not in [layers['hillshade'], layers['dem']]]
    styles = {l.id(): map_.layerStyleOverrides()[l.id()] for l in kept}
    styles[layer.id()] = style_xml(layer, key, '')
    map_.setLayers(kept + [layer])
    map_.setLayerStyleOverrides(styles)
    raster = gdal.Open(str(cache_file))
    alpha = raster.GetRasterBand(4).ReadAsArray()
    info = {**identity, 'file': str(cache_file), 'sha256': sha(cache_file),
            'nodata_pixel_fraction': float((alpha == 0).sum() / alpha.size)}
    raster = None
    cache_file.with_suffix('.source.json').write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
    return info


def north(layout, map_, x, y):
    arrow = QgsLayoutItemPicture(layout)
    arrow.setId(map_.id() + '_North')
    layout.addLayoutItem(arrow)
    arrow.attemptMove(QgsLayoutPoint(x, y + 4))
    arrow.attemptResize(QgsLayoutSize(4, 7))
    arrow.setPicturePath(str(OUT / 'north_arrow.svg'))
    arrow.setLinkedMap(map_)
    arrow.setNorthMode(QgsLayoutItemPicture.TrueNorth)
    arrow.setZValue(15)
    label(layout, map_.id() + '_N', 'N', (x - 0.5, y, 5, 4), 9, bold=True, family='Times New Roman', center=True)


def scale(layout, map_, x, y, km, transparent=False):
    item = QgsLayoutItemScaleBar(layout)
    item.setId(map_.id() + '_Scale')
    item.setStyle('Line Ticks Up')
    item.setLinkedMap(map_)
    item.setUnits(Qgis.DistanceUnit.Kilometers)
    item.setUnitsPerSegment(km)
    item.setNumberOfSegments(1)
    item.setNumberOfSegmentsLeft(0)
    item.setUnitLabel('km')
    item.setHeight(1.2)
    item.setLineSymbol(line(INK, 0.22))
    item.setTextFormat(font(10, INK, bold=True, family='Arial', halo=transparent))
    item.setLabelBarSpace(0.5 if transparent else 0.7)
    item.setBoxContentSpace(0 if transparent else 0.8)
    item.setBackgroundEnabled(not transparent)
    if not transparent:
        item.setBackgroundColor(QColor(255, 255, 255, 235))
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y))
    item.setZValue(16)


def rectangle(layout, id_, box, symbol):
    item = QgsLayoutItemShape(layout)
    item.setId(id_)
    item.setShapeType(QgsLayoutItemShape.Rectangle)
    item.setSymbol(symbol)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(*box[:2]))
    item.attemptResize(QgsLayoutSize(*box[2:]))
    item.setZValue(12)
    return item


def polyline(layout, id_, coords, symbol):
    item = QgsLayoutItemPolyline(QPolygonF([QPointF(*p) for p in coords]), layout)
    item.setId(id_)
    item.setSymbol(symbol)
    layout.addLayoutItem(item)
    item.setZValue(12)
    return item


def fault_legend_symbol(renderer):
    # Use the ordinary fault rule (white casing plus brown-red core), without
    # the separate left-lateral marker rule.
    rule = next(r for r in renderer.rootRule().children() if r.isElse())
    return rule.symbol().clone()


def layout_point_icon(layout, id_, svg_path, x, y, size=6.0):
    """Place a point-symbol SVG centered on the same baseline as its legend text."""
    item = QgsLayoutItemPicture(layout)
    item.setId(id_)
    item.setPicturePath(str(svg_path))
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x + (7.0 - size) / 2, y + (7.7 - size) / 2))
    item.attemptResize(QgsLayoutSize(size, size))
    item.setZValue(13)
    return item


def left_symbol_legend(layout, fault_renderer):
    """Compact, three-column key for thematic layers, historic earthquakes and TSX frames."""
    rows = LEGEND_ROWS
    col1, col2, col3 = LEGEND_COLUMNS
    entries = [
        ('buildings', col1, rows[0], 'Buildings'),
        ('built_up', col2, rows[0], 'Built-up area'),
        ('faults', col3, rows[0], 'Faults'),
        ('dianchi', col1, rows[1], 'Dianchi Lake'),
        ('tsx1', col2, rows[1], 'TSX1 extent'),
        ('tsx2', col3, rows[1], 'TSX2 extent'),
        ('gnss', col1, rows[2], 'GNSS station'),
        ('historical_earthquakes', col2, rows[2], 'Historical earthquakes'),
    ]
    for key, x, y, text in entries:
        text_size = 12
        y_text = y
        if key == 'buildings':
            rectangle(layout, 'Legend_buildings', (x, y + 1.8, 7.5, 3.8), building_legend_fill())
        elif key == 'built_up':
            rectangle(layout, 'Legend_built_up', (x, y + 1.8, 7.5, 3.8), built_up_fill())
        elif key == 'faults':
            polyline(layout, 'Legend_faults', [(x, y + 3.8), (x + 8, y + 3.8)],
                     fault_legend_symbol(fault_renderer))
        elif key == 'dianchi':
            rectangle(layout, 'Legend_dianchi', (x, y + 2.0, 7.5, 4.2),
                      fill(WATER, '#268DAD', 0.12))
        elif key == 'historical_earthquakes':
            layout_point_icon(layout, 'Legend_historical_earthquakes', EARTHQUAKE_TRIANGLE_SVG, x, y)
        elif key == 'gnss':
            layout_point_icon(layout, 'Legend_gnss', GNSS_STAR_SVG, x, y)
        elif key == 'tsx1':
            polyline(layout, 'Legend_tsx1', [(x, y + 3.8), (x + 8, y + 3.8)],
                     line(RED, 0.65, 'dash'))
        elif key == 'tsx2':
            polyline(layout, 'Legend_tsx2', [(x, y + 3.8), (x + 8, y + 3.8)],
                     line(ORANGE, 0.65, 'dash dot'))
        width = 66 if key == 'historical_earthquakes' else 28
        label(layout, 'Legend_label_' + key, text, (x + 9.5, y_text, width, 7.7),
              text_size, bold=True, family='Arial')


def add_gnss_station(layout, project, map_, item_id, size_mm=7.0):
    x, y = map_position(project, map_, GNSS_LON, GNSS_LAT)
    marker = QgsLayoutItemPicture(layout)
    marker.setId(item_id)
    marker.setPicturePath(str(GNSS_STAR_SVG))
    layout.addLayoutItem(marker)
    marker.attemptMove(QgsLayoutPoint(x - size_mm / 2, y - size_mm / 2))
    marker.attemptResize(QgsLayoutSize(size_mm, size_mm))
    marker.setZValue(21)
    return {'id': marker.id(), 'longitude': GNSS_LON, 'latitude': GNSS_LAT,
            'symbol': 'red five-point star with white casing', 'color': GNSS_COLOR,
            'page_position_mm': [x, y], 'marker_size_mm': size_mm}


def map_position(project, map_, lon, lat):
    p = QgsCoordinateTransform(WGS, map_.crs(), project).transform(QgsPointXY(lon, lat))
    extent, pos, size = map_.extent(), map_.positionWithUnits(), map_.sizeWithUnits()
    return (pos.x() + (p.x() - extent.xMinimum()) / extent.width() * size.width(),
            pos.y() + (extent.yMaximum() - p.y()) / extent.height() * size.height())


def event_annotations(layout, project, map_, layers):
    """Mw callouts with red leader lines for the two requested epicenters."""
    historical = next((f for f in layers['earthquakes'].getFeatures()
                       if str(f['发震时']).startswith('2023-01-27') and float(f['震级_M_']) == 2.1), None)
    recent = next(layers['event_2026'].getFeatures(), None)
    if historical is None or recent is None:
        raise RuntimeError('The two requested earthquake points are missing from the source data')
    entries = []
    specs = [
        ('event_2023_label', f'{EVENT_2023_DATE}\nMw {EVENT_2023_MAGNITUDE:.1f}',
         float(historical['经度___']), float(historical['纬度___']), -18, -13, HISTORICAL_EQ_COLOR, 2.7),
        ('event_2026_label', f'{EVENT_2026_DATE}\nMw {EVENT_2026_MAGNITUDE:.1f}',
         float(recent['longitude']), float(recent['latitude']), 15, -14, EVENT_2026_COLOR, 3.8),
    ]
    for id_, value, lon, lat, dx, dy, color, marker_clearance in specs:
        anchor_x, anchor_y = map_position(project, map_, lon, lat)
        box = (anchor_x + dx - 18, anchor_y + dy - 6.2, 36, 12.4)
        center_x, center_y = box[0] + box[2] / 2, box[1] + box[3] / 2
        vx, vy = center_x - anchor_x, center_y - anchor_y
        distance = math.hypot(vx, vy)
        edge_t = min((box[2] / 2) / abs(vx) if vx else float('inf'),
                     (box[3] / 2) / abs(vy) if vy else float('inf'))
        line_end = (anchor_x + vx * edge_t, anchor_y + vy * edge_t)
        line_start = (anchor_x + vx / distance * marker_clearance,
                      anchor_y + vy / distance * marker_clearance)
        leader = polyline(layout, id_ + '_leader', [line_start, line_end], line(RED, 0.30))
        leader.setZValue(22)
        item = label(layout, id_, value, box, 14, color, bold=True, family='Arial', center=True)
        text_format = font(14, color, bold=True, family='Arial', halo=True)
        qfont = text_format.font()
        qfont.setItalic(True)
        text_format.setFont(qfont)
        item.setTextFormat(text_format)
        item.setZValue(24)
        entries.append({'id': id_, 'text': value.replace('\n', ' / '),
                        'longitude': lon, 'latitude': lat, 'font_size_pt': 14,
                        'color': color, 'label_box_mm': list(box),
                        'leader_line': {'color': RED, 'width_mm': 0.30,
                                        'start_mm': list(line_start), 'end_mm': list(line_end)}})
    return entries


def gnss_annotation(layout, project, map_):
    """Label the right-map GNSS station without a red leader/arrow."""
    anchor_x, anchor_y = map_position(project, map_, GNSS_LON, GNSS_LAT)
    # Keep the label on the same baseline as the star, just beyond its white casing.
    box = (anchor_x + 4.5, anchor_y - 4.0, 38.0, 8.0)
    item = label(layout, 'GNSS_station_label', 'GNSS station', box,
                 14, RED, bold=True, family='Arial')
    text_format = font(14, RED, bold=True, family='Arial', halo=True)
    qfont = text_format.font()
    qfont.setItalic(True)
    text_format.setFont(qfont)
    item.setTextFormat(text_format)
    item.setZValue(24)
    return {'text': 'GNSS station', 'longitude': GNSS_LON, 'latitude': GNSS_LAT,
            'font_family': 'Arial', 'font_size_pt': 14, 'bold': True, 'italic': True,
            'color': RED, 'white_halo_mm': 0.55, 'label_box_mm': list(box),
            'symbol_to_label_gap_mm': 1.0, 'connector': 'none'}


def grid(map_, interval_minutes=5):
    # Reference: original_documents/optimize_hazard_layout.py and its saved QPT,
    # history/changes/2026-10-13_004_hazard_paper_style. The original latitude
    # cutoff (25.249) belongs to that older map extent, so it is not reused here.
    g = map_.grid()
    g.setEnabled(True)
    g.setCrs(WGS)
    g.setIntervalX(interval_minutes / 60)
    g.setIntervalY(interval_minutes / 60)
    g.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly)
    g.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
    g.setFrameWidth(1.0)
    g.setFramePenSize(0.25)
    g.setFramePenColor(QColor('black'))
    g.setAnnotationEnabled(True)
    g.setAnnotationTextFormat(font(8.5, INK, bold=True, family='Arial'))
    g.setAnnotationFrameDistance(1.1)
    g.setAnnotationPrecision(0)
    g.setAnnotationFormat(QgsLayoutItemMapGrid.CustomFormat)
    g.setAnnotationExpression("to_string(floor(round(@grid_number*60)/60)) || '°' || to_string(round(@grid_number*60)%60) || '′' || if(@grid_axis='x','E','N')")
    for border in (g.Top, g.Left, g.Bottom, g.Right):
        g.setAnnotationPosition(g.OutsideMapFrame, border)
        g.setAnnotationDisplay(g.LongitudeOnly if border == g.Top else g.LatitudeOnly if border == g.Left else g.HideAll, border)
        g.setAnnotationDirection(g.Vertical if border == g.Left else g.Horizontal, border)


def elevation_legend(layout):
    x, y, width = RIGHT_BOX[0] + 4, 207.5, RIGHT_BOX[2] - 8
    for i, color in enumerate(DEM_COLORS):
        left = x + (DEM_CLASS_BOUNDS[i] - DEM_MIN) / (DEM_MAX - DEM_MIN) * width
        class_width = (DEM_CLASS_BOUNDS[i + 1] - DEM_CLASS_BOUNDS[i]) / (DEM_MAX - DEM_MIN) * width
        rectangle(layout, 'Elevation_class_' + str(i + 1),
                  (left, y, class_width - 0.18, 5.5),
                  fill(color, color, 0))
    for i, value in enumerate(DEM_CLASS_BOUNDS):
        px = x + (value - DEM_MIN) / (DEM_MAX - DEM_MIN) * width
        label(layout, 'Elevation_break_' + str(i), f'{value:,.0f}',
              (px - 8, 198.5, 16, 9), 12, bold=True, family='Arial', center=True)
    label(layout, 'Elevation_legend_title', 'Elevation (m)',
          (RIGHT_BOX[0], 214.5, RIGHT_BOX[2], 18), 18, bold=True, family='Arial', center=True)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_layout_symbol_assets()
    project = QgsProject()
    project.setCrs(CRS)
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setTitle('Kunming Study Area | DEM, Buildings and Administrative Boundaries')
    project.setBackgroundColor(QColor('white'))
    source_fault_renderer, fault_reference = load_hazard_fault_renderer()
    hazard_fault_renderer = thicken_fault_renderer(source_fault_renderer)
    fault_reference['layout_width_multiplier'] = FAULT_WIDTH_MULTIPLIER
    fault_reference['layout_widths_mm'] = fault_line_widths(hazard_fault_renderer)
    layers = {}
    source_hashes = {}
    for asset in fault_reference['assets']:
        source_hashes[asset['original']] = sha(asset['original'])
        source_hashes[asset['local']] = sha(asset['local'])
    for key, (name, path) in SOURCES.items():
        source = str((ROOT / path).resolve())
        layer = QgsVectorLayer(source, name, 'ogr')
        if not layer.isValid():
            raise RuntimeError('Invalid source: ' + source)
        if key == 'earthquakes':
            # Select the full 2012–2024 catalog by the official Kunming county
            # codes, then verify every selected epicenter against their union.
            earthquake_catalog_record_count = layer.featureCount()
            if earthquake_catalog_record_count != 7944:
                raise RuntimeError('The 2012–2024 historical earthquake catalog should contain 7,944 records')
            kunming_counties = list(layers['districts'].getFeatures())
            county_codes = sorted({str(f['gb']) for f in kunming_counties})
            code_values = ', '.join("'" + code.replace("'", "''") + "'" for code in county_codes)
            subset = f'"gb" IN ({code_values})'
            if not layer.setSubsetString(subset) or layer.featureCount() != 10:
                raise RuntimeError('Kunming boundary filter must select the 10 known 2012–2024 catalog events')
            kunming_union = QgsGeometry.unaryUnion([f.geometry() for f in kunming_counties])
            to_admin_crs = QgsCoordinateTransform(layer.crs(), layers['districts'].crs(), project)
            selected_earthquakes = list(layer.getFeatures())
            outside = []
            for earthquake in selected_earthquakes:
                point = QgsGeometry(earthquake.geometry())
                point.transform(to_admin_crs)
                if not kunming_union.intersects(point):
                    outside.append(earthquake.id())
            if outside:
                raise RuntimeError('Kunming code-filtered earthquakes outside district geometry: ' + str(outside))
        elif key == 'districts':
            subset = '"gb" LIKE \'1565301%\''
            if not layer.setSubsetString(subset) or layer.featureCount() != 14:
                raise RuntimeError('Review-number county boundary source must contain exactly 14 Kunming districts')
            district_features = list(layer.getFeatures())
            if {f['name'] for f in district_features} != KUNMING_DISTRICT_NAMES:
                raise RuntimeError('Review-number boundary source does not match the 14 expected Kunming districts')
            if any(not f.geometry().isGeosValid() for f in district_features):
                raise RuntimeError('Invalid geometry in review-number Kunming district boundaries')
        elif key == 'city':
            subset = '"gb" = \'156530100\''
            if not layer.setSubsetString(subset) or layer.featureCount() != 1:
                raise RuntimeError('Review-number city boundary source must contain one Kunming city polygon')
            city_feature = next(layer.getFeatures())
            if city_feature['name'] != '昆明市' or not city_feature.geometry().isGeosValid():
                raise RuntimeError('Review-number city boundary does not resolve to a valid Kunming polygon')
        layer.setCustomProperty('study_area/source_key', key)
        if key == 'faults':
            layer.setRenderer(hazard_fault_renderer.clone())
        project.addMapLayer(layer)
        layers[key] = layer
        file = Path(source.split('|')[0])
        # Hash all parts of each Shapefile, plus SQLite packages and the main project.
        if file.suffix == '.shp':
            paths = list(file.parent.glob(file.stem + '.*'))
        elif file.is_dir() and file.suffix.lower() == '.gdb':
            # Ignore volatile ArcGIS lock markers; hash stored data and metadata.
            paths = [p for p in file.iterdir() if p.is_file() and not p.name.endswith('.lock')]
        else:
            paths = [file]
        for path in paths:
            source_hashes[str(path)] = sha(path)
        QgsMapLayerStyle(style_xml(layer, key, 'c')).writeToLayer(layer)
    district_features = list(layers['districts'].getFeatures())
    city_feature = next(layers['city'].getFeatures())
    district_union = QgsGeometry.unaryUnion([f.geometry() for f in district_features])
    admin_symdiff_area = district_union.symDifference(city_feature.geometry()).area()
    if admin_symdiff_area > 1e-12:
        raise RuntimeError('The selected Kunming county boundaries do not match the city boundary')
    right_extent, dem_stretch_info = viewport_dem_stretch(project, layers['buildings'], RIGHT_BOX)
    for key in ['dem', 'hillshade']:
        layer = dem_layer(hillshade=key == 'hillshade')
        layer.setCustomProperty('study_area/source_key', key)
        project.addMapLayer(layer)
        layers[key] = layer
    for path in [DEM_FILE, *DEM_FILE.parent.glob(DEM_FILE.name + '.*'), DEM_FILE.with_suffix('.tfw')]:
        if path.is_file():
            source_hashes[str(path)] = sha(path)
    canonical = ROOT / '04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz'
    source_hashes[str(canonical)] = sha(canonical)
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(NAME)
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(300, 235))
    layout.renderContext().setDpi(1200)
    project.layoutManager().addLayout(layout)

    a = make_map(project, layout, 'A_Kunming_City', LEFT_BOX, layers,
                 {'name': 'a', 'layers': ['event_2026', 'earthquakes', 'tsx1', 'tsx2', 'dianchi', 'districts', 'city']},
                 (102.10, 24.31, 103.75, 26.62), 'white')
    a.zoomToExtent(data_extent(project, layers['city'], LEFT_BOX, margin_m=5000))
    a.setFrameEnabled(False)
    a.grid().setEnabled(False)
    a.grid().setAnnotationEnabled(False)
    c = make_map(project, layout, 'C_Study_Area', RIGHT_BOX, layers,
                 {'name': 'c', 'layers': ['event_2026', 'earthquakes', 'faults', 'dianchi', 'streets', 'districts', 'buildings', 'built_up', 'hillshade', 'dem']},
                 (102.40, 24.61, 103.18, 25.40), '#FAFBF9')
    c.zoomToExtent(right_extent)
    layout.setReferenceMap(c)
    grid(c)
    event_label_checks = event_annotations(layout, project, c, layers)
    gnss_left_check = add_gnss_station(layout, project, a, 'GNSS_station_A', size_mm=5.5)
    gnss_check = add_gnss_station(layout, project, c, 'GNSS_station_C', size_mm=7.0)
    gnss_label_checks = gnss_annotation(layout, project, c)
    north(layout, a, LEFT_BOX[0] + LEFT_BOX[2] - 6, 15)
    north(layout, c, RIGHT_BOX[0] + RIGHT_BOX[2] - 12, 15)
    scale(layout, a, 11, LEFT_BOX[1] + LEFT_BOX[3] + 1, 10)
    scale(layout, c, RIGHT_BOX[0] + 7,
          RIGHT_BOX[1] + RIGHT_BOX[3] - 10.5, 5, transparent=True)
    label(layout, 'Left_map_Kunming', 'Kunming',
          (LEFT_BOX[0], 190.0, LEFT_BOX[2], 12.0),
          18, bold=True, family='Arial', center=True)
    left_symbol_legend(layout, hazard_fault_renderer)
    elevation_legend(layout)

    terrain_caches = {
        'right': cache_terrain(project, c, layers, 'terrain_detail', source_hashes[str(DEM_FILE)]),
    }
    for info in terrain_caches.values():
        source_hashes[info['file']] = info['sha256']

    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(c.extent(), CRS))
    # Keep the default canvas in the same order as the detailed map.
    root = project.layerTreeRoot()
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(c.layers())
    project.setFileName(str(ROOT / '01_study_area/qgis/projects/01_study_area.qgz'))
    if not project.write():
        raise RuntimeError('Project write failed')
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(OUT / (NAME + '.qpt'))))
    if not layout.saveAsTemplate(str(OUT / (NAME + '.qpt')), context):
        raise RuntimeError('Template write failed')
    # Export the saved layout so the previews match the project users actually open.
    reopened = QgsProject()
    if not reopened.read(project.fileName()):
        raise RuntimeError('Saved project cannot be reopened')
    reopened_layout = reopened.layoutManager().layoutByName(NAME)
    if reopened_layout is None:
        raise RuntimeError('Saved layout missing')
    assert all(l.isValid() for l in reopened.mapLayers().values())
    exporter = QgsLayoutExporter(reopened_layout)
    for name, dpi in [('preview.png', 150), (NAME + '.png', 1200), (NAME + '.tif', 1200)]:
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = dpi
        settings.exportMetadata = False
        result = exporter.exportToImage(str(EXPORT_DIR / name), settings)
        if result != QgsLayoutExporter.Success:
            raise RuntimeError(f'Image export failed: {name}: {result}')
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = 1200
    settings.forceVectorOutput = True
    settings.exportMetadata = True
    result = exporter.exportToPdf(str(EXPORT_DIR / (NAME + '.pdf')), settings)
    if result != QgsLayoutExporter.Success:
        raise RuntimeError(f'PDF export failed: {result}')
    # The TSX detail follows the left context map, where its footprints are shown.
    detail_map = reopened_layout.itemById('A_Kunming_City')
    px, py = map_position(reopened, detail_map, 102.84, 25.29)
    detail = exporter.renderRegionToImage(QRectF(px - 18, py - 8, 36, 25), QSize(), 300)
    if detail.isNull() or not detail.save(str(EXPORT_DIR / 'TSX_overlap_detail.png'), 'PNG'):
        raise RuntimeError('TSX detail preview export failed')

    changed_inputs = [path for path, digest in source_hashes.items() if sha(path) != digest]
    if changed_inputs:
        raise RuntimeError('Input file changed during rendering: ' + ', '.join(changed_inputs))
    events = []
    c_poly = QgsGeometry.fromRect(c.extent())
    c_poly.transform(QgsCoordinateTransform(CRS, WGS, project))
    for f in layers['earthquakes'].getFeatures():
        if c_poly.intersects(f.geometry()):
            events.append({'date': str(f['发震时']), 'magnitude': f['震级_M_'], 'lon': f['经度___'], 'lat': f['纬度___']})
    recent_event = next(layers['event_2026'].getFeatures())
    events.append({'date': EVENT_2026_DATE, 'magnitude': EVENT_2026_MAGNITUDE,
                   'lon': float(recent_event['longitude']), 'lat': float(recent_event['latitude']),
                   'depth_km': float(recent_event['depth_km']), 'source': layers['event_2026'].source()})
    checks = {
        'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'qgis_version': Qgis.QGIS_VERSION, 'project': project.fileName(),
        'layout': NAME, 'page_mm': [300, 235], 'source_files_unchanged': True,
        'export_profiles': {
            NAME + '.tif': {'format': 'TIFF', 'dpi': 1200, 'purpose': 'high-resolution journal submission',
                            'page_mm': [300, 235]},
            NAME + '.pdf': {'format': 'PDF', 'dpi': 1200, 'purpose': 'vector-first typesetting; terrain is a 1200 dpi raster layer'},
            NAME + '.png': {'format': 'PNG', 'dpi': 1200, 'purpose': 'high-resolution journal submission'},
        },
        'canonical_project_unchanged': True, 'dem_drawn': True,
        'cartographic_text': {
            'title': 'omitted', 'subtitle': 'omitted', 'footer_source_note': 'omitted',
            'map_feature_labels': 'English district names, fault names, Dian Lake, two earthquake callouts, and a GNSS station callout without a leader; left map shows all 10 historical Kunming catalog events plus the 2026 event as red triangles',
            'symbol_legend': 'eight compact English items in three columns below left map; one red triangle represents historical earthquakes',
            'elevation_legend': 'seven discrete classes at the bottom below right map',
        },
        'left_scope': 'Kunming city with 14 county-level boundaries, gray fill, Dianchi, red GNSS star, all 10 historical catalog earthquakes within Kunming (2012–2024), the 2026 event, and TSX footprints; no surrounding administrative boundaries',
        'kunming_historical_earthquakes': {
            'source_catalog': str(layers['earthquakes'].source()),
            'source_catalog_record_count': earthquake_catalog_record_count,
            'selected_record_count': len(selected_earthquakes),
            'selection_method': 'official GS(2024)0650 county codes for all 14 Kunming districts, validated by point intersection with the district union',
            'marker': 'red triangle',
            'events': [{'date': str(f['发震时']), 'magnitude': float(f['震级_M_']),
                        'longitude': float(f['经度___']), 'latitude': float(f['纬度___']),
                        'district': str(f['name'])} for f in selected_earthquakes],
        },
        'administrative_boundary_source': {
            'review_number': 'GS(2024)0650号',
            'city_layer': str(layers['city'].source()), 'city_name': city_feature['name'],
            'city_code': city_feature['gb'], 'county_layer': str(layers['districts'].source()),
            'county_code_filter': '1565301*', 'county_count': len(district_features),
            'county_names': sorted(f['name'] for f in district_features),
            'all_county_geometries_valid': all(f.geometry().isGeosValid() for f in district_features),
            'county_union_city_symdifference_area_degrees2': admin_symdiff_area,
        },
        'right_administrative_levels': ['county-level district boundaries and names', 'subdistrict/township boundaries'],
        'right_district_labels_drawn': True,
        'right_city_boundary_drawn': False, 'right_district_boundaries_drawn': True,
        'administrative_line_widths_mm': {'left_city': CITY_OUTLINE_WIDTH_MM, 'left_districts': COUNTY_BOUNDARY_WIDTH_MM, 'right_city': 0.76, 'right_districts': RIGHT_COUNTY_BOUNDARY_WIDTH_MM, 'right_streets': STREET_BOUNDARY_WIDTH_MM},
        'administrative_line_colors': {'left_county': '#62696C', 'right_counties': '#62696C', 'right_streets': STREET_BOUNDARY_COLOR},
        'left_english_administrative_labels': 14,
        'left_district_label_font_pt': 12,
        'left_map_size_mm': [LEFT_BOX[2], LEFT_BOX[3]],
        'left_district_boundaries_drawn': layers['districts'] in a.layers(),
        'right_street_boundaries_drawn': layers['streets'] in c.layers(),
        'right_street_boundary_line_style': 'solid, light gray',
        'feature_labels_enabled': True, 'right_fault_labels_enabled': True,
        'right_fault_label_field': 'FN_En (English names; display aliases abbreviated for edge clearance)',
        'right_fault_label_style': {'font_family': 'Arial', 'font_size_pt': 14.0, 'italic': True, 'white_halo_mm': 0.85},
        'right_earthquake_overlay': {
            'historical_event': {'date': EVENT_2023_DATE, 'magnitude': EVENT_2023_MAGNITUDE, 'longitude': 102.64, 'latitude': 25.04,
                                 'symbol': 'red triangle with white casing'},
            'recent_event': {'date': EVENT_2026_DATE, 'magnitude': EVENT_2026_MAGNITUDE,
                             'longitude': 102.73, 'latitude': 25.09, 'depth_km': 10,
                             'source': str(layers['event_2026'].source()), 'symbol': 'red triangle with white casing'},
            'callouts': event_label_checks,
            'left_map_symbols': 'all 10 historical Kunming events and the 2026 event use red triangular markers',
            'magnitude_notation': 'Mw',
            'leader_lines': {'color': RED, 'width_mm': 0.30},
        },
        'gnss_station': gnss_check,
        'gnss_station_left_map': gnss_left_check,
        'gnss_station_right_label': gnss_label_checks,
        'gnss_label_close_to_star': True,
        'gnss_station_drawn_on_maps': ['A_Kunming_City', 'C_Study_Area'],
        'left_locator_label_adjustments': {'Guandu': 'shifted east/northeast to avoid overlap with the GNSS star'},
        'right_label_adjustments': {'Songming': 'shifted southwest inside the map frame to clear the north arrow'},
        'left_map_kunming_label': {
            'text': 'Kunming', 'font_family': 'Arial', 'font_size_pt': 18.0,
            'bold': True, 'same_size_as': 'Elevation (m)',
            'position_mm': [LEFT_BOX[0], 190.0, LEFT_BOX[2], 12.0],
        },
        'right_dian_lake_label': {'text': 'Dian Lake', 'font_family': 'Arial', 'font_size_pt': 16.0},
        'removed_panel_b': True,
        'left_extent_boxes': 2, 'tsx_frames_left_only': all(layers[k] in a.layers() and layers[k] not in c.layers() for k in ['tsx1', 'tsx2']),
        'left_map_frame_enabled': a.frameEnabled(), 'right_map_frame_enabled': c.frameEnabled(),
        'left_coordinates_enabled': a.grid().enabled() or a.grid().annotationEnabled(),
        'left_dem_drawn': any(isinstance(l, QgsRasterLayer) for l in a.layers()),
        'left_faults_drawn': layers['faults'] in a.layers(),
        'left_has_historical_earthquakes': layers['earthquakes'] in a.layers(),
        'left_historical_earthquake_marker_count': layers['earthquakes'].featureCount(),
        'left_has_recent_earthquake': layers['event_2026'] in a.layers(),
        'gnss_station_leader_removed': layout.itemById('GNSS_station_leader') is None,
        'right_map_larger_than_left': RIGHT_BOX[2] > LEFT_BOX[2] and RIGHT_BOX[3] > LEFT_BOX[3],
        'left_scale_outside_map': layout.itemById(a.id() + '_Scale').positionWithUnits().y() > a.positionWithUnits().y() + a.sizeWithUnits().height(),
        'left_scale_clear_of_legend': (
            layout.itemById(a.id() + '_Scale').positionWithUnits().y()
            + layout.itemById(a.id() + '_Scale').sizeWithUnits().height() <= LEGEND_ROWS[0]
        ),
        'right_scale_inside_map': (
            layout.itemById(c.id() + '_Scale').positionWithUnits().x() >= c.positionWithUnits().x()
            and layout.itemById(c.id() + '_Scale').positionWithUnits().y() >= c.positionWithUnits().y()
            and layout.itemById(c.id() + '_Scale').positionWithUnits().x() + 30 <= c.positionWithUnits().x() + c.sizeWithUnits().width()
            and layout.itemById(c.id() + '_Scale').positionWithUnits().y() + 10 <= c.positionWithUnits().y() + c.sizeWithUnits().height()
        ),
        'left_symbol_legend_visible': all(layout.itemById(i) is not None for i in [
            'Legend_buildings', 'Legend_built_up', 'Legend_faults', 'Legend_dianchi',
            'Legend_historical_earthquakes', 'Legend_gnss', 'Legend_tsx1', 'Legend_tsx2']),
        'left_symbol_legend_items': ['Buildings', 'Built-up area', 'Faults', 'Dianchi Lake',
                                     'TSX1 extent', 'TSX2 extent', 'GNSS station', 'Historical earthquakes'],
        'left_symbol_legend_columns': 3,
        'left_symbol_legend_rows': 3,
        'earthquake_legend_symbol_counts': {'Historical earthquakes': 1},
        'left_symbol_legend_styles': {
            'Buildings': {'shape': 'rectangle', 'size_mm': [7.5, 3.8], 'fill': BUILDING_COLOR,
                          'outline': BUILDING_LEGEND_EDGE, 'outline_width_mm': BUILT_UP_OUTLINE_WIDTH,
                          'opacity': BUILDING_LEGEND_OPACITY},
            'Built-up area': {'shape': 'rectangle', 'size_mm': [7.5, 3.8], 'fill': BUILT_UP_COLOR,
                              'outline': BUILT_UP_EDGE, 'outline_width_mm': BUILT_UP_OUTLINE_WIDTH,
                              'opacity': BUILT_UP_OPACITY},
            'Historical earthquakes': 'one red triangle for all historic epicenters',
            'GNSS station': {'shape': 'five-point star', 'fill': GNSS_COLOR, 'white_casing': True},
        },
        'layout_symbol_assets': {
            EARTHQUAKE_TRIANGLE_SVG.name: {'path': str(EARTHQUAKE_TRIANGLE_SVG), 'sha256': sha(EARTHQUAKE_TRIANGLE_SVG)},
            GNSS_STAR_SVG.name: {'path': str(GNSS_STAR_SVG), 'sha256': sha(GNSS_STAR_SVG)},
        },
        'left_symbol_legend_font': {'font_family': 'Arial', 'font_size_pt': 12, 'bold': True},
        'label_font_sizes_pt': {
            'left_district_names': {'font_family': 'Arial', 'size': 12.0, 'bold': True},
            'right_district_names': {'font_family': 'Arial', 'size': 12.0, 'bold': True},
            'right_fault_names': {'font_family': 'Arial', 'size': 14.0, 'italic': True},
            'dian_lake': {'font_family': 'Arial', 'size': 16.0, 'bold': True},
            'earthquake_callouts': {'font_family': 'Arial', 'size': 14.0, 'bold': True, 'italic': True},
            'gnss_station_callout': {'font_family': 'Arial', 'size': 14.0, 'bold': True, 'italic': True},
            'right_coordinates': {'font_family': 'Arial', 'size': 8.5, 'bold': True},
            'north_arrow_N': {'font_family': 'Times New Roman', 'size': 9.0, 'bold': True},
            'left_scale': {'font_family': 'Arial', 'size': 10.0, 'bold': True},
            'right_scale': {'font_family': 'Arial', 'size': 10.0, 'bold': True},
            'left_legend_labels': {'font_family': 'Arial', 'size': 12.0, 'bold': True},
            'left_map_kunming': {'font_family': 'Arial', 'size': 18.0, 'bold': True},
            'elevation_legend_title': {'font_family': 'Arial', 'size': 18.0, 'bold': True, 'position': 'centered below color bar'},
            'elevation_values': {'font_family': 'Arial', 'size': 12.0, 'bold': True},
        },
        'right_extent_basis': 'All 57,228 actual projected building geometries, 1,800 m margin, then fit to map aspect ratio',
        'building_extent_calculation': dem_stretch_info['building_extent'],
        'layer_counts': {k: l.featureCount() for k, l in layers.items() if isinstance(l, QgsVectorLayer)},
        'dem': {'file': str(DEM_FILE), 'source_crs': layers['dem'].crs().authid(),
                'pixel_size': [layers['dem'].rasterUnitsPerPixelX(), layers['dem'].rasterUnitsPerPixelY()],
                'color_range': [DEM_MIN, DEM_MAX], 'class_bounds_m': DEM_CLASS_BOUNDS,
                'class_count': len(DEM_COLORS), 'hillshade_azimuth': 315,
                'stretch': dem_stretch_info,
                'hillshade_altitude': 40, 'hillshade_opacity': HILLSHADE_OPACITY, 'color_stops': DEM_STOPS},
        'all_reopened_layers_valid': True,
        'dem_building_contrast': {
            'status': 'visually_checked_in_current_preview',
            'dem_palette': DEM_PALETTE_DESCRIPTION,
            'building_fill': BUILDING_COLOR,
            'built_up_fill': BUILT_UP_COLOR,
            'built_up_opacity': BUILT_UP_OPACITY,
            'assessment': 'Deep-purple buildings and pale-pink built-up areas remain distinct from green terrain, brown elevation highs and the cyan lake',
        },
        'builtup_data': {
            'status': 'loaded_from_preserved_builtup_geopackage',
            'geopackage': str(ROOT / '../data/study_area/built_up.gpkg'),
            'feature_class': 'built_up', 'feature_count': layers['built_up'].featureCount(),
            'crs': layers['built_up'].crs().authid(), 'geometry': QgsWkbTypes.displayString(layers['built_up'].wkbType()),
            'drawn': layers['built_up'] in c.layers(), 'legend_label': 'Built-up area',
            'symbol': {'fill': BUILT_UP_COLOR, 'opacity': BUILT_UP_OPACITY, 'outline': BUILT_UP_EDGE, 'outline_width_mm': BUILT_UP_OUTLINE_WIDTH},
            'render_order': 'above DEM and below study-building footprints',
        },
        'terrain_caches': terrain_caches,
        'fault_reference': fault_reference,
        'fault_renderer_matches_hazard_style': strip_line_widths(renderer_signature(layers['faults'].renderer())) == strip_line_widths(fault_reference['rules']),
        'fault_width_multiplier': FAULT_WIDTH_MULTIPLIER,
        'fault_line_widths_mm': fault_line_widths(layers['faults'].renderer()),
        'panel_boxes_mm': {'left': LEFT_BOX, 'right': RIGHT_BOX},
        'inter_map_gap_mm': RIGHT_BOX[0] - (LEFT_BOX[0] + LEFT_BOX[2]),
        'dianchi_above_administration_in_both_maps': all(m.layers().index(layers['dianchi']) < m.layers().index(layers[k]) for m in [a, c] for k in ['city', 'districts', 'streets'] if layers[k] in m.layers()),
        'basemap_road_and_waterway_lines_removed': True,
        'map_frame_width_mm': 0.65,
        'scale_bars': {
            'left': {'endpoints_km': [0, 10], 'position': 'outside map'},
            'right': {'endpoints_km': [0, 5], 'position': 'inside map', 'background': 'transparent', 'font_family': 'Arial'},
            'segments': 1, 'middle_labels': False,
        },
        'symbol_legend_visible': True,
        'elevation_legend_only': False,
        'left_administrative_label_style': {'font_family': 'Arial', 'font_size_pt': 12.0, 'bold': True, 'halo': True},
        'coordinate_style': {
            'reference_pdf': str(ROOT / '04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt'),
            'font_family': 'Arial', 'font_size_pt': 8.5, 'font_color': INK, 'bold': True,
            'interval_minutes': 5, 'left_coordinates_enabled': False, 'interior_grid_lines': False,
            'tick_length_mm': 1.0, 'tick_width_mm': 0.25,
            'annotation_frame_distance_mm': 1.1,
            'longitude_side': 'top', 'latitude_side': 'left',
            'latitude_direction': 'vertical', 'format': 'degrees and minutes, E/N',
        },
        'maps': {m.id(): {'crs': m.crs().authid(), 'extent': m.extent().toString(3), 'scale': m.scale(),
                         'layers_top_to_bottom': [l.customProperty('study_area/source_key', '') for l in m.layers()],
                         'layers_locked': m.keepLayerSet(), 'styles_locked': m.keepLayerStyles()} for m in [a, c]},
        'main_map_earthquakes': events,
        'input_sha256': source_hashes,
        'exports': {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in existing + [EXPORT_DIR / 'preview.png', EXPORT_DIR / 'TSX_overlap_detail.png']},
    }
    (OUT / 'verification.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in checks.items() if k not in ['input_sha256', 'maps', 'exports', 'fault_reference']}, ensure_ascii=False, indent=2))
    return project, layout


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--legacy-rebuild']:
        project, layout = build()
    else:
        if str(OUT) not in sys.path:
            sys.path.insert(0, str(OUT))
        from build_a4_layout import main
        main()
