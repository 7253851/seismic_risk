# -*- coding: utf-8 -*-
"""2026-10-14: single-panel hazard layout matching the supplied reference extent.

Run with the QGIS bundled Python, QT_QPA_PLATFORM=offscreen and PROJ_DATA set.
Only presentation is changed; source geometry and hazard values remain intact.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile

from qgis.core import *
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPolygonF

from qgis_paths import ROOT as BASE
from hillshade_support import HILLSHADE_FILE, ensure_hillshade, SERVICE as HILLSHADE_SERVICE, OPACITY as HILLSHADE_OPACITY, COLORS as HILLSHADE_COLORS
PROJECT = BASE / '04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz'
RECORD = Path(os.environ.get('SEISMIC_LAYOUT_RECORD', str(BASE / '04_seismic_hazard/output/qgis/current_layout_record')))
OUT = BASE / '04_seismic_hazard/output/qgis'
STYLE_DIR = BASE / '04_seismic_hazard/qgis/layouts/hazard/print_styles'
NAME = 'Kunming_Hazard_PGA'
PAGE_MM = (195, 211)
MAP_TOP_MM = 8.5
MAP_HEIGHT_MM = 190
SIDE_PADDING_M = 300
BUILDING_PT = 0.1
DISTRICT_PT = 2.0
MAP_FRAME_MM = 0.45
TICK_LENGTH_MM = 1.8
TICK_WIDTH_MM = 0.40
GRATICULE_LABEL_GAP_MM = 1.2
FAULT_WIDTH_MM = 0.60
FAULT_COLOR = '#8A3E32'
FAULT_ARROW_INTERVAL_MM = 24
FAULT_ARROW_SVG = BASE / '04_seismic_hazard/qgis/layouts/hazard/left_lateral_arrows.svg'
HISTORICAL_EQ_COLOR = '#E22D32'
HISTORICAL_EQ_SIZE_MM = 3.8
EVENT_2026_COLOR = HISTORICAL_EQ_COLOR
EVENT_2026_SIZE_MM = HISTORICAL_EQ_SIZE_MM
DISTRICT_LABEL_PT = 14
LAKE_LABEL_PT = 18
FAULT_LABEL_PT = 11.5
EVENT_LABEL_PT = 12
EVENT_2026_DATE = '2026-09-30'
EVENT_2026_MAGNITUDE = 4.3

spec = importlib.util.spec_from_file_location('previous_layout_helpers', BASE / 'shared/qgis/scripts/layout_support.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
CLASSES = previous.CLASSES


def fmt(size=9, color='#24282B'):
    font = QFont('Arial')
    font.setPointSizeF(size)
    font.setBold(True)
    f = QgsTextFormat()
    f.setFont(font)
    f.setSize(size)
    f.setColor(QColor(color))
    return f


def label(layout, id_, text, box, size=9, color='#24282B', center=False, halo=False):
    item = QgsLayoutItemLabel(layout)
    item.setId(id_)
    item.setText(text)
    f = fmt(size, color)
    if halo:
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(0.55)
        buffer.setColor(QColor('white'))
        f.setBuffer(buffer)
    item.setTextFormat(f)
    item.setMargin(0)
    item.setHAlign(Qt.AlignHCenter if center else Qt.AlignLeft)
    item.setVAlign(Qt.AlignVCenter)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(*box[:2]))
    item.attemptResize(QgsLayoutSize(*box[2:]))
    return item


def building_renderer():
    renderer = QgsRuleBasedRenderer(QgsFillSymbol.createSimple({'outline_style': 'no'}))
    root = renderer.rootRule()
    root.removeChildAt(0)
    for name, expr, color in CLASSES:
        # A darker edge in the same hue preserves class legibility at regional scale.
        symbol = QgsFillSymbol.createSimple({
            'color': color, 'outline_color': QColor(color).darker(130).name(),
            'outline_style': 'solid', 'joinstyle': 'miter',
        })
        sl = symbol.symbolLayer(0)
        sl.setStrokeWidth(BUILDING_PT)
        sl.setStrokeWidthUnit(Qgis.RenderUnit.Points)
        rule = QgsRuleBasedRenderer.Rule(symbol)
        rule.setLabel(name)
        rule.setFilterExpression(expr)
        root.appendChild(rule)
    return renderer


def fault_symbol(left_lateral=False, legend=False):
    """Thick fault trace; paired arrows only for records explicitly marked left-lateral."""
    symbol = QgsLineSymbol.createSimple({
        'line_color': '#FFFFFF', 'line_width': str(FAULT_WIDTH_MM + 0.20),
        'line_width_unit': 'MM', 'capstyle': 'round', 'joinstyle': 'round',
    })
    symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({
        'line_color': FAULT_COLOR, 'line_width': str(FAULT_WIDTH_MM),
        'line_width_unit': 'MM', 'capstyle': 'round', 'joinstyle': 'round',
    }))
    if left_lateral:
        arrows = QgsMarkerLineSymbolLayer.create({
            'placements': 'CentralPoint' if legend else 'Interval',
            'interval': str(FAULT_ARROW_INTERVAL_MM), 'interval_unit': 'MM',
            'offset_along_line': '0' if legend else str(FAULT_ARROW_INTERVAL_MM / 2),
            'offset_along_line_unit': 'MM', 'rotate': '1',
            'average_angle_length': '1.5', 'average_angle_unit': 'MM',
        })
        marker = QgsMarkerSymbol()
        marker.changeSymbolLayer(0, QgsSvgMarkerSymbolLayer.create({
            'name': str(FAULT_ARROW_SVG), 'size': '5.5', 'size_unit': 'MM', 'angle': '0',
        }))
        arrows.setSubSymbol(marker)
        symbol.appendSymbolLayer(arrows)
    return symbol


def fault_renderer():
    renderer = QgsRuleBasedRenderer(fault_symbol())
    root = renderer.rootRule()
    root.removeChildAt(0)
    left = QgsRuleBasedRenderer.Rule(fault_symbol(left_lateral=True))
    left.setLabel('Left-lateral faults')
    left.setFilterExpression('trim("Fea_Ch") = \'左旋\'')
    root.appendChild(left)
    general = QgsRuleBasedRenderer.Rule(fault_symbol())
    general.setLabel('Faults')
    general.setIsElse(True)
    root.appendChild(general)
    return renderer


def earthquake_symbol(event_2026=False, legend=False):
    """Both earthquake events use the study-area map's red triangle."""
    from map_series_support import reference_point_symbol
    return reference_point_symbol(legend=legend)


def line_key(layout, id_, xy, length, symbol, vertical=False):
    end = QPointF(0, length) if vertical else QPointF(length, 0)
    item = QgsLayoutItemPolyline(QPolygonF([QPointF(0, 0), end]), layout)
    item.setId(id_)
    item.setSymbol(symbol)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(*xy))
    return item


def map_annotations(layout, main, layers, project):
    """Curated English labels, with line-parallel fault names and point callouts."""
    extent = main.extent()
    box = (main.pos().x(), main.pos().y(), main.sizeWithUnits().width(), main.sizeWithUnits().height())
    wgs = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(wgs, main.crs(), project)
    items, leaders, entries = [], [], []

    def xy(lon, lat):
        point = tr.transform(QgsPointXY(lon, lat))
        return (box[0]+(point.x()-extent.xMinimum())/extent.width()*box[2],
                box[1]+(extent.yMaximum()-point.y())/extent.height()*box[3])

    def text(id_, value, center, size, dimensions, color='#24282B', angle=0, halo=True):
        cx, cy = center
        width, height = dimensions
        item = label(layout, id_, value, (cx-width/2,cy-height/2,width,height),
                     size, color, center=True, halo=halo)
        item.setBackgroundEnabled(False)
        if angle:
            item.setItemRotation(angle, True)
        items.append(item)
        entries.append({'id':id_, 'text':value, 'font_pt':size, 'center_mm':center, 'rotation':angle})
        return item

    def callout(id_, value, anchor, center, dimensions, size, color, target=None, marker_clearance=2.8):
        text(id_, value, center, size, dimensions, color)
        cx, cy = center
        if target is None:
            target = (max(cx-dimensions[0]/2,min(anchor[0],cx+dimensions[0]/2)),
                      max(cy-dimensions[1]/2,min(anchor[1],cy+dimensions[1]/2)))
        dx, dy = target[0]-anchor[0], target[1]-anchor[1]
        distance = (dx*dx+dy*dy)**0.5
        start = (anchor[0]+dx/distance*marker_clearance, anchor[1]+dy/distance*marker_clearance)
        left, top = min(start[0],target[0]), min(start[1],target[1])
        poly = QPolygonF([QPointF(start[0]-left,start[1]-top),QPointF(target[0]-left,target[1]-top)])
        leader = QgsLayoutItemPolyline(poly, layout)
        leader.setId('Leader_'+id_)
        symbol = QgsLineSymbol.createSimple({'line_color':'#FFFFFF','line_width':'0.60','capstyle':'round'})
        symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color':color,'line_width':'0.20','capstyle':'round'}))
        leader.setSymbol(symbol)
        layout.addLayoutItem(leader)
        leader.attemptMove(QgsLayoutPoint(left,top))
        leaders.append(leader)

    for name, lon, lat in [
        ('Wuhua',102.682,25.105), ('Panlong',102.789,25.094),
        ('Xishan',102.601,25.055), ('Guandu',102.910,25.036),
        ('Chenggong',102.897,24.898),
    ]:
        text(name, name, xy(lon,lat), DISTRICT_LABEL_PT, (30 if name == 'Xishan' else 40,7))
    text('Dian_Lake', 'Dian Lake', xy(102.718,24.873), LAKE_LABEL_PT, (49,9), '#153B50', halo=False)

    fault_features = {str(f['fault_uid']):f for f in layers['faults'].getFeatures()}
    for uid, id_, center, width, angle in [
        ('KMF_0013','Fault_Puduhe',(43,29),34,-78),
        ('KMF_0007','Fault_Heilongtan',(96,97),56,-88),
        ('KMF_0000','Fault_Baiyi',(142,39),53,-88),
        ('KMF_0009','Fault_Machang',(27,89),44,-48),
        ('KMF_0003','Fault_Dachunhe',(163.5,100.5),57,-42),
    ]:
        feature = fault_features[uid]
        text(id_, str(feature['FN_En']), center, FAULT_LABEL_PT, (width,6), FAULT_COLOR, angle)
        entries[-1]['fault_uid'] = uid
    callout('Fault_Xiaojiang', 'Xiaojiang fault\n(western branch)', xy(102.9673,24.773),
            (163,181),(44,12),FAULT_LABEL_PT,FAULT_COLOR,target=(178,187),marker_clearance=0)
    entries[-1]['fault_uid'] = 'KMF_0022'
    # Unnamed fault traces remain visible, without text or leader annotations.

    clip = map_polygon(extent,main.crs(),layers['earthquakes'].crs(),project)
    historical = [f for f in layers['earthquakes'].getFeatures() if f.geometry().intersects(clip)]
    for index, feature in enumerate(historical):
        date = str(feature['发震时']).split()[0]
        magnitude = float(feature['震级_M_'])
        anchor = xy(float(feature['经度___']),float(feature['纬度___']))
        center = (27,48.5) if index == 0 else (anchor[0]+17,anchor[1]-11)
        callout('Historical_event_'+str(index), f'{date}\nMw {magnitude:.1f}', anchor, center,
                (32,11.5),EVENT_LABEL_PT,HISTORICAL_EQ_COLOR,target=(34,54) if index == 0 else None)
    event = next(layers['event_2026'].getFeatures())
    callout('Event_2026_annotation', f'{EVENT_2026_DATE}\nMw {EVENT_2026_MAGNITUDE:.1f}',
            xy(float(event['longitude']),float(event['latitude'])),(105,23.5),(36,11.5),
            EVENT_LABEL_PT,EVENT_2026_COLOR,target=(98,29.25),marker_clearance=4.2)
    return items, leaders, entries


def contextual_legend(layout, map_, map_box):
    """Keep the PGA row in place; transparent earthquake/fault keys inside the map."""
    left, top, width, height = map_box
    bottom = top + height
    label(layout, 'Legend_title', 'PGA (g)', (left,bottom+3,18,5.5), 9)
    step = (width-19)/5
    for index, (name, expr, color) in enumerate(CLASSES):
        x = left + 19 + index*step
        previous.rectangle(layout, 'Legend_class_'+str(index), (x,bottom+4.3,5,3), color, width='0')
        label(layout, 'Legend_range_'+str(index), name, (x+6.5,bottom+2.5,step-6.7,6), 8)

    inset_left = left+2.5

    def key_label(id_, text, x, y, width):
        item = label(layout,id_,text,(x,y-2.5,width,5),8.5,halo=True)
        item.setBackgroundEnabled(False)
        text_format = item.textFormat()
        buffer = text_format.buffer()
        buffer.setSize(.35)
        text_format.setBuffer(buffer)
        item.setTextFormat(text_format)
        return item

    for id_, is_event, y, text in [
        ('Historical_eq', False, bottom-28.5, '2023 earthquake'),
        ('Event_2026', True, bottom-23, '2026 earthquake'),
    ]:
        key = QgsLayoutItemMarker(layout)
        key.setId(id_ + '_legend_symbol')
        key.setSymbol(earthquake_symbol(event_2026=is_event, legend=True))
        layout.addLayoutItem(key)
        key.setBackgroundEnabled(False)
        key.attemptMove(QgsLayoutPoint(inset_left+2.5,y))
        key_label(id_+'_legend_label',text,inset_left+7,y,28.5)
    line_key(layout,'Fault_legend_symbol',(inset_left,bottom-17.5),8.5,fault_symbol())
    key_label('Fault_legend_label','Faults',inset_left+10.5,bottom-17.5,25)
    line_key(layout,'Left_lateral_legend_symbol',(inset_left,bottom-12),10.5,fault_symbol(left_lateral=True,legend=True))
    key_label('Left_lateral_legend_label','Left-lateral',inset_left+12.5,bottom-12,23)

    scale = previous.scale_bar(layout, map_, 'Overview_scale', (inset_left,bottom-7), Qgis.DistanceUnit.Kilometers, 2, 'km')
    scale.setNumberOfSegments(1)
    scale.setNumberOfSegmentsLeft(0)
    scale.setTextFormat(fmt(8))
    scale.setLabelBarSpace(0.8)
    scale.setHeight(0.8)
    scale.setBoxContentSpace(0)
    scale.setBackgroundEnabled(False)
    scale.attemptResize(QgsLayoutSize(0, 0))


def locked_styles(layers):
    overrides = {}
    clones = []
    for key, source in layers.items():
        layer = source.clone()
        clones.append(layer)
        layer.setLabelsEnabled(False)
        layer.setOpacity(1)
        layer.setScaleBasedVisibility(False)
        layer.setBlendMode(QPainter.CompositionMode_SourceOver)
        simplify = QgsVectorSimplifyMethod()
        simplify.setSimplifyHints(Qgis.VectorRenderingSimplificationFlag.NoSimplification)
        layer.setSimplifyMethod(simplify)
        if key == 'hazard':
            layer.setRenderer(building_renderer())
        elif key == 'faults':
            layer.setRenderer(fault_renderer())
        elif key in ('earthquakes', 'event_2026'):
            layer.setRenderer(QgsSingleSymbolRenderer(earthquake_symbol(event_2026=(key == 'event_2026'))))
        elif key == 'districts':
            symbol = QgsFillSymbol.createSimple({'style': 'no', 'outline_color': '#363C40', 'joinstyle': 'round'})
            symbol.symbolLayer(0).setStrokeWidth(DISTRICT_PT)
            symbol.symbolLayer(0).setStrokeWidthUnit(Qgis.RenderUnit.Points)
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        elif key == 'dianchi':
            layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'color': '#60BDE3', 'outline_style': 'no'})))
        elif key == 'waterways':
            layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({'line_color': '#CBE4EF', 'line_width': '0.12'})))
        elif key == 'roads':
            renderer = QgsRuleBasedRenderer(QgsLineSymbol.createSimple({'line_color': '#C6CBCE', 'line_width': '0.08'}))
            root = renderer.rootRule()
            root.removeChildAt(0)
            for expr, width, color in [
                ("\"kind\" IN ('motorway','trunk','primary')", '0.16', '#B9C0C4'),
                ("\"kind\" IN ('secondary','tertiary')", '0.09', '#CCD1D4'),
                ("\"kind\" NOT IN ('motorway','trunk','primary','secondary','tertiary')", '0.055', '#E0E3E5'),
            ]:
                rule = QgsRuleBasedRenderer.Rule(QgsLineSymbol.createSimple({'line_color': color, 'line_width': width}))
                rule.setFilterExpression(expr)
                root.appendChild(rule)
            layer.setRenderer(renderer)
        overrides[source.id()] = previous.xml_style(layer)
        layer.saveNamedStyle(str(STYLE_DIR / (key + '.qml')))
    return overrides, clones


def map_polygon(extent, map_crs, source_crs, project):
    polygon = QgsGeometry.fromRect(extent).densifyByCount(30)
    polygon.transform(QgsCoordinateTransform(map_crs, source_crs, project))
    return polygon


def tight_horizontal_extent(hazard, original, crs, project):
    """Fit the current mapped buildings with small side margins, retaining N/S extent."""
    clip = map_polygon(original, crs, hazard.crs(), project)
    transform = QgsCoordinateTransform(hazard.crs(), crs, project)
    bounds = None
    request = QgsFeatureRequest().setFilterRect(clip.boundingBox()).setNoAttributes()
    for feature in hazard.getFeatures(request):
        geometry = feature.geometry()
        if geometry.intersects(clip):
            geometry.transform(transform)
            if bounds is None:
                bounds = geometry.boundingBox()
            else:
                bounds.combineExtentWith(geometry.boundingBox())
    if bounds is None:
        raise RuntimeError('No buildings found in the existing map extent')
    return QgsRectangle(bounds.xMinimum()-SIDE_PADDING_M, original.yMinimum(),
                        bounds.xMaximum()+SIDE_PADDING_M, original.yMaximum())


def spatial_audit(hazard, districts, old_extent, new_extent, crs, project):
    old = map_polygon(old_extent, crs, hazard.crs(), project)
    new = map_polygon(new_extent, crs, hazard.crs(), project)
    chenggong = next(f.geometry() for f in districts.getFeatures() if f['name'] == '呈贡区')
    chenggong.transform(QgsCoordinateTransform(districts.crs(), hazard.crs(), project))
    engines = []
    for geometry in [old, new, chenggong]:
        engine = QgsGeometry.createGeometryEngine(geometry.constGet())
        engine.prepareGeometry()
        engines.append(engine)
    counts = Counter()
    classes = [0] * 5
    for f in hazard.getFeatures(QgsFeatureRequest().setSubsetOfAttributes(['PGA_Final_g', 'PGA_Class'], hazard.fields())):
        geometry = f.geometry()
        in_old = engines[0].intersects(geometry.constGet())
        in_new = engines[1].intersects(geometry.constGet())
        in_cg = engines[2].intersects(geometry.constGet())
        counts['old_total'] += in_old
        counts['new_total'] += in_new
        counts['restored_total'] += in_new and not in_old
        counts['lost_total'] += in_old and not in_new
        counts['chenggong_source'] += in_cg
        counts['chenggong_old'] += in_cg and in_old
        counts['chenggong_new'] += in_cg and in_new
        counts['chenggong_restored'] += in_cg and in_new and not in_old
        if in_new:
            classes[[item[0] for item in CLASSES].index(str(f['PGA_Class']))] += 1
    return dict(counts), classes


def revise():
    for folder in [RECORD, OUT, STYLE_DIR]: folder.mkdir(parents=True, exist_ok=True)
    project = QgsProject.instance()
    if not project.read(str(PROJECT)):
        raise RuntimeError('Project could not be loaded')
    with tempfile.NamedTemporaryFile(prefix='kunming_hazard_before_',suffix='.qgz',delete=False) as temporary:
        stage_backup = Path(temporary.name)
    shutil.copy2(PROJECT, stage_backup)
    initial_digest = previous.digest(PROJECT)
    original_ids = set(project.mapLayers())
    visibility = {n.layerId(): n.itemVisibilityChecked() for n in project.layerTreeRoot().findLayers()}
    layout = project.layoutManager().layoutByName(NAME)
    main = layout.itemById('Hazard_Main_Map')
    old_extent = QgsRectangle(main.extent())
    crs = QgsCoordinateReferenceSystem('EPSG:4543')
    wgs = QgsCoordinateReferenceSystem('EPSG:4326')
    if not crs.isValid() or not wgs.isValid():
        raise RuntimeError('PROJ_DATA must point to the QGIS bundled proj directory')
    layers = {k: previous.source_layer(project, 'seismic_building/base_key', k) for k in ['districts', 'streets', 'dianchi', 'faults']}
    layers['earthquakes'] = previous.source_layer(project, 'seismic_building/base_key', 'earthquakes_local')
    # The existing user-supplied event point is the 2026 event identified by the user.
    # Its source has no date or magnitude field: do not invent or modify either.
    layers['event_2026'] = previous.source_layer(project, 'seismic_building/validation_role', 'epicenter')
    layers['hazard'] = previous.source_layer(project, 'seismic_building/result_key', 'hazard')
    for key in ['waterways']:
        layers[key] = previous.source_layer(project, 'seismic_building/print_base', key)
    hazard = layers['hazard']
    if hazard.subsetString():
        raise RuntimeError('Unexpected building data filter')
    hashes = {l.source().split('|')[0]: previous.digest(l.source().split('|')[0]) for l in layers.values()}
    with sqlite3.connect(Path(hazard.source().split('|')[0]).as_uri() + '?mode=ro', uri=True) as con:
        counts = [con.execute('SELECT count(*) FROM building_hazard WHERE ' + expr).fetchone()[0] for _, expr, _ in CLASSES]
    if counts != previous.EXPECTED_COUNTS:
        raise RuntimeError('Hazard classification counts changed')
    overrides, clones = locked_styles(layers)
    for item in list(layout.items()):
        if isinstance(item, QgsLayoutItem) and not isinstance(item, QgsLayoutItemPage) and item is not main:
            layout.removeLayoutItem(item)
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(*PAGE_MM))
    layout.renderContext().setDpi(1200)
    layout.setCustomProperty('seismic_building/print_optimized', 'english_map_annotations_v12')
    extent = tight_horizontal_extent(hazard, old_extent, crs, project)
    map_box = (10, MAP_TOP_MM, MAP_HEIGHT_MM*extent.width()/extent.height(), MAP_HEIGHT_MM)
    ordered = [layers[k] for k in ['event_2026', 'earthquakes', 'faults', 'dianchi', 'districts', 'streets', 'hazard', 'waterways']]
    terrain = None
    if HILLSHADE_FILE.exists():
        terrain = ensure_hillshade(project)
        overrides[terrain.id()] = previous.xml_style(terrain)
        terrain.saveNamedStyle(str(STYLE_DIR/'hillshade.qml'))
        ordered.append(terrain)
    previous.configure_map(main, map_box, ordered, overrides, extent, crs)
    main.setBackgroundColor(QColor('white'))
    main.setFrameStrokeWidth(QgsLayoutMeasurement(MAP_FRAME_MM))
    main.setFrameStrokeColor(QColor('#24282B'))
    main.setZValue(1)
    project.setBackgroundColor(QColor('white'))
    layout.setReferenceMap(main)
    grid = main.grid()
    grid.setEnabled(True)
    grid.setCrs(wgs)
    grid.setIntervalX(1/12)
    grid.setIntervalY(1/12)
    grid.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly)
    grid.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
    grid.setFramePenSize(TICK_WIDTH_MM)
    grid.setFrameWidth(TICK_LENGTH_MM)
    grid.setAnnotationEnabled(True)
    grid.setAnnotationTextFormat(fmt(12))
    grid.setAnnotationFrameDistance(GRATICULE_LABEL_GAP_MM)
    grid.setAnnotationFormat(QgsLayoutItemMapGrid.CustomFormat)
    grid.setAnnotationExpression("to_string(floor(round(@grid_number*60)/60)) || '°' || to_string(round(@grid_number*60)%60) || '′' || if(@grid_axis='x','E','N')")
    for border in [grid.Top, grid.Left, grid.Bottom, grid.Right]:
        grid.setAnnotationPosition(grid.OutsideMapFrame, border)
        grid.setAnnotationDisplay(grid.LongitudeOnly if border == grid.Top else grid.LatitudeOnly if border == grid.Left else grid.HideAll, border)
        grid.setAnnotationDirection(grid.Vertical if border == grid.Left else grid.Horizontal, border)
    right = map_box[0] + map_box[2]
    north_text = label(layout, 'North_text', 'N',
        (right-18,map_box[1]+4,14,4), 10.5, center=True)
    north_text.setBackgroundEnabled(False)
    arrow = QgsLayoutItemPicture(layout)
    arrow.setId('True_North_Arrow')
    arrow.setBackgroundEnabled(False)
    layout.addLayoutItem(arrow)
    arrow.attemptMove(QgsLayoutPoint(right-14.75,map_box[1]+9))
    arrow.attemptResize(QgsLayoutSize(7.5,12.5))
    arrow.setPicturePath(str(BASE / '04_seismic_hazard/qgis/layouts/hazard/north_arrow.svg'))
    arrow.setLinkedMap(main)
    arrow.setNorthMode(QgsLayoutItemPicture.TrueNorth)
    contextual_legend(layout, main, map_box)
    annotation_items, annotation_leaders, annotation_entries = map_annotations(layout, main, layers, project)
    for item in layout.items():
        if isinstance(item, QgsLayoutItem) and item is not main and not isinstance(item, QgsLayoutItemPage):
            item.setZValue(5)
    north_text.setZValue(6)
    arrow.setZValue(6)
    for item in annotation_leaders:
        item.setZValue(4)
    for item in annotation_items:
        item.setZValue(7)
    audit, main_counts = spatial_audit(hazard, layers['districts'], old_extent, extent, crs, project)
    if audit['lost_total']:
        raise RuntimeError('The compact frame cropped buildings visible in the previous layout')
    if audit['chenggong_new'] < audit['chenggong_old']:
        raise RuntimeError('Extent failed to restore Chenggong buildings')
    if audit['chenggong_new'] != audit['chenggong_source']:
        raise RuntimeError('The southern edge still crops source buildings in Chenggong')
    if audit['new_total'] < 0.99 * hazard.featureCount():
        raise RuntimeError('Reference extent should include at least 99% of the source buildings')
    print('Spatial audit:', json.dumps(audit, ensure_ascii=False), flush=True)
    print('Exporting street-level 1200 dpi PNG', flush=True)
    from map_series_support import export_layout,save_template
    point_symbols = export_layout(layout,OUT,'Kunming_Building_Hazard')
    save_template(layout,BASE/'04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt')
    if any(previous.digest(p) != h for p,h in hashes.items()):
        raise RuntimeError('Source data changed')
    assert original_ids.issubset(set(project.mapLayers()))
    assert {n.layerId():n.itemVisibilityChecked() for n in project.layerTreeRoot().findLayers()} == visibility
    assert previous.digest(PROJECT) == initial_digest, 'Concurrent external project change'
    previous.preserve_gui_and_save(project, None, stage_backup)
    report = {
        'time': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'project': str(PROJECT), 'layout': NAME, 'page_mm': PAGE_MM, 'main_map_mm': map_box,
        'main_extent_before': old_extent.toString(12), 'main_extent_after':extent.toString(12),
        'main_extent_wgs84':QgsCoordinateTransform(crs,wgs,project).transformBoundingBox(extent).toString(12),
        'main_scale_after':main.scale(), 'main_map_width_km':extent.width()/1000,
        'main_map_height_km':extent.height()/1000, 'side_padding_m':SIDE_PADDING_M,
        'main_building_count':audit['new_total'], 'main_coverage_fraction':audit['new_total']/hazard.featureCount(),
        'main_class_counts':main_counts, 'spatial_audit':audit,
        'feature_count':hazard.featureCount(), 'classes':[{'label':a,'expression':b,'color':c,'count':n} for (a,b,c),n in zip(CLASSES,counts)],
        'source_sha256':hashes, 'geometry_and_pga_unchanged':True,
        'background_color':'#FFFFFF', 'district_boundary_pt':DISTRICT_PT,
        'map_frame_width_mm':MAP_FRAME_MM,
        'building_outline_pt':BUILDING_PT, 'lake_above_administrative_boundaries':True,
        'administrative_boundaries_above_buildings':True,
        'geographic_labels_removed':[],
        'map_annotation_entries':annotation_entries,
        'map_annotation_language':'English',
        'scale_bar_outside_map':False, 'north_arrow_inside_map':True,
        'north_arrow_background':'transparent',
        'title_and_footer_removed':True,
        'context_legend_entries':point_symbols['legend_entries'], 'reference_point_symbols':point_symbols,
        'context_legend_position':'inside map, lower left', 'context_legend_background':'transparent',
        'only_current_version_retained':True,
        'main_map_layers':[l.name() for l in ordered], 'detail_maps':[], 'locator_boxes':[],
        'font_family':'Arial', 'all_text_bold':True, 'dpi':1200,
        'graticule_font_size_pt':12,
        'graticule_tick_length_mm':TICK_LENGTH_MM, 'graticule_tick_width_mm':TICK_WIDTH_MM,
        'graticule_annotation_gap_mm':GRATICULE_LABEL_GAP_MM,
        'scale_bar_segments':1, 'scale_bar_km':2,
        'fault_overlay':{'source':layers['faults'].source(), 'source_feature_count':layers['faults'].featureCount(),
                         'labels_enabled':False, 'color':FAULT_COLOR, 'width_mm':FAULT_WIDTH_MM,
                         'symbol':'solid trace with white casing; paired arrows for explicitly left-lateral records',
                         'arrow_filter':'trim("Fea_Ch") = \'左旋\'',
                         'arrow_interval_mm':FAULT_ARROW_INTERVAL_MM,
                         'arrow_svg':str(FAULT_ARROW_SVG),
                         'symbol_reference':'https://pubs.usgs.gov/tm/2006/11A02/'},
        'earthquake_overlay':{
            'historical_source':layers['earthquakes'].source(),
            'historical_source_count':layers['earthquakes'].featureCount(),
            'historical_symbol':'red filled triangle with white casing',
            'historical_size_mm':HISTORICAL_EQ_SIZE_MM,
            'event_2026_source':layers['event_2026'].source(),
            'event_2026_symbol':'red triangle with white casing',
            'event_2026_size_mm':EVENT_2026_SIZE_MM,
            'event_2026_date':EVENT_2026_DATE, 'event_2026_magnitude':EVENT_2026_MAGNITUDE,
            'date_magnitude_source':'User supplied 4.3 and 9.30 in the context of the 2026 earthquake',
            'event_year_basis':'User identifies the existing supplied epicenter as the 2026 event; source has no date or magnitude field',
            'labels_enabled':False,
        },
        'hillshade':({'source':HILLSHADE_SERVICE,'opacity':HILLSHADE_OPACITY,
                      'color_ramp':HILLSHADE_COLORS,
                      'local_raster':str(HILLSHADE_FILE)} if terrain else None),
        'png':str(OUT/'Kunming_Building_Hazard_1200dpi.png'),'export_format':'PNG','export_dpi':1200,
        'administrative_level':'five county-level districts + township/subdistrict','county_boundary_pt':2.0,'street_boundary_pt':.6,'basemap_roads_visible':False,
        'follow_theme':False, 'locked_layers_and_styles':True,
        'original_layers_retained':True, 'original_visibility_preserved':True,
        'project_saved':True, 'exports_success':True,
    }
    for path in [RECORD/'verification_summary.json', OUT/'hazard_print_report.json']:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    stage_backup.unlink(missing_ok=True)
    print('Saved', PROJECT, flush=True)
    return report


if __name__ in ('__main__', '__console__'):
    if not QgsApplication.instance():
        app = QgsApplication([], False)
        app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis', True)
        app.initQgis()
    from qgis.utils import iface
    if iface and QgsProject.instance().isDirty():
        raise RuntimeError('请先保存当前工程后再修改布局。')
    revise()
    if not iface:
        os._exit(0)
