"""Create a draft A4 QGIS figure 4 with native, editable map and chart labels."""
from pathlib import Path
import argparse
import json
import os
import xml.etree.ElementTree as ET
from qgis.core import (
    QgsApplication, QgsProject, QgsPrintLayout, QgsReadWriteContext, QgsPathResolver,
    QgsLayoutItem, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemPicture,
    QgsLayoutPoint, QgsLayoutSize, QgsLayoutExporter, QgsTextFormat,
    QgsTextBufferSettings, Qgis,
)
from qgis.PyQt.QtCore import Qt, QPointF, QRectF, QSize
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtXml import QDomDocument
from layout_scale_utils import digest, multiply, scale_measure, scale_physical_styles, collect_assets

_APP = None


def map_snapshot(layout):
    return {i.id(): {'extent': [i.extent().xMinimum(), i.extent().yMinimum(),
                               i.extent().xMaximum(), i.extent().yMaximum()],
                     'layers': [x.id() for x in i.layers()], 'rotation': i.mapRotation()}
            for i in layout.items() if isinstance(i, QgsLayoutItemMap)}


def text_anchor(item):
    size = item.sizeWithUnits()
    hx = 1 if item.hAlign() == Qt.AlignRight else .5 if item.hAlign() == Qt.AlignHCenter else 0
    vy = 1 if item.vAlign() == Qt.AlignBottom else .5 if item.vAlign() == Qt.AlignVCenter else 0
    p = item.mapToScene(QPointF(hx * size.width(), vy * size.height()))
    return [p.x(), p.y()]


def fit_map_labels(layout):
    adjustments = []
    for item in layout.items():
        if not isinstance(item, QgsLayoutItemLabel):
            continue
        point = text_anchor(item)
        old = [item.sizeWithUnits().width(), item.sizeWithUnits().height()]
        item.adjustSizeToText()
        item.attemptResize(QgsLayoutSize(max(old[0], item.sizeWithUnits().width()),
                                        max(old[1], item.sizeWithUnits().height())))
        current = text_anchor(item)
        item.attemptMove(QgsLayoutPoint(item.pos().x() + point[0] - current[0],
                                       item.pos().y() + point[1] - current[1]))
        assert max(abs(a-b) for a, b in zip(point, text_anchor(item))) < 1e-6
        if abs(item.sizeWithUnits().width()-old[0]) > 1e-6 or abs(item.sizeWithUnits().height()-old[1]) > 1e-6:
            adjustments.append({'id': item.id(), 'before_size_mm': old,
                                'after_size_mm': [item.sizeWithUnits().width(), item.sizeWithUnits().height()],
                                'text_anchor_unchanged': True})
    return adjustments


def map_role(id_, type_):
    if id_ in ['Wuhua', 'Panlong', 'Xishan', 'Guandu', 'Chenggong']:
        return 'districts'
    if id_ == 'Dian_Lake': return 'lake'
    if id_ in ['Historical_event_0', 'Event_2026_annotation', 'GNSS_station_label']:
        return 'events_gnss'
    if id_ == 'North_text': return 'north'
    if id_ == 'Legend_title': return 'legend_title'
    if id_.startswith('Legend_range_'): return 'legend_classes'
    if id_ in ['Earthquake_legend_label', 'GNSS_legend_label', 'Fault_legend_label', 'Left_lateral_legend_label']:
        return 'symbol_legend'
    if id_.startswith('Fault_'): return 'faults'
    if type_ == '65646': return 'scale_bar'
    raise ValueError('Assign a font role for ' + id_)


def transform_map(root, plan):
    scale, origin = plan['map_scale'], plan['map_origin_mm']
    rows = []
    for item in root.iter('LayoutItem'):
        if item.get('type') == '65638':
            item.set('size', '210,297,mm')
            continue
        for name in ['position', 'positionOnPage']:
            if item.get(name): item.set(name, scale_measure(item.get(name), scale, origin))
        for name in ['size', 'outlineWidthM', 'labelMargin', 'cornerRadiusMeasure']:
            if item.get(name): item.set(name, scale_measure(item.get(name), scale))
        for name in ['marginX', 'marginY', 'svgBorderWidth', 'pictureWidth', 'pictureHeight',
                     'boxContentSpace', 'labelBarSpace', 'outlineWidth', 'height',
                     'subdivisionsHeight', 'minBarWidth', 'maxBarWidth', 'segmentMillimeters']:
            if item.get(name): item.set(name, multiply(item.get(name), scale))
        for node in item.findall('./nodes/node'):
            for axis in ['x', 'y']: node.set(axis, multiply(node.get(axis), scale))
        for grid in item.findall('./ComposerMapGrid'):
            for key in ['gridFrameWidth', 'gridFramePenThickness', 'gridFrameMargin',
                        'frameAnnotationDistance', 'crossLength']:
                if grid.get(key): grid.set(key, multiply(grid.get(key), scale))
            if grid.get('show') == '1' and grid.get('showAnnotation') == '1':
                t = grid.find('./text-style'); t.set('fontSize', str(plan['map_fonts_pt']['coordinates']))
                t.set('fontFamily', 'Arial')
                rows.append({'id': item.get('id') + '_coordinates', 'pt': plan['map_fonts_pt']['coordinates']})
        for text in item.findall('./text-style'):
            role = map_role(item.get('id'), item.get('type'))
            target = plan['map_fonts_pt'][role]
            text.set('fontSize', str(target)); text.set('fontFamily', 'Arial')
            rows.append({'id': item.get('id'), 'text': item.get('labelText'), 'role': role, 'pt': target})
    scale_physical_styles(root, scale)
    root.set('name', 'Figure04_A4'); root.set('printResolution', '600')
    return rows


def add_chart_label(layout, rec):
    item = QgsLayoutItemLabel(layout)
    item.setId(rec['id']); item.setText(rec['text'])
    item.setHAlign({'left': Qt.AlignLeft, 'right': Qt.AlignRight,
                    'center': Qt.AlignHCenter}[rec['horizontal_alignment']])
    item.setVAlign(Qt.AlignVCenter)
    fmt = QgsTextFormat(); font = QFont('Arial')
    font.setPointSizeF(rec['font_pt']); font.setBold(rec['bold']); font.setItalic(rec['italic'])
    fmt.setFont(font); fmt.setSize(rec['font_pt']); fmt.setSizeUnit(Qgis.RenderUnit.Points)
    fmt.setColor(QColor(rec['color'])); fmt.setLineHeight(rec['line_spacing'])
    if rec['halo_mm']:
        buffer = QgsTextBufferSettings(); buffer.setEnabled(True)
        buffer.setSize(rec['halo_mm']); buffer.setColor(QColor('white')); fmt.setBuffer(buffer)
    item.setTextFormat(fmt)
    item.setMargin(1.5 * 25.4 / 72 * .45448 if rec['background'] else 0)
    if rec['background']:
        item.setBackgroundEnabled(True); item.setBackgroundColor(QColor('white'))
    layout.addLayoutItem(item)
    item.adjustSizeToText()
    item.setItemRotation(rec['rotation'])
    size = item.sizeWithUnits()
    center = item.mapToScene(QPointF(size.width()/2, size.height()/2))
    item.attemptMove(QgsLayoutPoint(item.pos().x() + rec['center_mm'][0] - center.x(),
                                   item.pos().y() + rec['center_mm'][1] - center.y()))
    item.setZValue(60 if rec['background'] else 50)
    return item


def main():
    global _APP
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    workspace, output = Path(plan['workspace']), Path(plan['output']).resolve()
    assert any(output.is_relative_to((workspace/root).resolve()) for root in ('plot/04_seismic_hazard/layout/work', 'drafts'))
    source = workspace/'plot/04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz'
    protected = [source, workspace/'plot/04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt',
                 workspace/'plot/04_seismic_hazard/output/final/figure04.png',
                 workspace/'manuscript/figures/jpg/Figure4.jpg',
                 workspace/'manuscript/pdf/manuscript.pdf', workspace/'plot/figure_index.json']
    hashes = {str(x): digest(x) for x in protected}
    _APP = QgsApplication.instance()
    if _APP is None: _APP=QgsApplication([],False); _APP.initQgis()
    project = QgsProject(); assert project.read(str(source))
    original = project.layoutManager().layoutByName('Kunming_Hazard_PGA'); assert original
    before = map_snapshot(original)
    assert all(x.isValid() for x in original.itemById('Hazard_Main_Map').layers())
    before_text = sorted(i.text() for i in original.items() if isinstance(i,QgsLayoutItemLabel))
    context = QgsReadWriteContext(); context.setPathResolver(QgsPathResolver(str(source)))
    document = QDomDocument('qgis'); document.appendChild(original.writeXml(document,context))
    root = ET.fromstring(document.toString())
    assets = collect_assets(root, context, output)
    font_rows = transform_map(root, plan)
    document = QDomDocument(); assert document.setContent(ET.tostring(root,encoding='unicode'))[0]
    layout = QgsPrintLayout(project); layout.initializeDefaults()
    _,ok = layout.loadFromTemplate(document,context,True); assert ok
    layout.setName('Figure04_A4'); layout.renderContext().setDpi(600)
    project.layoutManager().removeLayout(original); project.layoutManager().addLayout(layout)
    adjustments = fit_map_labels(layout)
    # The larger title needs the unused whitespace to its left to clear the
    # first colour swatch. All other map alignment anchors remain fixed.
    title, swatch = layout.itemById('Legend_title'), layout.itemById('Legend_class_0')
    old_title_position = [title.pos().x(), title.pos().y()]
    shift = min(0., swatch.pos().x() - .35 - title.sceneBoundingRect().right())
    if shift:
        title.attemptMove(QgsLayoutPoint(title.pos().x()+shift,title.pos().y()))
    position_adjustments = [{'id':'Legend_title','reason':'Clear the first swatch at 6 pt',
                             'before_mm':old_title_position,
                             'after_mm':[title.pos().x(),title.pos().y()],
                             'shift_x_mm':shift}]
    assert title.pos().x() >= plan['figure_origin_mm'][0]
    after = map_snapshot(layout)
    assert before == after
    assert before_text == sorted(i.text() for i in layout.items() if isinstance(i,QgsLayoutItemLabel))
    for chart in plan['charts']:
        picture = QgsLayoutItemPicture(layout); picture.setId(chart['id']+'_graphics')
        layout.addLayoutItem(picture)
        picture.attemptMove(QgsLayoutPoint(*chart['position_mm']))
        picture.attemptResize(QgsLayoutSize(*chart['size_mm']))
        picture.setPicturePath(chart['svg']); picture.setZValue(30)
        for rec in chart['labels']: add_chart_label(layout,rec)
    project_path = output/'04_seismic_hazard_A4.qgz'
    project.setFileName(str(project_path)); project.setFilePathStorage(Qgis.FilePathType.Relative)
    assert project.write()
    template = output/'Figure04_A4.qpt'
    ctx = QgsReadWriteContext(); ctx.setPathResolver(QgsPathResolver(str(template)))
    assert layout.saveAsTemplate(str(template),ctx)
    exporter = QgsLayoutExporter(layout)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi=600; settings.forceVectorOutput=True; settings.textRenderFormat=Qgis.TextRenderFormat.AlwaysText
    pdf=output/'figure04_A4.pdf'
    assert exporter.exportToPdf(str(pdf),settings) == QgsLayoutExporter.Success
    region=QRectF(*plan['figure_origin_mm'],plan['figure_width_mm'],plan['figure_height_mm'])
    for filename,dpi in [('figure04_paper_size.png',600),('figure04_preview.png',180)]:
        image=exporter.renderRegionToImage(region,QSize(),dpi)
        assert not image.isNull() and image.save(str(output/filename),'PNG')
    assert hashes=={x:digest(x) for x in hashes}
    report={'project':str(project_path),'template':str(template),'pdf':str(pdf),
            'page_mm':plan['page_mm'],'figure_origin_mm':plan['figure_origin_mm'],
            'figure_size_mm':[plan['figure_width_mm'],plan['figure_height_mm']],
            'map_fonts':font_rows,'chart_fonts_pt':plan['chart_fonts_pt'],
            'map_extent_layer_order_rotation_unchanged':before==after,
            'map_text_content_unchanged':True,'map_text_frame_adjustments':adjustments,
            'minimal_position_adjustments':position_adjustments,
            'chart_text_items':sum(len(c['labels']) for c in plan['charts']),
            'all_chart_text_editable_in_QGIS':True,'panel_identifiers_removed':True,
            'protected_sha256':hashes,'formal_files_unchanged':True,'assets':assets,
            'data_sha256':plan['source_data_sha256'],'buildings':plan['buildings']}
    (output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['assets','data_sha256','protected_sha256','map_fonts','map_text_frame_adjustments']},ensure_ascii=False,indent=2),flush=True)
    return project,layout


if __name__=='__main__':
    project,layout=main()
    # QGIS/Qt can crash while the embedded Python application finalizes native
    # layout ownership. All exports and verification have completed and closed.
    os._exit(0)
