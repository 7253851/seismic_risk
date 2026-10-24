"""Native QGIS composite: local distribution, two damage cases and building-scale PS.

PS positions and rates are copied from the model's associated observations.
All source projects, evidence photographs and model values remain read-only.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import sqlite3

from qgis.core import *
from qgis.PyQt.QtCore import Qt, QVariant, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QPolygonF

from build_event_spatial_distribution import label, fill, line, text_format, lock_styles

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'plot/13_event_validation/output'
QGIS_DIR = ROOT / 'plot/13_event_validation/qgis'
DATA_DIR = ROOT / 'result/intermediate/13_event_validation/cartography'
FIG_DIR, CHECK_DIR = OUT / 'derived', OUT / 'checks'
STEM = '5_2_event_validation_composite'
TARGET = QGIS_DIR / 'projects/13_event_validation.qgz'
PS_DATA = DATA_DIR / (STEM + '_PS.gpkg')
LOCATION_PROJECT = ROOT / 'plot/13_event_validation/qgis/support/13_event_locations.qgz'
CASE_PROJECT = ROOT / 'plot/13_event_validation/qgis/support/validation_damage_cases_2x3.qgz'
PS_SOURCE = ROOT / 'result/intermediate/vulnerability_inputs/building_ps_points.gpkg'
CONFIRMED = ROOT / 'result/validation/13_event_validation/maps/campus_hver/confirmed_damage.fgb'
PAGE = (374., 252.)
PANEL = (46., 44.)
BLACK, MAGENTA = '#000000', '#B20A8F'
CLASSES = ['Very Low', 'Low', 'Moderate', 'High', 'Very High']
PS_LIMITS = (-2., 4.)
CASES = [
    dict(code='D1', bid=34360, campus='YUFE South', letters='bcde',
         satellite='A', header_y=10., top_y=24., bottom_y=79., group_y=8.),
    dict(code='D2', bid=35945, campus='YNAU West', letters='ghij',
         satellite='C', header_y=131., top_y=145., bottom_y=200., group_y=129.),
]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def gpkg_geometry(blob):
    envelope = (blob[3] >> 1) & 7
    offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope]
    geometry = QgsGeometry()
    geometry.fromWkb(bytes(blob[offset:]))
    assert not geometry.isNull() and not geometry.isEmpty()
    return geometry


def frame(layout, id_, x, y, w, h, stroke=.35, z=45):
    item = QgsLayoutItemShape(layout)
    item.setId(id_)
    item.setShapeType(QgsLayoutItemShape.Rectangle)
    item.setSymbol(fill('255,255,255,0', BLACK, stroke))
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y))
    item.attemptResize(QgsLayoutSize(w, h))
    item.setZValue(z)
    return item


def save_ps(project):
    layer = QgsVectorLayer('Point?crs=EPSG:32648', 'Observed PS - buildings 34360 and 35945', 'memory')
    layer.dataProvider().addAttributes([
        QgsField('source_fid', QVariant.LongLong), QgsField('source', QVariant.Int),
        QgsField('ps_id', QVariant.LongLong), QgsField('Build_ID', QVariant.LongLong),
        QgsField('v_vertical', QVariant.Double), QgsField('coherence', QVariant.Double)])
    layer.updateFields()
    records, by_id = [], {34360: [], 35945: []}
    with sqlite3.connect('file:' + str(PS_SOURCE) + '?mode=ro&immutable=1', uri=True) as connection:
        rows = connection.execute('SELECT fid,source,ps_id,Build_ID,v_vertical,coh,geom '
                                  'FROM building_ps_points WHERE Build_ID IN (34360,35945)').fetchall()
    keys = set()
    for fid, source, ps_id, bid, rate, coherence, blob in rows:
        assert (source, ps_id) not in keys
        keys.add((source, ps_id))
        assert PS_LIMITS[0] <= rate <= PS_LIMITS[1]
        feature = QgsFeature(layer.fields())
        geometry = gpkg_geometry(blob)
        feature.setGeometry(geometry)
        feature.setAttributes([fid, source, ps_id, bid, rate, coherence])
        records.append(feature)
        by_id[bid].append(feature)
    assert len(by_id[34360]) == 61 and len(by_id[35945]) == 104
    assert layer.dataProvider().addFeatures(records)[0]
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName, options.layerName = 'GPKG', 'observed_building_PS'
    if PS_DATA.exists():
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(PS_DATA), project.transformContext(), options)
    assert result[0] == QgsVectorFileWriter.NoError, result
    restored = QgsVectorLayer(str(PS_DATA) + '|layername=observed_building_PS', layer.name(), 'ogr')
    assert restored.isValid() and restored.featureCount() == 165
    # Reopened records must keep both the actual observations and their exact point coordinates.
    original = {int(f['source_fid']): (f.geometry().asWkb(), f['v_vertical']) for f in records}
    assert all((f.geometry().asWkb(), f['v_vertical']) == original[int(f['source_fid'])]
               for f in restored.getFeatures())
    return restored, by_id


def ps_ramp():
    return QgsGradientColorRamp(QColor('#440154'), QColor('#FDE725'), False, [
        QgsGradientStop(.25, QColor('#3B528B')), QgsGradientStop(.5, QColor('#21918C')),
        QgsGradientStop(.75, QColor('#5EC962'))])


def ps_renderer():
    ramp, ranges = ps_ramp(), []
    for i in range(64):
        lo, hi = PS_LIMITS[0] + i * 6 / 64., PS_LIMITS[0] + (i + 1) * 6 / 64.
        symbol = QgsMarkerSymbol.createSimple({'name': 'circle', 'size': '.65',
            'color': ramp.color((i + .5) / 64).name(), 'outline_color': 'white', 'outline_width': '.08'})
        ranges.append(QgsRendererRange(lo, hi, symbol, f'{lo:.3f} to {hi:.3f}'))
    return QgsGraduatedSymbolRenderer('v_vertical', ranges)


def ps_legend(layout, id_, x, y):
    label(layout, id_ + '_units', 'PS vertical rate (mm/yr)', x + 2., y + 30.5, 42, 3.5,
          6.7, BLACK).setZValue(50)
    ramp = ps_ramp()
    for i in range(64):
        item = QgsLayoutItemShape(layout)
        item.setId(id_ + '_color_' + str(i))
        item.setShapeType(QgsLayoutItemShape.Rectangle)
        item.setSymbol(QgsFillSymbol.createSimple({'color': ramp.color((i + .5) / 64).name(), 'outline_style': 'no'}))
        layout.addLayoutItem(item)
        item.attemptMove(QgsLayoutPoint(x + 2. + 42. * i / 64, y + 34.5))
        item.attemptResize(QgsLayoutSize(42. / 64 + .01, 1.8))
        item.setZValue(50)
    frame(layout, id_ + '_color_frame', x + 2, y + 34.5, 42, 1.8, .12, 51)
    for value in (-2, 0, 2, 4):
        dx = 2 + (value - PS_LIMITS[0]) / (PS_LIMITS[1] - PS_LIMITS[0]) * 42
        tick = label(layout, id_ + '_tick_' + str(value), str(value), x + dx - 3, y + 37, 6, 4,
                     6.5, BLACK)
        tick.setHAlign(Qt.AlignHCenter)
        tick.setZValue(51)


def controls(layout, map_item, id_, x, y, segment, font=7.):
    label(layout, id_ + '_N', 'N', x + 39, y + .8, 5, 4, font + .5, BLACK).setHAlign(Qt.AlignHCenter)
    north = QgsLayoutItemPicture(layout)
    north.setId(id_ + '_north')
    layout.addLayoutItem(north)
    north.attemptMove(QgsLayoutPoint(x + 40, y + 5))
    north.attemptResize(QgsLayoutSize(3, 5.2))
    north.setPicturePath(str(ROOT / 'plot/01_study_area/qgis/layouts/study_area/north_arrow.svg'))
    north.setLinkedMap(map_item)
    north.setNorthMode(QgsLayoutItemPicture.TrueNorth)
    north.setBackgroundEnabled(False)
    north.setZValue(40)
    scale = QgsLayoutItemScaleBar(layout)
    scale.setId(id_ + '_scale')
    scale.setStyle('Line Ticks Up')
    scale.setLinkedMap(map_item)
    scale.setUnits(Qgis.DistanceUnit.Meters)
    scale.setUnitsPerSegment(segment)
    scale.setNumberOfSegments(1)
    scale.setNumberOfSegmentsLeft(0)
    scale.setUnitLabel('m')
    scale.setHeight(.9)
    scale.setTextFormat(text_format(font, BLACK, halo=.35))
    symbol = QgsLineSymbol.createSimple({'line_color': 'white', 'line_width': '.65'})
    symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color': BLACK, 'line_width': '.18'}))
    scale.setLineSymbol(symbol)
    scale.setBackgroundEnabled(False)
    scale.setFrameEnabled(False)
    scale.setBoxContentSpace(.4)
    scale.setLabelBarSpace(.3)
    layout.addLayoutItem(scale)
    scale.attemptMove(QgsLayoutPoint(x + 1.3, y + .8))
    scale.setZValue(40)
    return scale


def class_legend(layout, config, id_, x, y):
    if config['key'] == 'hazard':
        label(layout, id_ + '_units', 'PGA (g)', x + 2, y + 28.6, 20, 3.5, 7, BLACK).setZValue(50)
    for i, (name, color) in enumerate(zip(CLASSES, config['colors'])):
        xx = x + 2 + i * 8.4
        item = QgsLayoutItemShape(layout)
        item.setId(id_ + '_swatch_' + str(i))
        item.setShapeType(QgsLayoutItemShape.Rectangle)
        item.setSymbol(fill(color, '#707070', .08))
        layout.addLayoutItem(item)
        item.attemptMove(QgsLayoutPoint(xx, y + 33.4))
        item.attemptResize(QgsLayoutSize(8.4, 2.1))
        item.setZValue(50)
        caption = label(layout, id_ + '_class_' + str(i), name.replace(' ', '\n'),
                        xx - .2, y + 36., 8.8, 6.2, 6.2, BLACK)
        fmt = caption.textFormat()
        font = fmt.font()
        font.setStretch(85)
        fmt.setFont(font)
        caption.setTextFormat(fmt)
        caption.setHAlign(Qt.AlignHCenter)
        caption.setZValue(51)


def scale_location_layout(layout, factor):
    items = [i for i in layout.items() if isinstance(i, QgsLayoutItem) and not isinstance(i, QgsLayoutItemPage)]
    snapshots = [(i, i.pos().x(), i.pos().y(), i.sizeWithUnits().width(), i.sizeWithUnits().height()) for i in items]
    extents = {i.id(): QgsRectangle(i.extent()) for i in items if isinstance(i, QgsLayoutItemMap)}
    for item, x, y, w, h in snapshots:
        item.attemptMove(QgsLayoutPoint(x * factor, y * factor))
        if not isinstance(item, QgsLayoutItemScaleBar):
            item.attemptResize(QgsLayoutSize(w * factor, h * factor))
    for item in items:
        if isinstance(item, QgsLayoutItemMap):
            item.zoomToExtent(extents[item.id()])
    return extents


def main(preview_only=False):
    for directory in (FIG_DIR, DATA_DIR, CHECK_DIR, OUT / 'tmp/pdfs'):
        directory.mkdir(parents=True, exist_ok=True)
    satellite_metadata = json.loads((DATA_DIR / 'satellite/satellite_insets_manifest.json').read_text())
    satellites = {entry['Build_ID']: entry for entry in satellite_metadata['cases']}
    configs = json.loads((ROOT / 'result/validation/13_event_validation/maps/campus_hver/data_manifest.json').read_text())['configs']
    photo_paths = {case['code']: ROOT / 'result/validation/13_event_validation/maps/damage_distribution_collage' / (case['code'] + '_damage_photo.png')
                   for case in CASES}
    protected_paths = [LOCATION_PROJECT, CASE_PROJECT, PS_SOURCE, CONFIRMED,
                       ROOT / 'result/validation/13_event_validation/maps/campus_hver/campus_hver.fgb',
                       ROOT / 'result/validation/13_event_validation/maps/campus_hver/campus_boundaries.fgb']
    protected_paths += list(photo_paths.values()) + [ROOT / entry['tif'] for entry in satellites.values()]
    protected = {str(path): sha(path) for path in protected_paths}
    project = QgsProject()
    assert project.read(str(LOCATION_PROJECT))
    layout = project.layoutManager().layoutByName('5_2_Event_Validation_Distribution')
    assert layout
    layout.setName('5_2_Event_Validation_Composite')
    location_extents = scale_location_layout(layout, 1.1)
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(*PAGE))
    layout.renderContext().setDpi(600)
    project.setTitle('5.2 Event validation - location, damage, PS observations and H/V/E/R')
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    root = project.layerTreeRoot()
    group = root.addGroup('04 Composite - case indicator maps and observed PS')
    group.setExpanded(False)

    def add(layer):
        assert layer.isValid(), layer.name()
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        root.findLayer(layer.id()).setItemVisibilityChecked(False)
        return layer

    ps_layer, observations = save_ps(project)
    add(ps_layer)
    source_project = QgsProject()
    assert source_project.read(str(CASE_PROJECT))
    source_clones = {}

    def indicator_layers(source_map):
        layers, overrides = [], {}
        for original in source_map.layers():
            if original.id() not in source_clones:
                clone = original.clone()
                clone.setName('Case source - ' + original.name())
                add(clone)
                source_clones[original.id()] = clone
            clone = source_clones[original.id()]
            layers.append(clone)
            xml = source_map.layerStyleOverrides().get(original.id())
            if xml:
                overrides[clone.id()] = xml
            else:
                style = QgsMapLayerStyle()
                style.readFromLayer(original)
                overrides[clone.id()] = style.xmlData()
        return layers, overrides

    known = QgsVectorLayer(str(CONFIRMED), 'Selected validation footprints', 'ogr')
    assert known.isValid()
    case_records, indicator_records = [], []
    frame(layout, 'Composite_outer_frame', 3, 3, PAGE[0] - 6, PAGE[1] - 6, .5, 90)
    for case in CASES:
        code, bid = case['code'], case['bid']
        source_layout = source_project.layoutManager().layoutByName('Validation_' + code + '_2x3')
        feature = next(f for f in known.getFeatures() if f['Build_ID'] == bid)
        frame(layout, code + '_group_frame', 219, case['group_y'], 151, 117, .45, 70)
        label(layout, code + '_header', f"{code}  {case['campus']}   Building {bid}",
              222, case['header_y'], 144, 6, 11.5, BLACK)
        positions = [(222., case['top_y']), (271., case['top_y']), (320., case['top_y']),
                     (222., case['bottom_y']), (271., case['bottom_y']), (320., case['bottom_y'])]
        titles = ['(a) Damage photo', '(b) Satellite + PS', '(c) Hazard',
                  '(d) Vulnerability', '(e) Exposure', '(f) Risk']
        for (x, y), caption in zip(positions, titles):
            label(layout, code + '_title_' + caption[1], caption, x, y - 6.3, PANEL[0], 5.2, 9, BLACK)

        # The photo intentionally fills the full panel, as explicitly requested.
        px, py = positions[0]
        photo = QgsLayoutItemPicture(layout)
        photo.setId(code + '_damage_photo')
        layout.addLayoutItem(photo)
        photo.setResizeMode(QgsLayoutItemPicture.Stretch)
        photo.attemptMove(QgsLayoutPoint(px, py))
        photo.attemptResize(QgsLayoutSize(*PANEL))
        photo.setPicturePath(str(photo_paths[code]))
        photo.setBackgroundEnabled(False)
        photo.setZValue(5)
        photo.setCustomProperty('validation/Build_ID', bid)
        frame(layout, code + '_photo_frame', px, py, *PANEL)

        # Individual-building satellite map: exactly PS + imagery, without polygons.
        x, y = positions[1]
        points = ps_layer.clone()
        points.setName(code + ' - observed PS for building ' + str(bid))
        points.setSubsetString('"Build_ID" = ' + str(bid))
        points.setRenderer(ps_renderer())
        points.setLabelsEnabled(False)
        add(points)
        satellite = QgsRasterLayer(str(ROOT / satellites[bid]['tif']), code + ' - native L19 satellite imagery', 'gdal')
        add(satellite)
        ps_map = QgsLayoutItemMap(layout)
        ps_map.setId(code + '_single_building_satellite_PS')
        layout.addLayoutItem(ps_map)
        ps_map.attemptMove(QgsLayoutPoint(x, y))
        ps_map.attemptResize(QgsLayoutSize(*PANEL))
        ps_map.setCrs(known.crs())
        extent = QgsRectangle(feature.geometry().boundingBox())
        for node in observations[bid]:
            extent.combineExtentWith(node.geometry().boundingBox())
        width = max(extent.width(), extent.height() * PANEL[0] / PANEL[1]) * 1.7
        height = width * PANEL[1] / PANEL[0]
        cx, cy = extent.center().x(), extent.center().y() - height * .14
        extent = QgsRectangle(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)
        ps_map.setLayers([points, satellite])
        ps_map.setKeepLayerSet(True)
        ps_map.zoomToExtent(extent)
        lock_styles(ps_map, [points, satellite])
        ps_map.setZValue(5)
        controls(layout, ps_map, code + '_PS', x, y, 20, 6.5)
        label(layout, code + '_PS_count', 'n = ' + str(points.featureCount()), x + 2, y + 7, 20, 4, 6.7, BLACK).setZValue(50)
        ps_legend(layout, code + '_PS_legend', x, y)
        frame(layout, code + '_PS_frame', x, y, *PANEL)
        assert points.featureCount() == len(observations[bid])
        assert all(ps_map.extent().contains(node.geometry().asPoint()) for node in observations[bid])
        assert all(layer.geometryType() == Qgis.GeometryType.Point for layer in ps_map.layers() if isinstance(layer, QgsVectorLayer))

        for index, (config, letter) in enumerate(zip(configs, case['letters'])):
            source_map = source_layout.itemById('Campus_' + letter)
            x, y = positions[index + 2]
            panel_map = QgsLayoutItemMap(layout)
            panel_map.setId(code + '_' + config['key'])
            layout.addLayoutItem(panel_map)
            panel_map.attemptMove(QgsLayoutPoint(x, y))
            panel_map.attemptResize(QgsLayoutSize(*PANEL))
            panel_map.setCrs(source_map.crs())
            layers, overrides = indicator_layers(source_map)
            panel_map.setLayers(layers)
            panel_map.setKeepLayerSet(True)
            panel_map.setLayerStyleOverrides(overrides)
            panel_map.setKeepLayerStyles(True)
            panel_map.zoomToExtent(source_map.extent())
            panel_map.setZValue(5)
            controls(layout, panel_map, code + '_' + config['key'], x, y, 500, 7)
            level = str(feature[config['class_field']])
            color = config['colors'][CLASSES.index(level)]
            label(layout, code + '_' + config['key'] + '_case', code, x + 2, y + 8, 12, 5,
                  9.5, MAGENTA).setZValue(50)
            label(layout, code + '_' + config['key'] + '_grade',
                  level + (' risk' if config['key'] == 'risk' else ''), x + 2, y + 14., 39, 5.5,
                  9, color).setZValue(50)
            geometry = QgsGeometry(feature.geometry())
            geometry.transform(QgsCoordinateTransform(known.crs(), panel_map.crs(), project))
            point = geometry.pointOnSurface().asPoint()
            e = panel_map.extent()
            anchor = (x + (point.x() - e.xMinimum()) / e.width() * PANEL[0],
                      y + (e.yMaximum() - point.y()) / e.height() * PANEL[1])
            line(layout, code + '_' + config['key'] + '_leader', anchor, (x + 8, y + 12), MAGENTA, .18, True).setZValue(30)
            class_legend(layout, config, code + '_' + config['key'], x, y)
            frame(layout, code + '_' + config['key'] + '_frame', x, y, *PANEL)
            indicator_records.append({'case': code, 'indicator': config['key'], 'level': level,
                                      'class_field': config['class_field'], 'color': color,
                                      'source_map': source_map.id(), 'source_classes_and_styles_unchanged': True})
        rates = [float(f['v_vertical']) for f in observations[bid]]
        case_records.append({'case': code, 'Build_ID': bid, 'PS_count': points.featureCount(),
                             'PS_source': str(PS_SOURCE), 'PS_rate_field': 'v_vertical',
                             'PS_range_mm_yr': [min(rates), max(rates)],
                             'PS_color_limits_mm_yr': list(PS_LIMITS),
                             'PS_points_displaced_or_interpolated': False,
                             'PS_view_extent_32648': ps_map.extent().toString(6),
                             'PS_view_span_m': [ps_map.extent().width(), ps_map.extent().height()],
                             'PS_map_polygon_layers': 0, 'photo_mode': 'Stretch',
                             'photo_panel_mm': list(PANEL), 'all_panel_positions_mm': positions})

    for item in layout.items():
        if isinstance(item, (QgsLayoutItemLabel, QgsLayoutItemScaleBar)):
            font = item.textFormat().font()
            assert font.family() == 'Arial' and font.bold(), item.id()
    project.setCustomVariables(dict(project.customVariables(), composite_layout='left map + 2 x 6 case panels',
        observed_PS_counts='34360:61;35945:104', PS_display_field='v_vertical', PS_shared_color_limits='-2,4',
        photo_display='Stretched to identical 46 x 44 mm panels by user request',
        satellite_PS_building_outlines=False, source_case_project=str(CASE_PROJECT)))
    assert project.write(str(TARGET))
    template = ROOT / 'plot/13_event_validation/qgis/layouts/13_event_validation/13_event_validation.qpt'
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(template)))
    assert layout.saveAsTemplate(str(template), context)
    exporter = QgsLayoutExporter(layout)
    preview = FIG_DIR / (STEM + '_preview.png')
    image = exporter.renderPageToImage(0, dpi=150)
    assert not image.isNull() and image.save(str(preview))
    outputs = [str(preview)]
    if not preview_only:
        image = exporter.renderPageToImage(0, dpi=600)
        image.setDotsPerMeterX(round(600 / .0254))
        image.setDotsPerMeterY(round(600 / .0254))
        png = FIG_DIR / (STEM + '_600dpi.png')
        assert not image.isNull() and image.save(str(png))
        del image
        pdf_temp = OUT / 'tmp/pdfs' / (STEM + '_export.pdf')
        if pdf_temp.exists():
            pdf_temp.unlink()
        pdf = QgsLayoutExporter.PdfExportSettings()
        pdf.dpi = 600
        pdf.forceVectorOutput = True
        pdf.textRenderFormat = Qgis.TextRenderFormat.AlwaysOutlines
        assert exporter.exportToPdf(str(pdf_temp), pdf) == QgsLayoutExporter.Success
        pdf_path = FIG_DIR / (STEM + '.pdf')
        pdf_temp.replace(pdf_path)
        outputs += [str(png), str(pdf_path)]
    restored = QgsProject()
    assert restored.read(str(TARGET))
    assert all(layer.isValid() for layer in restored.mapLayers().values())
    restored_layout = restored.layoutManager().layoutByName(layout.name())
    maps = [item for item in restored_layout.items() if isinstance(item, QgsLayoutItemMap)]
    assert len(maps) == 13, len(maps)
    for case in CASES:
        photo = restored_layout.itemById(case['code'] + '_damage_photo')
        assert photo.resizeMode() == QgsLayoutItemPicture.Stretch
        assert abs(photo.sizeWithUnits().width() - PANEL[0]) < 1e-6
        assert abs(photo.sizeWithUnits().height() - PANEL[1]) < 1e-6
    assert all(sha(path) == digest for path, digest in protected.items())
    manifest = {'project': str(TARGET), 'layout': layout.name(), 'template': str(template),
                'page_mm': list(PAGE), 'font': 'Arial Bold', 'case_panel_mm': list(PANEL),
                'layout_pattern': 'Scaled native location map on left; two framed 2x3 case grids on right',
                'location_map_scale_factor': 1.1, 'cases': case_records, 'indicator_checks': indicator_records,
                'map_count': len(maps), 'photo_count': 2, 'PS_source_records': 165,
                'source_files_unchanged': True, 'source_sha256': protected,
                'all_layers_valid_after_reload': True, 'outputs': outputs, 'preview_only': preview_only}
    (CHECK_DIR / (STEM + '_manifest.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'source_sha256'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview-only', action='store_true')
    options = parser.parse_args()
    app = QgsApplication([], False)
    app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis', True)
    app.initQgis()
    main(options.preview_only)
    os._exit(0)
