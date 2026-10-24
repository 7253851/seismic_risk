"""Place the saved, editable figure 1 at manuscript size on an A4 portrait page.

Default output is draft-only. No publishing, dataset edits, or legacy rebuilds.
Run with plot/shared/qgis/scripts/run_pyqgis.sh.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET

from qgis.core import (
    QgsApplication, QgsProject, QgsPrintLayout, QgsReadWriteContext,
    QgsPathResolver, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutPoint,
    QgsLayoutSize, QgsLayoutExporter, Qgis,
)
from qgis.PyQt.QtCore import QRectF, QSize
from qgis.PyQt.QtXml import QDomDocument

WORKSPACE = Path(__file__).resolve().parents[5]
# Draft output; the adopted files in layout/ itself are never written.
LAYOUT_WORK = WORKSPACE / 'plot/01_study_area/layout/work'
SOURCE = WORKSPACE / 'plot/01_study_area/qgis/projects/01_study_area.qgz'
SOURCE_LAYOUT = 'Kunming_Study_Area'
LAYOUT_NAME = 'Kunming_Study_Area_A4_6pt'
A4_MM = (210.0, 297.0)
# Measured from the current manuscript PDF: 443.2520712 pt, 0.95 textwidth.
PAPER_FIGURE_WIDTH_MM = 156.36948067333336
MINIMUM_FONT_PT = 6.0
FONT_SIZES_PT = {
    'coordinates_north_scale': 6.0,
    'district_legend_elevation_ticks': 6.5,
    'fault_earthquake_gnss': 7.5,
    'lake': 8.5,
    'kunming_elevation_titles': 9.5,
}
PHYSICAL_UNITS = {'MM', 'Point', 'Points', 'Inch', 'Inches', 'Pixel', 'Pixels'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def multiply(value, factor):
    """Scale numeric dimensions, including comma/semicolon separated offsets."""
    return re.sub(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?',
                  lambda m: format(float(m.group()) * factor, '.15g'), value)


def scale_measure(value, factor, offset=None):
    parts = value.split(',')
    if parts[-1] != 'mm':
        raise ValueError('Expected millimetre layout geometry: ' + value)
    numbers = [float(v) * factor for v in parts[:-1]]
    if offset is not None:
        numbers = [v + delta for v, delta in zip(numbers, offset)]
    return ','.join([*(format(v, '.15g') for v in numbers), 'mm'])


def scale_physical_styles(root, factor):
    """Scale millimetre symbols/halos without changing colours or map units."""
    for element in root.iter():
        if element.tag == 'Option' and element.get('type') == 'Map':
            options = {child.get('name'): child for child in element.findall('./Option')}
            for key, unit in options.items():
                if not key or unit.get('value') not in PHYSICAL_UNITS:
                    continue
                for suffix in ('_unit', '_units'):
                    if key.endswith(suffix) and key[:-len(suffix)] in options:
                        item = options[key[:-len(suffix)]]
                        item.set('value', multiply(item.get('value', '0'), factor))
                        break
        pairs = {
            'bufferSizeUnits': ['bufferSize'],
            'maskSizeUnits': ['maskSize', 'maskSize2'],
            'shapeSizeUnit': ['shapeSizeX', 'shapeSizeY'],
            'shapeOffsetUnit': ['shapeOffsetX', 'shapeOffsetY'],
            'shapeRadiiUnit': ['shapeRadiiX', 'shapeRadiiY'],
            'shapeBorderWidthUnit': ['shapeBorderWidth'],
            'shadowOffsetUnit': ['shadowOffsetDist'],
            'shadowRadiusUnit': ['shadowRadius'],
            'distUnits': ['dist'], 'offsetUnits': ['xOffset', 'yOffset'],
            'repeatDistanceUnits': ['repeatDistance'],
            'overrunDistanceUnit': ['overrunDistance'],
            'maximumDistanceUnit': ['maximumDistance'],
            'fontSizeUnit': ['fontLetterSpacing', 'fontWordSpacing'],
        }
        for unit_name, dimensions in pairs.items():
            if element.get(unit_name) in PHYSICAL_UNITS:
                for key in dimensions:
                    if key in element.attrib:
                        element.set(key, multiply(element.get(key), factor))


def transform_template(root, factor, origin, minimum_font_pt):
    rows = []
    for item in root.iter('LayoutItem'):
        if item.get('type') == '65638':
            item.set('size', '210,297,mm')
            continue
        for name in ('position', 'positionOnPage'):
            if item.get(name):
                item.set(name, scale_measure(item.get(name), factor, origin))
        for name in ('size', 'outlineWidthM', 'labelMargin', 'cornerRadiusMeasure'):
            if item.get(name):
                item.set(name, scale_measure(item.get(name), factor))
        for name in ('marginX', 'marginY', 'svgBorderWidth', 'pictureWidth',
                     'pictureHeight', 'boxContentSpace', 'labelBarSpace',
                     'outlineWidth', 'height', 'subdivisionsHeight',
                     'minBarWidth', 'maxBarWidth', 'segmentMillimeters'):
            if item.get(name):
                item.set(name, multiply(item.get(name), factor))
        for node in item.findall('./nodes/node'):
            for axis in ('x', 'y'):
                node.set(axis, multiply(node.get(axis), factor))
        for grid in item.findall('./ComposerMapGrid'):
            for key in ('gridFrameWidth', 'gridFramePenThickness', 'gridFrameMargin',
                        'frameAnnotationDistance', 'crossLength'):
                if grid.get(key):
                    grid.set(key, multiply(grid.get(key), factor))
        # Map labels live inside each map's locked styles. Set their physical
        # point sizes separately from the free layout labels and decorations.
        map_text_roles = {}
        for style in item.findall('./LayerStyles/LayerStyle'):
            name = style.get('name', '')
            if name.startswith('Kunming District Boundaries'):
                role = 'district_legend_elevation_ticks'
            elif name.startswith('Dianchi Lake'):
                role = 'lake'
            elif name.startswith('Faults'):
                role = 'fault_earthquake_gnss'
            else:
                continue
            for text in style.iter('text-style'):
                map_text_roles[text] = role
        item_id = item.get('id', '')
        for text in item.iter('text-style'):
            unit = text.get('fontSizeUnit')
            if unit != 'Point':
                raise ValueError('Review non-point text format: ' + str(unit))
            old = float(text.get('fontSize'))
            if text in map_text_roles:
                role = map_text_roles[text]
            elif item_id.startswith(('Legend_label_', 'Elevation_break_')):
                role = 'district_legend_elevation_ticks'
            elif item_id in {'GNSS_station_label', 'event_2026_label', 'event_2023_label'}:
                role = 'fault_earthquake_gnss'
            elif item_id in {'Left_map_Kunming', 'Elevation_legend_title'}:
                role = 'kunming_elevation_titles'
            elif item.get('type') in {'65639', '65646'} or item_id.endswith('_N'):
                role = 'coordinates_north_scale'
            else:
                raise ValueError('Assign an explicit typography role for ' + item_id)
            target = max(minimum_font_pt, FONT_SIZES_PT[role])
            text.set('fontSize', format(target, '.15g'))
            text.set('fontFamily', 'Arial')
            rows.append({'item': item.get('id', ''),
                         'text': item.get('labelText', ''),
                         'source_pt': old, 'a4_pt': target, 'role': role,
                         'family': 'Arial', 'weight': text.get('fontWeight'),
                         'italic': text.get('fontItalic')})
    scale_physical_styles(root, factor)
    root.set('name', LAYOUT_NAME)
    root.set('printResolution', '600')
    return rows


def map_snapshot(layout):
    return {item.id(): {
        'extent': [item.extent().xMinimum(), item.extent().yMinimum(),
                   item.extent().xMaximum(), item.extent().yMaximum()],
        'layers': [layer.id() for layer in item.layers()],
        'rotation': item.mapRotation(),
    } for item in layout.items() if isinstance(item, QgsLayoutItemMap)}


def collect_assets(root, context, output):
    """Copy SVGs used by the working layout; keep source resources read-only."""
    assets = output / 'assets'
    records = []
    for element in root.iter():
        for key, value in list(element.attrib.items()):
            if not value.lower().endswith('.svg'):
                continue
            source = Path(context.pathResolver().readPath(value)).resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            assets.mkdir(exist_ok=True)
            target = assets / (digest(source)[:10] + '_' + source.name)
            if not target.exists():
                shutil.copy2(source, target)
            element.set(key, str(target))
            records.append({'source': str(source), 'copy': str(target),
                            'sha256': digest(source)})
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=LAYOUT_WORK)
    parser.add_argument('--figure-width-mm', type=float, default=PAPER_FIGURE_WIDTH_MM)
    parser.add_argument('--minimum-font-pt', type=float, default=MINIMUM_FONT_PT)
    parser.add_argument('--top-mm', type=float, default=25.0)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not any(output.is_relative_to(root.resolve()) for root in (LAYOUT_WORK, WORKSPACE / 'drafts')):
        parser.error('Output must be inside plot/01_study_area/layout/work or workspace/drafts; formal publishing is disabled.')
    if not 0 < args.figure_width_mm <= A4_MM[0] or args.minimum_font_pt <= 0:
        parser.error('Figure width and font size must be positive and fit A4.')
    output.mkdir(parents=True, exist_ok=True)
    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], False)
        app.initQgis()
    protected = [SOURCE, WORKSPACE / 'plot/01_study_area/output/final/figure01.png',
                 WORKSPACE / 'manuscript/figures/jpg/Figure1.jpg',
                 WORKSPACE / 'manuscript/pdf/manuscript.pdf',
                 WORKSPACE / 'plot/figure_index.json']
    hashes = {str(path): digest(path) for path in protected}
    project = QgsProject()
    if not project.read(str(SOURCE)):
        raise RuntimeError('Cannot open the saved figure 1 project.')
    if not all(layer.isValid() for layer in project.mapLayers().values()):
        raise RuntimeError('Source project contains an invalid layer.')
    original = project.layoutManager().layoutByName(SOURCE_LAYOUT)
    if original is None:
        raise RuntimeError('Source layout is missing.')
    page = original.pageCollection().page(0).pageSize()
    source_width, source_height = page.width(), page.height()
    factor = args.figure_width_mm / source_width
    origin = ((A4_MM[0] - args.figure_width_mm) / 2, args.top_mm)
    figure_height = source_height * factor
    if origin[1] < 0 or origin[1] + figure_height > A4_MM[1]:
        parser.error('Figure placement does not fit inside the A4 page.')
    before_maps = map_snapshot(original)
    before_text = sorted(item.text() for item in original.items()
                         if isinstance(item, QgsLayoutItemLabel))
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(SOURCE)))
    source_document = QDomDocument('qgis')
    source_document.appendChild(original.writeXml(source_document, context))
    root = ET.fromstring(source_document.toString())
    asset_records = collect_assets(root, context, output)
    fonts = transform_template(root, factor, origin, args.minimum_font_pt)
    document = QDomDocument()
    result = document.setContent(ET.tostring(root, encoding='unicode'))
    if isinstance(result, tuple) and not result[0]:
        raise RuntimeError('Transformed layout XML could not be parsed.')
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    _, ok = layout.loadFromTemplate(document, context, True)
    if not ok:
        raise RuntimeError('Could not load the transformed editable layout.')
    layout.setName(LAYOUT_NAME)
    layout.renderContext().setDpi(600)
    # 6.5 pt makes this legend entry wrap in its old invisible text frame.
    # Widen the frame only; preserve its left/vertical-centre text anchor.
    gnss_legend = layout.itemById('Legend_label_gnss')
    old_box = [gnss_legend.pos().x(), gnss_legend.pos().y(),
               gnss_legend.sizeWithUnits().width(), gnss_legend.sizeWithUnits().height()]
    gnss_legend.adjustSizeToText()
    fitted_width = max(old_box[2], gnss_legend.sizeWithUnits().width())
    gnss_legend.attemptResize(QgsLayoutSize(fitted_width, old_box[3]))
    gnss_legend.attemptMove(QgsLayoutPoint(old_box[0], old_box[1]))
    text_frame_adjustments = [{
        'item': 'Legend_label_gnss', 'reason': 'Keep GNSS station on one line at 6.5 pt',
        'before_box_mm': old_box,
        'after_box_mm': [gnss_legend.pos().x(), gnss_legend.pos().y(),
                         gnss_legend.sizeWithUnits().width(), gnss_legend.sizeWithUnits().height()],
        'text_anchor_unchanged': True,
    }]
    project.layoutManager().removeLayout(original)
    project.layoutManager().addLayout(layout)
    after_maps = map_snapshot(layout)
    assert before_maps.keys() == after_maps.keys()
    for key in before_maps:
        old, new = before_maps[key], after_maps[key]
        assert old['layers'] == new['layers'] and old['rotation'] == new['rotation']
        assert max(abs(a - b) for a, b in zip(old['extent'], new['extent'])) < 0.05, key
    assert before_text == sorted(item.text() for item in layout.items()
                                 if isinstance(item, QgsLayoutItemLabel))
    project_path = output / '01_study_area_A4.qgz'
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    assert project.write()
    template_path = output / (LAYOUT_NAME + '.qpt')
    template_context = QgsReadWriteContext()
    template_context.setPathResolver(QgsPathResolver(str(template_path)))
    assert layout.saveAsTemplate(str(template_path), template_context)
    exporter = QgsLayoutExporter(layout)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = 600
    settings.forceVectorOutput = True
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    pdf_path = output / 'figure01_A4.pdf'
    assert exporter.exportToPdf(str(pdf_path), settings) == QgsLayoutExporter.Success
    figure_rect = QRectF(*origin, args.figure_width_mm, figure_height)
    for filename, dpi in [('figure01_paper_size.png', 600), ('figure01_preview.png', 180)]:
        image = exporter.renderRegionToImage(figure_rect, QSize(), dpi)
        assert not image.isNull() and image.save(str(output / filename), 'PNG')
    assert hashes == {path: digest(path) for path in hashes}, 'A formal input changed.'
    report = {'page_mm': list(A4_MM), 'figure_width_mm': args.figure_width_mm,
              'figure_height_mm': figure_height, 'figure_origin_mm': list(origin),
              'original_page_mm': [source_width, source_height], 'scale': factor,
              'legacy_layout_pt_for_paper_6pt': 6 / factor,
              'minimum_paper_font_pt': args.minimum_font_pt,
              'font_policy': 'Arial; explicit physical point sizes by element role',
              'font_sizes_pt': FONT_SIZES_PT,
              'text_frame_adjustments': text_frame_adjustments,
              'fonts': fonts, 'maps_before': before_maps, 'maps_after': after_maps,
              'text_content_unchanged': True, 'map_extent_and_layer_order_unchanged': True,
              'formal_files_unchanged': True, 'protected_sha256': hashes,
              'assets': asset_records, 'project': str(project_path),
              'template': str(template_path), 'pdf': str(pdf_path)}
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {'fonts', 'maps_before', 'maps_after', 'assets', 'protected_sha256'}},
                     ensure_ascii=False, indent=2), flush=True)
    return project, layout


if __name__ == '__main__':
    main()
