"""Build the local event-validation distribution map with the existing street basemap.

Run from the workspace with plot/shared/qgis/scripts/run_pyqgis.sh <this file>.
All inputs are read-only; the new project, local vectors and exports live in 讨论5.2.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os

from qgis.core import *
from qgis.PyQt.QtCore import Qt, QVariant, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QPolygonF

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'plot/13_event_validation/output'
QGIS_DIR = ROOT / 'plot/13_event_validation/qgis/support'
DATA_DIR = ROOT / 'result/intermediate/13_event_validation/cartography'
FIG_DIR = OUT / 'derived'
CHECK_DIR = OUT / 'checks'
STEM = '5_2_event_spatial_distribution'
PROJECT = QGIS_DIR / '13_event_locations.qgz'
GPKG = DATA_DIR / (STEM + '.gpkg')
SOURCE_PROJECT = ROOT / 'plot/04_seismic_hazard/qgis/projects/04_seismic_hazard_streets.qgz'
SCOPE = ROOT / 'result/validation/13_event_validation/results/campus_boundary_scope.gpkg'
DAMAGE = ROOT / 'result/validation/13_event_validation/maps/campus_hver/confirmed_damage.fgb'
EVENT = ROOT / 'data/validation/cases/event_epicenter.shp'
POI = ROOT / 'data/validation/cases/case_candidates.gpkg'
ALL_BUILDINGS = ROOT / 'result/intermediate/buildings/building_height_repaired.gpkg'

TEAL = '#087F96'
MAGENTA = '#C035A4'
RED = '#E52D43'
FAULT = '#AF4864'
INK = '#27343B'
LOCATOR = '#000000'
BUILDING_GRAY = '#9AA3AA'
SATELLITE_MANIFEST = DATA_DIR / 'satellite/satellite_insets_manifest.json'
INSETS = [('C', 35945, 'YNAU West', 88.),
          ('A', 34360, 'YUFE South', 164.)]
PANEL_X = {'C': 18., 'A': 114.}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(path, name, table=None):
    uri = str(path) + ('|layername=' + table if table else '')
    layer = QgsVectorLayer(uri, name, 'ogr')
    assert layer.isValid(), uri
    return layer


def materialize(layer, table, project):
    """Write only this run's local data, with the same geometry and attributes."""
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = 'GPKG'
    opts.layerName = table
    if GPKG.exists():
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(GPKG), project.transformContext(), opts)
    assert result[0] == QgsVectorFileWriter.NoError, result
    return source(GPKG, layer.name(), table)


def transformed(geometry, layer, project):
    result = QgsGeometry(geometry)
    result.transform(QgsCoordinateTransform(layer.crs(), project.crs(), project))
    return result


def marker(color, shape='circle', size=3.8):
    return QgsMarkerSymbol.createSimple({
        'name': shape, 'color': color, 'size': str(size),
        'outline_color': 'white', 'outline_width': '.45',
        'outline_width_unit': 'MM', 'joinstyle': 'round'})


def fill(color, outline, width):
    return QgsFillSymbol.createSimple({
        'color': color, 'outline_color': outline,
        'outline_width': str(width), 'outline_width_unit': 'MM',
        'joinstyle': 'round'})


def text_format(size, color=INK, chinese=False, halo=.55):
    result = QgsTextFormat()
    result.setFont(QFont('Arial', int(size), QFont.Bold))
    result.setSize(size)
    result.setColor(QColor(color))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(halo > 0)
    buffer.setSize(halo)
    buffer.setColor(QColor('white'))
    result.setBuffer(buffer)
    return result


def label(layout, id_, value, x, y, width, height, size=10, color=INK, chinese=False):
    item = QgsLayoutItemLabel(layout)
    item.setId(id_)
    item.setText(value)
    item.setTextFormat(text_format(size, color, chinese))
    item.setMargin(0)
    item.setBackgroundEnabled(False)
    item.setFrameEnabled(False)
    item.setVAlign(Qt.AlignVCenter)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y))
    item.attemptResize(QgsLayoutSize(width, height))
    item.setZValue(30)
    return item


def lock_styles(map_item, layers, suppress_labels=()):
    overrides = {}
    for layer in layers:
        was_enabled = layer.labelsEnabled() if isinstance(layer, QgsVectorLayer) else False
        if layer.id() in suppress_labels:
            layer.setLabelsEnabled(False)
        style = QgsMapLayerStyle()
        style.readFromLayer(layer)
        overrides[layer.id()] = style.xmlData()
        if layer.id() in suppress_labels:
            layer.setLabelsEnabled(was_enabled)
    map_item.setLayerStyleOverrides(overrides)
    map_item.setKeepLayerStyles(True)


def line(layout, id_, start, end, color, width=.3, underlay=False):
    item = QgsLayoutItemPolyline(QPolygonF([QPointF(*start), QPointF(*end)]), layout)
    item.setId(id_)
    symbol = QgsLineSymbol.createSimple({'line_color': 'white' if underlay else color,
                                         'line_width': str(width + .5 if underlay else width)})
    if underlay:
        symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color': color, 'line_width': str(width)}))
    item.setSymbol(symbol)
    layout.addLayoutItem(item)
    item.setZValue(29)
    return item


def main(preview_only=False):
    for folder in (QGIS_DIR, DATA_DIR, FIG_DIR, CHECK_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    protected_files = [SOURCE_PROJECT, ROOT / 'plot/13_event_validation/qgis/projects/13_event_validation.qgz', SCOPE, DAMAGE, ALL_BUILDINGS,
                       ROOT / 'data/cartography/kunming_simple_basemap.gpkg',
                       ROOT / 'data/cartography/terrain/kunming_esri_hillshade.tif',
                       ROOT / 'data/faults/kunming_faults_literature.gpkg']
    protected_files += list(EVENT.parent.glob(EVENT.stem + '.*'))
    imagery = json.loads(SATELLITE_MANIFEST.read_text())
    imagery_by_id = {entry['Build_ID']: entry for entry in imagery['cases']}
    protected_files += [SATELLITE_MANIFEST] + [ROOT / entry['tif'] for entry in imagery['cases']]
    protected = {str(p): sha(p) for p in protected_files}

    base_project = QgsProject()
    assert base_project.read(str(SOURCE_PROJECT))
    base_layout = base_project.layoutManager().layoutByName('Kunming_Hazard_PGA_Streets')
    base_map = base_layout.itemById('Hazard_Main_Map')
    assert base_map
    # Apply the saved print styles before cloning: these are authoritative over tree styles.
    for layer in base_map.layers():
        xml = base_map.layerStyleOverrides().get(layer.id())
        if xml:
            QgsMapLayerStyle(xml).writeToLayer(layer)

    project = QgsProject()
    project.setCrs(QgsCoordinateReferenceSystem('EPSG:4543'))
    project.setEllipsoid('WGS84')
    project.setTitle('5.2 Two-building event validation - satellite neighborhood insets')
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    root = project.layerTreeRoot()
    thematic = root.addGroup('01 Event validation and confirmed damage')
    foundation = root.addGroup('02 Building footprints and street basemap')
    auxiliary = root.addGroup('03 Neighborhood inset layers')

    def add(layer, group=thematic):
        assert layer.isValid(), layer.name()
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        return layer

    scope_source = source(SCOPE, 'Campus reference boundaries', 'selection_areas')
    scope = materialize(scope_source, 'campus_boundaries', project)
    scope.setRenderer(QgsSingleSymbolRenderer(fill('8,127,150,10', TEAL, .5)))
    scope.setLabelsEnabled(False)
    add(scope)

    bounds = QgsRectangle()
    bounds.setNull()
    for f in scope.getFeatures():
        bounds.combineExtentWith(transformed(f.geometry(), scope, project).boundingBox())
    # A portrait local view close to the supplied reference, with all campuses in frame.
    map_w, map_h = 172., 205.
    height = bounds.height() + 1500.
    width = max(height * map_w / map_h, bounds.width() + 1600.)
    height = width * map_h / map_w
    cx, cy = bounds.center().x(), bounds.center().y() + 50.
    extent = QgsRectangle(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)

    buildings_source = source(SCOPE, 'Campus building inventory - 188', 'candidate_buildings_latest')
    buildings = materialize(buildings_source, 'campus_buildings', project)
    buildings.setRenderer(QgsSingleSymbolRenderer(fill(BUILDING_GRAY, '#9FA9AF', .08)))
    buildings.setLabelsEnabled(False)
    add(buildings)
    damage_source = source(DAMAGE, 'Validation buildings - 34360 and 35945')
    assert damage_source.setSubsetString('"Build_ID" IN (34360,35945)')
    damage = materialize(damage_source, 'confirmed_damage_buildings', project)
    damage.setRenderer(QgsSingleSymbolRenderer(fill(MAGENTA, MAGENTA, .18)))
    damage.setLabelsEnabled(False)
    add(damage)

    # Use the complete building inventory, rather than just model-complete campus results.
    all_source = source(ALL_BUILDINGS, 'Building footprint source', 'building_height_repaired')
    all_memory = QgsVectorLayer('MultiPolygon?crs=EPSG:4543', 'Building footprints - gray model', 'memory')
    all_memory.dataProvider().addAttributes([QgsField('Build_ID', QVariant.Int), QgsField('height_m', QVariant.Double)])
    all_memory.updateFields()
    query_extent = QgsCoordinateTransform(project.crs(), all_source.crs(), project).transformBoundingBox(extent)
    for original in all_source.getFeatures(QgsFeatureRequest().setFilterRect(query_extent)):
        geometry = transformed(original.geometry(), all_source, project)
        if not geometry.intersects(QgsGeometry.fromRect(extent)):
            continue
        assert geometry.convertToMultiType()
        feature = QgsFeature(all_memory.fields())
        feature.setGeometry(geometry)
        feature.setAttributes([original['Build_ID'], original['mean_heigh']])
        assert all_memory.dataProvider().addFeatures([feature])[0]
    white_buildings = materialize(all_memory, 'white_model_buildings', project)
    white_buildings.setRenderer(QgsSingleSymbolRenderer(fill(BUILDING_GRAY, '#9FA9AF', .065)))
    white_buildings.setLabelsEnabled(False)
    add(white_buildings, foundation)

    satellite_outline = damage.clone()
    satellite_outline.setName('Validation-building outlines - satellite insets')
    outline_symbol = QgsFillSymbol.createSimple({'style': 'no', 'outline_color': 'white', 'outline_width': '1.1'})
    outline_symbol.appendSymbolLayer(QgsSimpleFillSymbolLayer.create({'style': 'no', 'outline_color': MAGENTA, 'outline_width': '.5'}))
    satellite_outline.setRenderer(QgsSingleSymbolRenderer(outline_symbol))
    satellite_outline.setLabelsEnabled(False)
    add(satellite_outline, auxiliary)
    satellite_layers = {}
    for code, bid, campus, _ in INSETS:
        entry = imagery_by_id[bid]
        satellite = QgsRasterLayer(str(ROOT / entry['tif']),
                                   f'{code} - {campus} - World Imagery L{entry["highest_available_level"]}', 'gdal')
        metadata = satellite.metadata()
        metadata.setRights([imagery['copyright']])
        metadata.setAbstract(imagery['role'] + '; native cached tiles; highest locally available level '
                             + str(entry['highest_available_level']))
        satellite.setMetadata(metadata)
        add(satellite, auxiliary)
        satellite_layers[code] = satellite

    # The two 500 m-wide satellite windows share one geographic scale.
    inset_extents = {}
    target_geometries = {}
    inset_w, inset_h = 64., 42.
    for code, bid, _, _ in INSETS:
        feature = next(f for f in damage.getFeatures() if f['Build_ID'] == bid)
        geom = transformed(feature.geometry(), damage, project)
        target_geometries[bid] = geom
        center = geom.boundingBox().center()
        half_width, half_height = 250., 250. * inset_h / inset_w
        inset_extents[code] = QgsRectangle(center.x() - half_width, center.y() - half_height,
                                         center.x() + half_width, center.y() + half_height)
        assert inset_extents[code].contains(geom.boundingBox())
        cached_bounds = imagery_by_id[bid]['bounds_4543']
        assert max(abs(a - b) for a, b in zip([inset_extents[code].xMinimum(), inset_extents[code].yMinimum(),
                                               inset_extents[code].xMaximum(), inset_extents[code].yMaximum()], cached_bounds)) < .01
    locator_memory = QgsVectorLayer('Polygon?crs=EPSG:4543', 'Satellite inset extents A and C', 'memory')
    locator_memory.dataProvider().addAttributes([QgsField('code', QVariant.String), QgsField('Build_ID', QVariant.Int)])
    locator_memory.updateFields()
    for code, bid, _, _ in INSETS:
        feature = QgsFeature(locator_memory.fields())
        feature.setGeometry(QgsGeometry.fromRect(inset_extents[code]))
        feature.setAttributes([code, bid])
        assert locator_memory.dataProvider().addFeatures([feature])[0]
    locators = materialize(locator_memory, 'inset_extents', project)
    locators.setRenderer(QgsSingleSymbolRenderer(fill('255,255,255,0', LOCATOR, .32)))
    locators.setLabelsEnabled(False)
    add(locators)

    poi_source = source(POI, 'Original validation POIs', 'site_points')
    points_memory = QgsVectorLayer('Point?crs=EPSG:4543', 'Validation sites - YUFE and YNAU', 'memory')
    points_memory.dataProvider().addAttributes([
        QgsField('location_id', QVariant.String), QgsField('map_label', QVariant.String),
        QgsField('source_note', QVariant.String)])
    points_memory.updateFields()
    point_positions = {}
    for lid, caption in [('CF01', 'YUFE South'), ('NY01', 'YNAU')]:
        original = next(f for f in poi_source.getFeatures() if f['location_id'] == lid)
        geom = transformed(original.geometry(), poi_source, project)
        point_positions[lid] = geom.asPoint()
        feature = QgsFeature(points_memory.fields())
        feature.setGeometry(geom)
        feature.setAttributes([lid, caption, 'Existing validation POI; source positions retained'])
        assert points_memory.dataProvider().addFeatures([feature])[0]
    points = materialize(points_memory, 'validation_locations', project)
    points.setRenderer(QgsSingleSymbolRenderer(marker(TEAL, size=3.0)))
    # Native labels also remain available in the main QGIS canvas.
    pal = QgsPalLayerSettings()
    pal.fieldName = 'map_label'
    pal.setFormat(text_format(11, TEAL))
    pal.dist = 2
    points.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    points.setLabelsEnabled(True)
    add(points)

    event_source = source(EVENT, '2026-09-30 epicenter')
    event = materialize(event_source, 'event_epicenter', project)
    event.setRenderer(QgsSingleSymbolRenderer(marker(RED, 'triangle', 4.8)))
    event.setLabelsEnabled(False)
    add(event)
    event_feature = next(event.getFeatures())
    event_position = transformed(event_feature.geometry(), event, project).asPoint()
    assert extent.contains(event_position)

    # Clone the actual street-map foundation and retain its local cached hillshade.
    base_layers = []
    inherited_names = []
    for original in base_map.layers():
        name = original.name()
        if not any(part in name for part in ('五大区县级边界', '昆明乡镇街道边界', 'OSM waterways', '灰色山体阴影')):
            continue
        clone = original.clone()
        for key, caption in [('五大区县级边界', 'District boundaries'),
                             ('昆明乡镇街道边界', 'Subdistrict boundaries'),
                             ('OSM waterways', 'Waterways'),
                             ('灰色山体阴影', 'Gray hillshade - local cache')]:
            if key in name:
                clone.setName(caption)
        if isinstance(clone, QgsVectorLayer):
            clone.setLabelsEnabled(False)
            if clone.name() in ('District boundaries', 'Subdistrict boundaries'):
                clone.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
                    'style': 'no', 'outline_color': '#000000',
                    'outline_width': '2' if clone.name() == 'District boundaries' else '.6',
                    'outline_width_unit': 'Point', 'joinstyle': 'round'})))
        add(clone, foundation)
        inherited_names.append(name)
        base_layers.append(clone)
    assert len(base_layers) == 4

    faults_source = source(ROOT / 'data/faults/kunming_faults_literature.gpkg', 'Fault source', 'faults_enriched')
    faults_memory = QgsVectorLayer('MultiLineString?crs=EPSG:4543', 'Local fault traces', 'memory')
    faults_memory.dataProvider().addAttributes(list(faults_source.fields()))
    faults_memory.updateFields()
    clip = QgsGeometry.fromRect(extent)
    for original in faults_source.getFeatures():
        geometry = transformed(original.geometry(), faults_source, project)
        if not geometry.intersects(clip):
            continue
        geometry = geometry.intersection(clip)
        if geometry.isEmpty():
            continue
        assert geometry.convertToMultiType()
        feature = QgsFeature(faults_memory.fields())
        feature.setAttributes(original.attributes())
        feature.setGeometry(geometry)
        assert faults_memory.dataProvider().addFeatures([feature])[0]
    faults = materialize(faults_memory, 'local_faults', project)
    symbol = QgsLineSymbol.createSimple({'line_color': 'white', 'line_width': '1.2'})
    symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color': FAULT, 'line_width': '.75'}))
    faults.setRenderer(QgsSingleSymbolRenderer(symbol))
    fault_labels = QgsPalLayerSettings()
    fault_labels.fieldName = 'FN_En'
    fault_labels.placement = Qgis.LabelPlacement.Line
    fault_labels.dist = 1.5
    fault_labels.setFormat(text_format(10, FAULT, halo=.65))
    faults.setLabeling(QgsVectorLayerSimpleLabeling(fault_labels))
    faults.setLabelsEnabled(True)
    add(faults, foundation)

    roads = source(ROOT / 'data/cartography/kunming_simple_basemap.gpkg', 'Neighborhood roads - OSM', 'roads')
    roads.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({'line_color': '#D0D5D8', 'line_width': '.38'})))
    roads.setLabelsEnabled(False)
    add(roads, auxiliary)
    root.findLayer(roads.id()).setItemVisibilityChecked(False)
    auxiliary.setExpanded(False)

    layers = ([points, event, damage, locators, scope, faults] + base_layers[:2]
              + [buildings, white_buildings] + base_layers[2:])
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(layers + [roads, satellite_outline] + list(satellite_layers.values()))
    for layer in [satellite_outline] + list(satellite_layers.values()):
        root.findLayer(layer.id()).setItemVisibilityChecked(False)
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, project.crs()))
    project.setBackgroundColor(QColor('white'))

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName('5_2_Event_Validation_Distribution')
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(196, 224))
    layout.renderContext().setDpi(600)
    project.layoutManager().addLayout(layout)
    map_ = QgsLayoutItemMap(layout)
    map_.setId('Event_Distribution_Main_Map')
    layout.addLayoutItem(map_)
    map_.attemptMove(QgsLayoutPoint(12, 10))
    map_.attemptResize(QgsLayoutSize(map_w, map_h))
    map_.setCrs(project.crs())
    map_.setLayers(layers)
    map_.setKeepLayerSet(True)
    map_.zoomToExtent(extent)
    map_.setBackgroundColor(QColor('white'))
    map_.setFrameEnabled(True)
    map_.setFrameStrokeColor(QColor(INK))
    map_.setFrameStrokeWidth(QgsLayoutMeasurement(.8))
    map_.setZValue(1)
    # Canvas uses automatic text placement; layout keeps two fixed validation-site callouts.
    lock_styles(map_, layers, [points.id()])

    grid = map_.grid()
    grid.setEnabled(True)
    grid.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
    grid.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly)
    grid.setIntervalX(.02)
    grid.setIntervalY(.02)
    grid.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
    grid.setFrameWidth(1.4)
    grid.setFramePenSize(.22)
    grid.setAnnotationEnabled(True)
    grid.setAnnotationFormat(QgsLayoutItemMapGrid.DegreeMinute)
    grid.setAnnotationPrecision(1)
    grid.setAnnotationFont(QFont('Arial', 9, QFont.Bold))
    grid.setAnnotationFrameDistance(1.4)
    for side in (QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.Right):
        grid.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, side)
    for side in (QgsLayoutItemMapGrid.Left, QgsLayoutItemMapGrid.Bottom):
        grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, side)
    grid.setAnnotationDirection(QgsLayoutItemMapGrid.Vertical, QgsLayoutItemMapGrid.Left)

    def mm(point):
        e = map_.extent()
        return (12 + (point.x() - e.xMinimum()) / e.width() * map_w,
                10 + (e.yMaximum() - point.y()) / e.height() * map_h)

    # Place the two district names at verified points inside their original boundaries.
    district_source = next(layer for layer in base_layers if layer.name() == 'District boundaries')
    district_names = []
    for source_name, caption, x, y, label_width in [('五华区', 'Wuhua District', 27., 145., 53.),
                                                    ('盘龙区', 'Panlong District', 125., 141., 53.)]:
        feature = next(f for f in district_source.getFeatures() if f['name'] == source_name)
        geometry = transformed(feature.geometry(), district_source, project)
        center_mm = (x + label_width / 2., y + 4.)
        point = QgsPointXY(map_.extent().xMinimum() + (center_mm[0] - 12.) / map_w * map_.extent().width(),
                           map_.extent().yMaximum() - (center_mm[1] - 10.) / map_h * map_.extent().height())
        assert geometry.contains(QgsGeometry.fromPointXY(point)), caption
        label(layout, 'District_label_' + caption.split()[0], caption, x, y, label_width, 8, 11.5, '#000000')
        district_names.append(caption)

    # Labels remain separate editable items, clear of the overlaid neighborhood panels.
    callouts = {'CF01': (-41., 5., 40.), 'NY01': (-29., -11., 27.)}
    for lid, caption in [('CF01', 'YUFE South'), ('NY01', 'YNAU')]:
        px, py = mm(point_positions[lid])
        dx, dy, box_width = callouts[lid]
        label(layout, 'Campus_label_' + lid, caption, px + dx, py + dy, box_width, 7, 11, TEAL)
        if lid == 'NY01':
            line(layout, 'Campus_leader_' + lid, (px - 2.2, py), (px - 7, py - 2.5), TEAL, .35, True)
    ex, ey = mm(event_position)
    label(layout, 'Event_date_label', '2026-09-30\nEpicenter', ex - 3., ey + 5., 35, 11, 9.5, RED)

    # Compact transparent legend in the clear northwest corner.
    legend_rows = [
        ('Epicenter', 'triangle', RED), ('Validation site', 'circle', TEAL),
        ('Campus boundary', 'outline', TEAL), ('Building footprint', 'fill', BUILDING_GRAY),
        ('Validation building', 'fill', MAGENTA), ('Fault', 'line', FAULT),
        ('Subdistrict boundary', 'line', '#000000'), ('District boundary', 'line', '#000000')]
    for i, (caption, shape, color) in enumerate(legend_rows):
        x, y = 18., 19. + i * 6.5
        if shape in ('triangle', 'circle'):
            item = QgsLayoutItemMarker(layout)
            item.setSymbol(marker(color, shape, 3.4 if shape == 'triangle' else 3.0))
            layout.addLayoutItem(item)
            item.attemptMove(QgsLayoutPoint(x + 3, y + 2.5))
            item.setZValue(30)
        elif shape in ('outline', 'fill'):
            item = QgsLayoutItemPolygon(QPolygonF([QPointF(x, y + .7), QPointF(x + 6, y + .7),
                                                  QPointF(x + 6, y + 4.3), QPointF(x, y + 4.3)]), layout)
            item.setSymbol(fill('255,255,255,0' if shape == 'outline' else color,
                                color if shape == 'outline' else '#9FA9AF' if color == BUILDING_GRAY else 'white',
                                .4 if shape == 'outline' else .16))
            layout.addLayoutItem(item)
            item.setZValue(30)
        else:
            line(layout, 'Legend_line_' + str(i), (x, y + 2.5), (x + 6, y + 2.5), color,
                 .75 if caption == 'Fault' else .55 if caption == 'District boundary' else .21, caption == 'Fault')
            item = None
        if item is not None:
            item.setId('Legend_symbol_' + str(i))
        label(layout, 'Legend_text_' + str(i), caption, x + 9, y, 47, 5, 9,
              '#000000' if caption in ('Subdistrict boundary', 'District boundary') else INK)

    inset_records = []
    for code, bid, campus, panel_y in INSETS:
        panel_x = PANEL_X[code]
        # Only a transparent border surrounds each image; annotations sit on the image.
        panel = QgsLayoutItemShape(layout)
        panel.setId('Inset_panel_' + code)
        panel.setShapeType(QgsLayoutItemShape.Rectangle)
        panel.setSymbol(fill('255,255,255,0', LOCATOR, .65))
        layout.addLayoutItem(panel)
        panel.attemptMove(QgsLayoutPoint(panel_x, panel_y))
        panel.attemptResize(QgsLayoutSize(inset_w, inset_h))
        panel.setZValue(42)
        inset = QgsLayoutItemMap(layout)
        inset.setId('Neighborhood_inset_' + code)
        layout.addLayoutItem(inset)
        inset.attemptMove(QgsLayoutPoint(panel_x, panel_y))
        inset.attemptResize(QgsLayoutSize(inset_w, inset_h))
        inset.setCrs(project.crs())
        inset_layers = [satellite_outline, satellite_layers[code]]
        inset.setLayers(inset_layers)
        inset.setKeepLayerSet(True)
        inset.setBackgroundEnabled(True)
        inset.setBackgroundColor(QColor('white'))
        inset.zoomToExtent(inset_extents[code])
        # The outer panel supplies the frame, with no title bar or separator rule.
        inset.setFrameEnabled(False)
        inset.setZValue(35)
        lock_styles(inset, inset_layers)
        label(layout, 'Inset_location_' + code, code + '  ' + campus,
              panel_x + 1.8, panel_y + 1., inset_w - 3.6, 5, 10, '#000000').setZValue(40)
        label(layout, 'Inset_building_ID_' + code, 'Building ' + str(bid),
              panel_x + 1.5, panel_y + 7., 32, 4.8, 8.5, '#000000').setZValue(40)
        inset_scale = QgsLayoutItemScaleBar(layout)
        inset_scale.setId('Inset_scale_' + code)
        inset_scale.setStyle('Line Ticks Up')
        inset_scale.setLinkedMap(inset)
        inset_scale.setUnits(Qgis.DistanceUnit.Meters)
        inset_scale.setUnitsPerSegment(50)
        inset_scale.setNumberOfSegments(2)
        inset_scale.setNumberOfSegmentsLeft(0)
        inset_scale.setUnitLabel('m')
        inset_scale.setHeight(1.1)
        inset_scale.setTextFormat(text_format(7.5, '#000000', halo=.5))
        scale_line = QgsLineSymbol.createSimple({'line_color': 'white', 'line_width': '.8'})
        scale_line.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color': '#000000', 'line_width': '.24'}))
        inset_scale.setLineSymbol(scale_line)
        inset_scale.setBackgroundEnabled(False)
        inset_scale.setFrameEnabled(False)
        inset_scale.setBoxContentSpace(.4)
        inset_scale.setLabelBarSpace(.5)
        layout.addLayoutItem(inset_scale)
        inset_scale.attemptMove(QgsLayoutPoint(panel_x + inset_w - 22., panel_y + inset_h - 7.))
        inset_scale.setZValue(40)

        window = inset_extents[code]
        left_top = mm(QgsPointXY(window.xMinimum(), window.yMaximum()))
        right_bottom = mm(QgsPointXY(window.xMaximum(), window.yMinimum()))
        label(layout, 'Locator_letter_' + code, code, left_top[0] - 4.7, left_top[1] - 3.,
              5, 5.5, 10, LOCATOR).setHAlign(Qt.AlignHCenter)
        if code == 'C':
            start = (left_top[0], right_bottom[1])
            end = (panel_x + inset_w, panel_y)
        else:
            start = (right_bottom[0], (left_top[1] + right_bottom[1]) / 2.)
            end = (panel_x, panel_y + inset_h / 2.)
        line(layout, 'Inset_connector_' + code, start, end, LOCATOR, .32, True)
        inset_records.append({'code': code, 'Build_ID': bid, 'campus': campus,
                              'extent': inset.extent().toString(6), 'width_m': inset.extent().width(),
                              'height_m': inset.extent().height(), 'scale': inset.scale(),
                              'basemap': 'Native World Imagery satellite tiles',
                              'tile_level': imagery_by_id[bid]['highest_available_level'],
                              'approx_ground_resolution_m': imagery_by_id[bid]['approx_ground_resolution_m'],
                              'frame_mm': [panel_x, panel_y, inset_w, inset_h],
                              'target_wholly_inside': inset.extent().contains(target_geometries[bid].boundingBox()),
                              'context_buildings': sum(1 for f in white_buildings.getFeatures(QgsFeatureRequest().setFilterRect(inset.extent()))
                                                       if f.geometry().intersects(QgsGeometry.fromRect(inset.extent())))})

    label(layout, 'North_N', 'N', 172, 16, 6, 5, 11, INK, False).setHAlign(Qt.AlignHCenter)
    arrow = QgsLayoutItemPicture(layout)
    arrow.setId('North_arrow')
    layout.addLayoutItem(arrow)
    arrow.attemptMove(QgsLayoutPoint(173, 22))
    arrow.attemptResize(QgsLayoutSize(4, 8))
    arrow.setPicturePath(str(ROOT / 'plot/01_study_area/qgis/layouts/study_area/north_arrow.svg'))
    arrow.setLinkedMap(map_)
    arrow.setNorthMode(QgsLayoutItemPicture.TrueNorth)
    arrow.setBackgroundEnabled(False)
    arrow.setZValue(30)

    scale = QgsLayoutItemScaleBar(layout)
    scale.setId('Scale_0_1_km')
    scale.setStyle('Line Ticks Up')
    scale.setLinkedMap(map_)
    scale.setUnits(Qgis.DistanceUnit.Kilometers)
    scale.setUnitsPerSegment(.5)
    scale.setNumberOfSegments(2)
    scale.setNumberOfSegmentsLeft(0)
    scale.setUnitLabel('km')
    scale.setHeight(1.5)
    scale.setTextFormat(text_format(9, INK, False, .5))
    scale.setLineSymbol(QgsLineSymbol.createSimple({'line_color': INK, 'line_width': '.25'}))
    scale.setBackgroundEnabled(False)
    scale.setBoxContentSpace(.6)
    scale.setLabelBarSpace(.8)
    layout.addLayoutItem(scale)
    scale.attemptMove(QgsLayoutPoint(18, 202))
    scale.setZValue(30)
    project.setCustomVariables({
        'basemap_source_project': str(SOURCE_PROJECT),
        'map_purpose': 'Local distribution of event-validation campuses and known damaged buildings',
        'confirmed_damage_building_ids': '34360,35945',
        'other_campus_buildings_damage_status': 'Context only; outside this two-building validation selection',
        'epicenter_coordinate_note': str(event_feature['coord_note']),
        'extent_basis': 'All four campus boundaries plus 1500 m total vertical padding',
        'reference_style': 'User supplied portrait distribution map; existing street-map foundation'})
    for item in layout.items():
        if isinstance(item, (QgsLayoutItemLabel, QgsLayoutItemScaleBar)):
            assert item.textFormat().font().family() == 'Arial' and item.textFormat().font().bold(), item.id()
        if isinstance(item, QgsLayoutItemLabel):
            assert item.text().isascii(), item.text()
    assert not layout.itemById('Source_note')
    assert project.write(str(PROJECT))
    qpt = ROOT / 'plot/13_event_validation/qgis/layouts/13_event_validation/13_event_locations.qpt'
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(qpt)))
    assert layout.saveAsTemplate(str(qpt), context)

    exporter = QgsLayoutExporter(layout)
    preview = FIG_DIR / (STEM + '_preview.png')
    image = exporter.renderPageToImage(0, dpi=180)
    assert not image.isNull() and image.save(str(preview))
    outputs = [str(preview)]
    if not preview_only:
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = 600
        png = FIG_DIR / (STEM + '_600dpi.png')
        assert exporter.exportToImage(str(png), settings) == QgsLayoutExporter.Success
        pdf = QgsLayoutExporter.PdfExportSettings()
        pdf.dpi = 600
        pdf.forceVectorOutput = True
        pdf.textRenderFormat = Qgis.TextRenderFormat.AlwaysOutlines
        pdf_path = FIG_DIR / (STEM + '.pdf')
        # Export to a fresh file before replacing the public PDF. This also avoids
        # stale GDAL PDF handles when the current document is already open elsewhere.
        pdf_tmp_dir = OUT / 'tmp/pdfs'
        pdf_tmp_dir.mkdir(parents=True, exist_ok=True)
        pdf_tmp = pdf_tmp_dir / (STEM + '_export.pdf')
        if pdf_tmp.exists():
            pdf_tmp.unlink()
        assert exporter.exportToPdf(str(pdf_tmp), pdf) == QgsLayoutExporter.Success
        pdf_tmp.replace(pdf_path)
        outputs += [str(png), str(pdf_path)]

    restored = QgsProject()
    assert restored.read(str(PROJECT))
    assert all(layer.isValid() for layer in restored.mapLayers().values())
    restored_layout = restored.layoutManager().layoutByName(layout.name())
    assert restored_layout and len(restored_layout.pageCollection().pages()) == 1
    restored_map = restored_layout.itemById('Event_Distribution_Main_Map')
    assert len(restored_map.layers()) == len(layers)
    assert len([item for item in restored_layout.items() if isinstance(item, QgsLayoutItemMap)]) == 3
    assert all(item['target_wholly_inside'] for item in inset_records)
    assert max(item['scale'] for item in inset_records) - min(item['scale'] for item in inset_records) < 1e-4
    assert not any(layer.providerType() in ('wms', 'xyzvectortiles') for layer in restored.mapLayers().values())
    assert scope.featureCount() == 4 and buildings.featureCount() == 188
    assert damage.featureCount() == 2 and points.featureCount() == 2 and event.featureCount() == 1
    assert {f['Build_ID'] for f in damage.getFeatures()} == {34360, 35945}
    assert {34360, 35945}.issubset({f['Build_ID'] for f in white_buildings.getFeatures()})
    assert not any(restored_layout.itemById(name) for name in ('Neighborhood_inset_B', 'Campus_label_CF02'))
    for feature in scope.getFeatures():
        assert map_.extent().contains(transformed(feature.geometry(), scope, project).boundingBox())
    assert all(sha(path) == digest for path, digest in protected.items())
    manifest = {
        'project': str(PROJECT), 'layout': layout.name(), 'template': str(qpt),
        'crs': project.crs().authid(), 'extent': map_.extent().toString(6),
        'page_mm': [196, 224], 'map_mm': [map_w, map_h],
        'map_span_m': [map_.extent().width(), map_.extent().height()],
        'street_basemap_source': str(SOURCE_PROJECT), 'inherited_layers': inherited_names,
        'satellite_basemap_used': 'Inset maps only', 'local_offline_sources_only': True,
        'satellite_manifest': str(SATELLITE_MANIFEST), 'district_labels': district_names,
        'fault_label': [f['FN_En'] for f in faults.getFeatures()], 'main_frame_width_mm': .8,
        'inset_title_separator_removed': True, 'inset_header_rule_removed': True,
        'inset_title_bars_removed': True, 'inset_labels_inside_images': True,
        'inset_frame_and_annotation_color': '#000000', 'inset_frame_width_mm': .65,
        'building_fill_color': BUILDING_GRAY, 'administrative_boundary_and_label_color': '#000000',
        'map_layers': [l.name() for l in layers],
        'campus_boundaries': scope.featureCount(), 'campus_buildings': buildings.featureCount(),
        'gray_model_buildings': white_buildings.featureCount(), 'gray_model_source': str(ALL_BUILDINGS),
        'building_geometry_modified': False, 'font': 'Arial Bold', 'visible_text_language': 'English',
        'footer_removed': True, 'fault_width_mm': .75, 'insets': inset_records,
        'confirmed_damage_ids': sorted(f['Build_ID'] for f in damage.getFeatures()),
        'other_building_role': 'Spatial context; not part of the selected two-building validation',
        'original_damage_source_ids_preserved': [34360, 35945, 45948], 'campus_poi_count': points.featureCount(),
        'event': {'longitude': event_feature['longitude'], 'latitude': event_feature['latitude'],
                  'coordinate_note': str(event_feature['coord_note']), 'label': '2026-09-30 Epicenter'},
        'fault_ids': [f['fault_uid'] for f in faults.getFeatures()],
        'source_sha256': protected, 'source_files_unchanged': True,
        'all_layers_valid_after_reload': True, 'all_campuses_inside_map': True,
        'outputs': outputs, 'preview_only': preview_only}
    (CHECK_DIR / (STEM + '_manifest.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'source_sha256'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('--preview-only', action='store_true')
    options = args.parse_args()
    app = QgsApplication([], False)
    app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis', True)
    app.initQgis()
    main(options.preview_only)
    os._exit(0)
