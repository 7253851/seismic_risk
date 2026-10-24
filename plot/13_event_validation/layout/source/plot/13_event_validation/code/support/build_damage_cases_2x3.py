"""Split the original campus H/V/E/R figure into two compact 2x3 case figures.

Each case contains its original damage photo, remote sensing, H, V, E and R.
Original coverage and building styles are retained, with larger annotation margins.
"""
from pathlib import Path
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

from qgis.core import *
from qgis.PyQt.QtCore import Qt, QPointF, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QImageReader, QPolygonF

from build_campus_2x3 import rectangle, text
from build_campus_hver import NAMES, appearance, halo_text

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'result/validation/13_event_validation/maps'
ASSETS = OUT / 'damage_cases_2x3'
SOURCE = ROOT/'QGIS/13_event_validation/support/validation_campuses_2x5.qgz'
TARGET = ROOT/'QGIS/13_event_validation/support/validation_damage_cases_2x3.qgz'
PAGE = (278, 216)
PANEL = (86, 82)
FONT = dict(header=30, title=24, campus=20, damage=23, grade=23,
            legend=14, scale=16, north=17, key=16)
CASES = [
    dict(code='D1', case_id='CF', campus='YUFE South', Build_ID=34360,
         letters='abcde', stem='validation_D1_YUFE_2x3'),
    dict(code='D2', case_id='NY', campus='YNAU West', Build_ID=35945,
         letters='fghij', stem='validation_D2_YNAU_2x3'),
]
ROLES = ['remote sensing', 'hazard', 'vulnerability', 'exposure', 'risk']
POSITIONS = [(96, 27), (186, 27), (6, 128), (96, 128), (186, 128)]
TITLE_NAMES = ['Remote sensing', 'Hazard', 'Vulnerability', 'Exposure', 'Risk']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def administrative(layer):
    return '/data/administrative/' in layer.source().replace('\\', '/')


def complete_satellite(map_item, imagery):
    rasters = [layer for layer in map_item.layers()
               if isinstance(layer, QgsRasterLayer) and 'remote sensing imagery' in layer.name()]
    assert len(rasters) == 1
    satellite = rasters[0]
    satellite.setDataSource(str(ROOT / imagery['tif']), satellite.name(), 'gdal', False)
    assert satellite.isValid()
    assert satellite.crs() == map_item.crs()
    assert satellite.extent().contains(map_item.extent())
    satellite.setCustomProperty('validation/full_frame_coverage', True)
    metadata = satellite.metadata()
    metadata.setAbstract('Locally cached World Imagery covering the full enlarged display window. '
                         'Georeferenced to the source imagery coordinates; no stretching. '
                         'Mosaic acquisition dates vary; spatial context only.')
    satellite.setMetadata(metadata)
    map_item.refresh()


def framed_extent(source):
    """Add display margins, retaining all original map coverage above the larger key."""
    extent = QgsRectangle(source)
    width, height = extent.width(), extent.height()
    return QgsRectangle(extent.xMinimum() - .11 * width, extent.yMinimum() - .19 * height,
                        extent.xMaximum() + .11 * width, extent.yMaximum() + .03 * height)


def font_size(item, size, stretch=100):
    fmt = item.textFormat()
    font = QFont('Arial')
    font.setBold(True)
    font.setStretch(stretch)
    fmt.setFont(font)
    fmt.setSize(size)
    item.setTextFormat(fmt)


def enlarge_campus_labels(map_item):
    overrides = map_item.layerStyleOverrides()
    for layer in map_item.layers():
        if not isinstance(layer, QgsVectorLayer) or not layer.labelsEnabled():
            continue
        temporary = layer.clone()
        QgsMapLayerStyle(overrides[layer.id()]).writeToLayer(temporary)
        settings = temporary.labeling().settings()
        fmt = settings.format()
        fmt.setFont(QFont('Arial', FONT['campus'], QFont.Bold))
        fmt.setSize(FONT['campus'])
        halo = fmt.buffer()
        halo.setSize(.75)
        fmt.setBuffer(halo)
        settings.setFormat(fmt)
        temporary.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        style = QgsMapLayerStyle()
        style.readFromLayer(temporary)
        overrides[layer.id()] = style.xmlData()
    map_item.setLayerStyleOverrides(overrides)


def restyle_damage(layout, map_item, letter, case, indicator):
    label = layout.itemById('Damage_' + case['code'] + '_' + letter)
    px, py = map(float, str(label.customProperty('validation/target_3857')).split(','))
    extent = map_item.extent()
    x, y = map_item.pos().x(), map_item.pos().y()
    point = QPointF(x + (px - extent.xMinimum()) / extent.width() * PANEL[0],
                    y + (extent.yMaximum() - py) / extent.height() * PANEL[1])
    if indicator:
        dx, dy = (3, 17) if case['code'] == 'D1' else (3, 14)
    else:
        dx, dy = (67, 49) if case['code'] == 'D1' else (4, 45)
    label.attemptMove(QgsLayoutPoint(x + dx, y + dy))
    label.attemptResize(QgsLayoutSize(18, 10))
    font_size(label, FONT['damage'])
    halo_text(label, .7)
    old_leader = layout.itemById('Damage_leader_' + letter)
    layout.removeLayoutItem(old_leader)
    endpoint = QPointF(x + dx + (16 if dx < 40 else 0), y + dy + 5)
    line = QgsLayoutItemPolyline(QPolygonF([point, endpoint]), layout)
    line.setId('Damage_leader_' + letter)
    symbol = QgsLineSymbol.createSimple({'line_color': 'white', 'line_width': '.9'})
    symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color': '#B20A8F', 'line_width': '.35'}))
    line.setSymbol(symbol)
    layout.addLayoutItem(line)
    line.setZValue(30)
    if indicator:
        grade = layout.itemById('Damage_Grade_' + letter)
        grade.attemptMove(QgsLayoutPoint(x + dx, y + dy + 11))
        grade.attemptResize(QgsLayoutSize(65, 11))
        font_size(grade, FONT['grade'])


def panel_items(layout, letter, code):
    prefixes = ['Campus_', 'Title_', 'Damage_leader_', 'Damage_Grade_',
                'North_', 'True_North_', 'Scale_']
    ids = [prefix + letter for prefix in prefixes]
    ids.append('Damage_' + code + '_' + letter)
    return [item for id_ in ids if (item := layout.itemById(id_)) is not None]


def legend(layout, config, map_item):
    """A large five-class strip inside the bottom of each indicator map."""
    x, y = map_item.pos().x() + 3, map_item.pos().y()
    if config['key'] == 'hazard':
        title = text(layout, 'Legend_hazard_units', 'PGA (g)', x, y + 56.3, 37, 7, 16)
        halo_text(title, .4)
        title.setZValue(40)
    for i, (name, color) in enumerate(zip(NAMES, config['colors'])):
        xx = x + i * 16
        item = rectangle(layout, xx, y + 64.5, 15.5, 4, color, '#48545A', .12)
        item.setId('Legend_swatch_' + config['key'] + '_' + str(i))
        item.setZValue(40)
        caption = name.replace(' ', '\n')
        label = text(layout, 'Legend_' + config['key'] + '_' + str(i), caption,
                     xx - .2, y + 69, 16, 12, FONT['legend'])
        font_size(label, FONT['legend'], 88)
        label.setHAlign(Qt.AlignHCenter)
        halo_text(label, .4)
        label.setZValue(41)


def controls(layout, map_item, letter):
    """Transparent true-north arrow and linked 500 m scale on every map."""
    for prefix in ['North_', 'True_North_', 'Scale_']:
        old = layout.itemById(prefix + letter)
        if old is not None:
            layout.removeLayoutItem(old)
    x, y = map_item.pos().x(), map_item.pos().y()
    north = text(layout, 'North_' + letter, 'N', x + 74, y + 1, 9, 7, FONT['north'])
    north.setHAlign(Qt.AlignHCenter)
    halo_text(north, .45)
    north.setZValue(41)
    arrow = QgsLayoutItemPicture(layout)
    layout.addLayoutItem(arrow)
    arrow.setId('True_North_' + letter)
    arrow.attemptMove(QgsLayoutPoint(x + 75.7, y + 8.5))
    arrow.attemptResize(QgsLayoutSize(5.5, 9))
    arrow.setPicturePath(str(OUT / 'campus_hver/north_arrow_reference.svg'))
    arrow.setLinkedMap(map_item)
    arrow.setNorthMode(QgsLayoutItemPicture.TrueNorth)
    arrow.setBackgroundEnabled(False)
    arrow.setFrameEnabled(False)
    arrow.setZValue(40)
    scale = QgsLayoutItemScaleBar(layout)
    scale.setId('Scale_' + letter)
    scale.setStyle('Line Ticks Up')
    scale.setLinkedMap(map_item)
    scale.setUnits(Qgis.DistanceUnit.Meters)
    scale.setUnitsPerSegment(500)
    scale.setNumberOfSegments(1)
    scale.setNumberOfSegmentsLeft(0)
    scale.setUnitLabel('m')
    scale.setHeight(1)
    fmt = QgsTextFormat()
    fmt.setFont(QFont('Arial', FONT['scale'], QFont.Bold))
    fmt.setSize(FONT['scale'])
    fmt.setColor(QColor('#24282B'))
    halo = QgsTextBufferSettings()
    halo.setEnabled(True)
    halo.setSize(.45)
    halo.setColor(QColor('white'))
    fmt.setBuffer(halo)
    scale.setTextFormat(fmt)
    line = QgsLineSymbol.createSimple({'line_color': 'white', 'line_width': '.8'})
    line.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color': '#24282B', 'line_width': '.22'}))
    scale.setLineSymbol(line)
    scale.setLabelBarSpace(.5)
    scale.setBoxContentSpace(.5)
    scale.setBackgroundEnabled(False)
    scale.setFrameEnabled(False)
    layout.addLayoutItem(scale)
    scale.attemptResize(QgsLayoutSize(1, 1))
    scale_y = 69 if map_item.customProperty('validation/role') == 'remote sensing' else 3
    scale.attemptMove(QgsLayoutPoint(x + 3, y + scale_y))
    scale.setZValue(41)


def boundary_legend(layout, map_item, case):
    """Place common boundary/damage keys on the remote-sensing basemap."""
    x, y = map_item.pos().x(), map_item.pos().y()
    for i, (color, label) in enumerate([
        ('#08A9BE', 'Boundary'),
        ('#A6A6A6', 'No data'),
        ('#D827C8', f"{case['code']} damage"),
    ]):
        yy = y + 3 + i * 9
        key = rectangle(layout, x + 3, yy, 7.5, 3.5, 'transparent', 'white', .85)
        symbol = QgsFillSymbol.createSimple({'style': 'no', 'outline_color': 'white', 'outline_width': '.85'})
        symbol.appendSymbolLayer(QgsSimpleFillSymbolLayer.create({'style': 'no', 'outline_color': color, 'outline_width': '.42'}))
        key.setSymbol(symbol)
        key.setId('Case_key_symbol_' + str(i))
        key.setZValue(40)
        label = text(layout, 'Case_key_' + str(i), label, x + 13, yy - 2, 57, 8, FONT['key'])
        halo_text(label, .5)
        label.setZValue(41)


def save_image(layout, path, dpi):
    image = QgsLayoutExporter(layout).renderPageToImage(0, dpi=dpi)
    assert not image.isNull()
    image.setDotsPerMeterX(round(dpi / .0254))
    image.setDotsPerMeterY(round(dpi / .0254))
    assert image.save(str(path)), path


def export_vector(layout, case):
    """Outline text; use clipped high-resolution map tiles for portable SVG rendering."""
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = 1200
    settings.forceVectorOutput = True
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysOutlines
    settings.simplifyGeometries = False
    assert QgsLayoutExporter(layout).exportToPdf(str(OUT / (case['stem'] + '.pdf')), settings) == QgsLayoutExporter.Success
    maps = [layout.itemById('Campus_' + letter) for letter in case['letters']]
    items = [item for item in layout.items() if isinstance(item, QgsLayoutItem)]
    visibility = [(item, item.isVisible()) for item in items]
    raster_paths = []
    for map_item in maps:
        for item, visible in visibility:
            item.setVisible(isinstance(item, QgsLayoutItemPage) or item == map_item)
        region = QRectF(map_item.pos().x(), map_item.pos().y(), PANEL[0], PANEL[1])
        image = QgsLayoutExporter(layout).renderRegionToImage(region, dpi=450)
        assert not image.isNull()
        path = ASSETS / (case['code'] + '_' + map_item.id() + '_PPT_map.png')
        assert image.save(str(path))
        raster_paths.append(path)
        del image
    for item, visible in visibility:
        item.setVisible(visible)
    pictures = []
    for map_item, path in zip(maps, raster_paths):
        map_item.setVisible(False)
        picture = QgsLayoutItemPicture(layout)
        layout.addLayoutItem(picture)
        picture.setResizeMode(QgsLayoutItemPicture.Stretch)
        picture.attemptMove(QgsLayoutPoint(map_item.pos().x(), map_item.pos().y()))
        picture.attemptResize(QgsLayoutSize(*PANEL))
        picture.setPicturePath(str(path))
        picture.setZValue(map_item.zValue())
        picture.setBackgroundEnabled(False)
        picture.setFrameEnabled(True)
        picture.setFrameStrokeColor(QColor('#26343B'))
        picture.setFrameStrokeWidth(QgsLayoutMeasurement(.25))
        pictures.append(picture)
    svg = QgsLayoutExporter.SvgExportSettings()
    svg.dpi = 450
    svg.forceVectorOutput = True
    svg.textRenderFormat = Qgis.TextRenderFormat.AlwaysOutlines
    svg.simplifyGeometries = False
    assert QgsLayoutExporter(layout).exportToSvg(str(OUT / (case['stem'] + '_PPT.svg')), svg) == QgsLayoutExporter.Success
    for picture in pictures:
        layout.removeLayoutItem(picture)
    for item, visible in visibility:
        item.setVisible(visible)
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(OUT / (case['stem'] + '.qpt'))))
    assert layout.saveAsTemplate(str(OUT / (case['stem'] + '.qpt')), context)


def verify(project, manifest, original):
    """Verify saved map stacks, extents, classes, photos and 2x3 positions."""
    assert all(layer.isValid() for layer in project.mapLayers().values())
    assert not any(administrative(layer) for layer in project.mapLayers().values())
    assert len(project.layoutManager().layouts()) == 2
    source_layout = original.layoutManager().layoutByName('Validation_Campuses_HVER')
    checks = []
    for case in manifest['cases']:
        layout = project.layoutManager().layoutByName(case['layout'])
        assert layout and layout.pageCollection().pageCount() == 1
        size = layout.pageCollection().pages()[0].pageSize()
        assert (size.width(), size.height()) == PAGE
        maps = [item for item in layout.items() if isinstance(item, QgsLayoutItemMap)]
        assert len(maps) == 5
        photo = layout.itemById('Damage_photo_' + case['code'])
        assert isinstance(photo, QgsLayoutItemPicture)
        assert Path(photo.picturePath()).resolve() == Path(case['photo']).resolve()
        assert sha(photo.picturePath()) == case['photo_sha256']
        assert photo.resizeMode() == QgsLayoutItemPicture.Zoom
        assert photo.pictureAnchor() == QgsLayoutItem.UpperLeft
        assert int(photo.customProperty('validation/Build_ID')) == case['Build_ID']
        photo_size = QImageReader(photo.picturePath()).size()
        assert abs(photo.sizeWithUnits().width() / photo.sizeWithUnits().height()
                   - photo_size.width() / photo_size.height()) < 1e-6
        frame = layout.itemById('Damage_photo_frame_' + case['code'])
        assert abs(frame.pos().x() - photo.pos().x()) < .0001
        assert abs(frame.pos().y() - photo.pos().y()) < .0001
        assert abs(frame.sizeWithUnits().width() - photo.sizeWithUnits().width()) < .0001
        assert abs(frame.sizeWithUnits().height() - photo.sizeWithUnits().height()) < .0001
        for index, letter in enumerate(case['letters']):
            current = layout.itemById('Campus_' + letter)
            source = source_layout.itemById('Campus_' + letter)
            expected_extent = framed_extent(source.extent())
            assert all(abs(a - b) < 1e-5 for a, b in zip(
                [current.extent().xMinimum(), current.extent().yMinimum(), current.extent().xMaximum(), current.extent().yMaximum()],
                [expected_extent.xMinimum(), expected_extent.yMinimum(), expected_extent.xMaximum(), expected_extent.yMaximum()]))
            assert current.extent().contains(source.extent())
            current_styles = {key: ET.canonicalize(value, strip_text=True)
                              for key, value in current.layerStyleOverrides().items()}
            source_styles = {key: ET.canonicalize(value, strip_text=True)
                             for key, value in source.layerStyleOverrides().items()}
            allowed_ids = {layer.id() for layer in source.layers() if not administrative(layer)}
            source_styles = {key: value for key, value in source_styles.items() if key in allowed_ids}
            assert current_styles.keys() == source_styles.keys()
            for key in current_styles:
                current_xml, source_xml = ET.fromstring(current_styles[key]), ET.fromstring(source_styles[key])
                if index == 0 and current_xml.find('labeling') is not None:
                    assert float(current_xml.find('./labeling/settings/text-style').get('fontSize')) == FONT['campus']
                    current_xml.remove(current_xml.find('labeling'))
                    source_xml.remove(source_xml.find('labeling'))
                    for node in [current_xml, source_xml]:
                        for tag in ['referencedLayers', 'referencingLayers']:
                            empty = node.find(tag)
                            if empty is not None and len(empty) == 0:
                                node.remove(empty)
                assert ET.canonicalize(ET.tostring(current_xml, encoding='unicode'), strip_text=True) == ET.canonicalize(ET.tostring(source_xml, encoding='unicode'), strip_text=True)
            assert [layer.id() for layer in current.layers()] == [layer.id() for layer in source.layers() if not administrative(layer)]
            assert abs(current.pos().x() - POSITIONS[index][0]) < 1e-6
            assert abs(current.pos().y() - POSITIONS[index][1]) < 1e-6
            assert current.sizeWithUnits().width() == PANEL[0]
            assert current.sizeWithUnits().height() == PANEL[1]
            assert layout.itemById('Title_' + letter).text() == f'({chr(98 + index)}) {TITLE_NAMES[index]}'
            assert layout.itemById('Title_' + letter).textFormat().size() == FONT['title']
            damage = layout.itemById('Damage_' + case['code'] + '_' + letter)
            assert damage.text() == case['code']
            assert int(damage.customProperty('validation/Build_ID')) == case['Build_ID']
            known = [layer for layer in current.layers() if 'photographed damage' in layer.name()]
            assert len(known) == 1
            features = list(known[0].getFeatures())
            assert len(features) == 1 and features[0]['Build_ID'] == case['Build_ID']
            if index:
                config = manifest['configs'][index - 1]
                grade = layout.itemById('Damage_Grade_' + letter)
                level = features[0][config['class_field']]
                assert grade.customProperty('validation/class') == level
                assert grade.text() == (level + ' risk' if config['key'] == 'risk' else level)
                assert grade.textFormat().color().name() == config['colors'][NAMES.index(level)]
                assert grade.textFormat().size() == FONT['grade']
                for i, color in enumerate(config['colors']):
                    swatch = layout.itemById('Legend_swatch_' + config['key'] + '_' + str(i))
                    label = layout.itemById('Legend_' + config['key'] + '_' + str(i))
                    assert swatch.symbol().color().name() == color
                    assert label.textFormat().size() == FONT['legend']
                    for legend_item in [swatch, label]:
                        assert legend_item.zValue() > current.zValue()
                        assert legend_item.pos().x() >= current.pos().x()
                        assert legend_item.pos().y() >= current.pos().y()
                        assert legend_item.pos().x() + legend_item.sizeWithUnits().width() <= current.pos().x() + PANEL[0]
                        assert legend_item.pos().y() + legend_item.sizeWithUnits().height() <= current.pos().y() + PANEL[1]
            for prefix in ['North_', 'True_North_', 'Scale_']:
                control = layout.itemById(prefix + letter)
                assert control and not control.hasBackground() and not control.frameEnabled()
                assert control.zValue() > current.zValue()
                assert control.pos().x() >= current.pos().x()
                assert control.pos().y() >= current.pos().y()
                assert control.pos().x() + control.sizeWithUnits().width() <= current.pos().x() + PANEL[0]
                assert control.pos().y() + control.sizeWithUnits().height() <= current.pos().y() + PANEL[1]
            assert layout.itemById('Scale_' + letter).linkedMap() == current
            assert layout.itemById('Scale_' + letter).unitsPerSegment() == 500
            assert layout.itemById('True_North_' + letter).linkedMap() == current
            checks.append(dict(case=case['code'], panel=chr(98 + index), role=ROLES[index],
                               original_coverage_retained=True, renderer_unchanged=True))
        satellite = layout.itemById('Campus_' + case['letters'][0])
        imagery = next(record for record in manifest['satellite_imagery']['cases']
                       if record['case_id'] == case['case_id'])
        image_layers = [layer for layer in satellite.layers()
                        if isinstance(layer, QgsRasterLayer) and 'remote sensing imagery' in layer.name()]
        assert len(image_layers) == 1
        assert Path(image_layers[0].source()).resolve() == (ROOT / imagery['tif']).resolve()
        assert image_layers[0].extent().contains(satellite.extent())
        assert image_layers[0].customProperty('validation/full_frame_coverage')
        for i in range(3):
            for id_ in ['Case_key_' + str(i), 'Case_key_symbol_' + str(i)]:
                key = layout.itemById(id_)
                assert key.zValue() > satellite.zValue()
                assert key.pos().x() >= satellite.pos().x()
                assert key.pos().y() >= satellite.pos().y()
                assert key.pos().x() + key.sizeWithUnits().width() <= satellite.pos().x() + PANEL[0]
                assert key.pos().y() + key.sizeWithUnits().height() <= satellite.pos().y() + PANEL[1]
        for item in layout.items():
            if isinstance(item, (QgsLayoutItemLabel, QgsLayoutItemScaleBar)):
                font = item.textFormat().font()
                assert font.family() == 'Arial' and font.bold(), item.id()
            if isinstance(item, QgsLayoutItem) and not isinstance(item, QgsLayoutItemPage):
                assert item.pos().x() >= 0 and item.pos().y() >= 0, item.id()
                assert item.pos().x() + item.sizeWithUnits().width() <= PAGE[0] + .01, item.id()
                assert item.pos().y() + item.sizeWithUnits().height() <= PAGE[1] + .01, item.id()
        save_image(layout, ASSETS / (case['code'] + '_reloaded_preview.png'), 180)
    bases = [layer for layer in project.mapLayers().values()
             if layer.customProperty('validation/hazard_basemap_source_id', '')]
    assert all(appearance(layer) == layer.customProperty('validation/hazard_basemap_style_sha256') for layer in bases)
    confirmed = QgsVectorLayer(str(OUT / 'campus_hver/confirmed_damage.fgb'), 'confirmed', 'ogr')
    assert sorted(feature['Build_ID'] for feature in confirmed.getFeatures()) == [34360, 35945, 45948]
    assert all(sha(path) == value for path, value in manifest['protected_sha256'].items())
    return dict(layouts=2, rows=2, columns=3, photos=2, maps=10,
                font='Arial Bold', photo_aspect_ratios_preserved=True,
                photo_frames_fit_images=True, north_arrows=10, scale_bars=10,
                indicator_legends_inside_maps=True, boundary_legends_on_satellite=True,
                administrative_boundary_layers=0, administrative_labels=0,
                satellite_views_fully_covered=True,
                satellite_pixels=[record['pixels'] for record in manifest['satellite_imagery']['cases']],
                page_mm=PAGE,
                presentation_font_sizes_pt=FONT,
                map_checks=checks, basemap_styles_unchanged=True,
                source_files_unchanged=True, original_three_positive_records_retained=True)


def main():
    ASSETS.mkdir(exist_ok=True)
    if '--export-only' in sys.argv:
        project = QgsProject()
        assert project.read(str(TARGET))
        for case in CASES:
            export_vector(project.layoutManager().layoutByName('Validation_' + case['code'] + '_2x3'), case)
        print('PPT vector exports updated', flush=True)
        os._exit(0)
    preview_only = '--preview-only' in sys.argv
    satellite_imagery = json.loads((ASSETS / 'satellite_full_manifest.json').read_text())
    configs = json.loads((OUT / 'campus_hver/data_manifest.json').read_text())['configs']
    protected_paths = [SOURCE, OUT / 'campus_hver/campus_hver.fgb',
                       OUT / 'campus_hver/campus_boundaries.fgb',
                       OUT / 'campus_hver/confirmed_damage.fgb']
    protected_paths += [OUT / 'damage_distribution_collage' / (case['code'] + '_damage_photo.png') for case in CASES]
    protected_paths += [ROOT / case['tif'] for case in satellite_imagery['cases']]
    protected = {str(path): sha(path) for path in protected_paths}
    project = QgsProject()
    assert project.read(str(SOURCE))
    manager = project.layoutManager()
    source_layout = manager.layoutByName('Validation_Campuses_HVER')
    assert source_layout
    originals = QgsProject()
    assert originals.read(str(SOURCE))
    records = []
    for case in CASES:
        layout = manager.duplicateLayout(source_layout, 'Validation_' + case['code'] + '_2x3')
        assert layout
        keep = {item.uuid() for letter in case['letters'] for item in panel_items(layout, letter, case['code'])}
        for item in list(layout.items()):
            if isinstance(item, QgsLayoutItem) and not isinstance(item, QgsLayoutItemPage) and item.uuid() not in keep:
                layout.removeLayoutItem(item)
        layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(*PAGE))
        layout.renderContext().setDpi(1200)
        for index, letter in enumerate(case['letters']):
            map_item = layout.itemById('Campus_' + letter)
            dx = POSITIONS[index][0] - map_item.pos().x()
            dy = POSITIONS[index][1] - map_item.pos().y()
            for item in panel_items(layout, letter, case['code']):
                item.attemptMove(QgsLayoutPoint(item.pos().x() + dx, item.pos().y() + dy))
            map_item.setCustomProperty('validation/panel', chr(98 + index))
            map_item.setCustomProperty('validation/role', ROLES[index])
            layers = [layer for layer in map_item.layers() if not administrative(layer)]
            map_item.setLayers(layers)
            allowed_ids = {layer.id() for layer in layers}
            map_item.setLayerStyleOverrides({key: value for key, value in map_item.layerStyleOverrides().items() if key in allowed_ids})
            map_item.zoomToExtent(framed_extent(source_layout.itemById('Campus_' + letter).extent()))
            title = layout.itemById('Title_' + letter)
            title.setText(f'({chr(98 + index)}) {TITLE_NAMES[index]}')
            title.attemptMove(QgsLayoutPoint(map_item.pos().x(), map_item.pos().y() - 12))
            title.attemptResize(QgsLayoutSize(86, 10))
            font_size(title, FONT['title'])
            if index == 0:
                imagery = next(record for record in satellite_imagery['cases'] if record['case_id'] == case['case_id'])
                complete_satellite(map_item, imagery)
                enlarge_campus_labels(map_item)
            restyle_damage(layout, map_item, letter, case, index > 0)
            controls(layout, map_item, letter)
            if index:
                legend(layout, configs[index - 1], map_item)
        text(layout, 'Case_header', f"{case['code']} | {case['campus']} | Building {case['Build_ID']}",
             6, 1, 266, 12, FONT['header'])
        photo_path = OUT / 'damage_distribution_collage' / (case['code'] + '_damage_photo.png')
        size = QImageReader(str(photo_path)).size()
        assert size.isValid()
        photo_width = PANEL[1] * size.width() / size.height()
        assert photo_width <= PANEL[0]
        photo_x = 6 + (PANEL[0] - photo_width) / 2
        text(layout, 'Photo_title', '(a) Damage photo', photo_x, 15, 86, 10, FONT['title'])
        frame = rectangle(layout, photo_x, 27, photo_width, PANEL[1], 'white', '#26343B', .25)
        frame.setId('Damage_photo_frame_' + case['code'])
        frame.setZValue(3)
        photo = QgsLayoutItemPicture(layout)
        photo.setId('Damage_photo_' + case['code'])
        layout.addLayoutItem(photo)
        photo.setResizeMode(QgsLayoutItemPicture.Zoom)
        photo.setPictureAnchor(QgsLayoutItem.UpperLeft)
        photo.attemptMove(QgsLayoutPoint(photo_x, 27))
        photo.attemptResize(QgsLayoutSize(photo_width, PANEL[1]))
        photo.setPicturePath(str(photo_path))
        photo.setCustomProperty('validation/Build_ID', case['Build_ID'])
        photo.setCustomProperty('validation/role', 'damage photograph')
        photo.setBackgroundEnabled(False)
        photo.setFrameEnabled(False)
        photo.setZValue(2)
        # The outline follows the photo bounds, with no fill over its pixels.
        frame.setSymbol(QgsFillSymbol.createSimple({'style': 'no', 'outline_color': '#26343B', 'outline_width': '.25'}))
        boundary_legend(layout, layout.itemById('Campus_' + case['letters'][0]), case)
        records.append(dict(case, layout=layout.name(), photo=str(photo_path),
                            photo_sha256=sha(photo_path), panel_order=['damage photograph', *ROLES],
                            rows=2, columns=3, page_mm=PAGE))
    manager.removeLayout(source_layout)
    removed_admin = [dict(id=layer.id(), name=layer.name(), source=layer.source())
                     for layer in project.mapLayers().values() if administrative(layer)]
    project.removeMapLayers([layer['id'] for layer in removed_admin])
    project.setTitle('D1 / D2 damage cases | two separate 2x3 layouts')
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    variables = dict(project.customVariables())
    variables.update(layout_grid='2 separate layouts, each 2 rows x 3 columns',
                     indicator_order='damage photograph, remote sensing, H, V, E, R',
                     photograph_layout='one original photograph per case, aspect ratio preserved',
                     photograph_frame='fits original photo bounds',
                     orientation_and_scale='inside all five maps per case; transparent backgrounds',
                     legends='class strips inside indicator maps; boundary/damage keys on remote sensing',
                     presentation_typography=json.dumps(FONT),
                     map_display_margin='Original extent retained inside a 22% larger display window; extra southern margin for large type keys',
                     administrative_boundaries='removed: district and township/street divisions and their labels',
                     satellite_coverage='Full enlarged window covered by new 4096 px real imagery caches; original georeferencing retained',
                     source_figure=str(SOURCE))
    project.setCustomVariables(variables)
    assert project.write(str(TARGET))
    manifest = dict(project=str(TARGET), source_project=str(SOURCE), cases=records,
                    configs=configs, protected_sha256=protected, pdf_dpi=1200,
                    presentation_font_sizes_pt=FONT,
                    removed_administrative_layers=removed_admin,
                    satellite_imagery=satellite_imagery,
                    preview_only=preview_only)
    for case in records:
        layout = manager.layoutByName(case['layout'])
        for dpi, suffix in ([(180, 'preview')] if preview_only else [(180, 'preview'), (1200, '1200dpi')]):
            save_image(layout, OUT / (case['stem'] + '_' + suffix + '.png'), dpi)
        if preview_only:
            continue
        save_image(layout, OUT / (case['stem'] + '_PPT.png'), (3840.1 * .0254 / (PAGE[0] / 1000)))
        export_vector(layout, case)
    restored = QgsProject()
    assert restored.read(str(TARGET))
    verification = verify(restored, manifest, originals)
    (ASSETS / 'layout_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    (ASSETS / 'reload_verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(verification, ensure_ascii=False), flush=True)
    os._exit(0)


if __name__ == '__main__':
    app = QgsApplication([], False)
    app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis', True)
    app.initQgis()
    main()
