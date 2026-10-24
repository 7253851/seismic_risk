"""Native A4 QGIS map, preserving map extent and typography anchors."""
from pathlib import Path
import json
import os
import xml.etree.ElementTree as ET
from qgis.core import (Qgis,QgsApplication,QgsProject,QgsPrintLayout,QgsReadWriteContext,
                       QgsPathResolver,QgsLayoutItemMap,QgsLayoutItemLabel,QgsLayoutItemPicture,
                       QgsLayoutPoint,QgsLayoutSize,QgsLayoutExporter)
from qgis.PyQt.QtCore import Qt,QPointF
from qgis.PyQt.QtXml import QDomDocument
from layout_scale_utils import digest,multiply,scale_measure,scale_physical_styles,collect_assets
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'shared/layout_tools'))
import panel_labels

OUTPUT=Path(__file__).resolve().parents[1]
PLAN=json.loads((OUTPUT/'a4_plan.json').read_text())
ROOT=Path(PLAN['root'])
_APP=None
OMIT={'Historical_earthquakes_legend_symbol','Historical_earthquakes_legend_label',
      'GNSS_legend_symbol','GNSS_legend_label','Fault_legend_symbol','Fault_legend_label',
      'Left_lateral_legend_symbol','Left_lateral_legend_label','Deformation_Scale',
      'Velocity_Colourbar','Velocity_Legend_Title',*[f'Velocity_Tick_{i}' for i in range(9)]}


def state(layout):
    return {x.id():{'extent':[x.extent().xMinimum(),x.extent().yMinimum(),x.extent().xMaximum(),x.extent().yMaximum()],
                    'rotation':x.mapRotation(),'layers':[l.id() for l in x.layers()]}
            for x in layout.items() if isinstance(x,QgsLayoutItemMap)}


def anchor(item):
    sz=item.sizeWithUnits()
    hx=1 if item.hAlign()==Qt.AlignRight else .5 if item.hAlign()==Qt.AlignHCenter else 0
    vy=1 if item.vAlign()==Qt.AlignBottom else .5 if item.vAlign()==Qt.AlignVCenter else 0
    p=item.mapToScene(QPointF(hx*sz.width(),vy*sz.height()))
    return [p.x(),p.y()]


def main():
    global _APP
    assert OUTPUT.is_relative_to(ROOT/'plot')
    source=ROOT/'plot/06_insar_deformation/qgis/projects/06_insar_deformation.qgz'
    original_hash=digest(source)
    _APP=QgsApplication([],False);_APP.initQgis()
    project=QgsProject();assert project.read(str(source))
    original=project.layoutManager().layoutByName('Kunming_TSX_Vertical_Deformation');assert original
    before=state(original)
    assert all(l.isValid() for x in original.items() if isinstance(x,QgsLayoutItemMap) for l in x.layers())
    ctx=QgsReadWriteContext();ctx.setPathResolver(QgsPathResolver(str(source)))
    doc=QDomDocument('qgis');doc.appendChild(original.writeXml(doc,ctx))
    root=ET.fromstring(doc.toString())
    assets=collect_assets(root,ctx,OUTPUT)
    factor=PLAN['map_scale'];origin=PLAN['map_origin_mm'];fonts=PLAN['fonts_pt']
    original_labels={x.get('id'):x.get('labelText') for x in root.findall('LayoutItem') if x.find('text-style') is not None}
    rows=[]
    for item in root.iter('LayoutItem'):
        id_=item.get('id')
        if item.get('type')=='65638':item.set('size','210,297,mm');continue
        for key in ['position','positionOnPage']:
            if item.get(key):item.set(key,scale_measure(item.get(key),factor,origin))
        for key in ['size','outlineWidthM','labelMargin','cornerRadiusMeasure']:
            if item.get(key):item.set(key,scale_measure(item.get(key),factor))
        for key in ['marginX','marginY','svgBorderWidth','pictureWidth','pictureHeight',
                    'boxContentSpace','labelBarSpace','outlineWidth','height',
                    'subdivisionsHeight','minBarWidth','maxBarWidth','segmentMillimeters']:
            if item.get(key):item.set(key,multiply(item.get(key),factor))
        for node in item.findall('./nodes/node'):
            for key in ['x','y']:node.set(key,multiply(node.get(key),factor))
        if id_ in OMIT:
            item.set('visibility','0');item.set('excludeFromExports','1')
        for grid in item.findall('./ComposerMapGrid'):
            for key in ['gridFrameWidth','gridFramePenThickness','gridFrameMargin','frameAnnotationDistance','crossLength']:
                if grid.get(key):grid.set(key,multiply(grid.get(key),factor))
            style=grid.find('text-style')
            if style is not None:
                style.set('fontFamily','Arial');style.set('fontSize',str(fonts['coordinates']))
                rows.append({'id':id_+'_coordinates','role':'coordinates','target_pt':fonts['coordinates']})
        style=item.find('text-style')
        if style is not None and id_ not in OMIT:
            if id_ in ['Wuhua','Panlong','Xishan','Guandu','Chenggong']:role='districts'
            elif id_=='Dian_Lake':role='lake'
            elif id_ in ['event_2026_label','event_2023_label','GNSS_station_label']:role='events_gnss'
            elif id_=='North_text':role='north'
            elif id_.startswith('Fault_'):role='faults'
            else:raise ValueError('Unassigned visible map text: '+str(id_))
            style.set('fontFamily','Arial');style.set('fontSize',str(fonts[role]))
            rows.append({'id':id_,'text':item.get('labelText'),'role':role,'target_pt':fonts[role]})
    scale_physical_styles(root,factor)
    # 1440 dpi provides 20 pixels per PDF point, so 6.5 and 7 pt are
    # represented without the 1200 dpi fractional-pixel font rounding.
    root.set('name','Figure06_A4');root.set('printResolution','1440')
    assert original_labels=={x.get('id'):x.get('labelText') for x in root.findall('LayoutItem') if x.find('text-style') is not None}
    doc=QDomDocument();assert doc.setContent(ET.tostring(root,encoding='unicode'))[0]
    layout=QgsPrintLayout(project);layout.initializeDefaults()
    _,ok=layout.loadFromTemplate(doc,ctx,True);assert ok
    layout.setName('Figure06_A4');layout.renderContext().setDpi(1440)
    project.layoutManager().removeLayout(original);project.layoutManager().addLayout(layout)
    adjustments=[];anchors=[]
    for item in layout.items():
        if not isinstance(item,QgsLayoutItemLabel) or item.id() in OMIT:continue
        old_anchor=anchor(item);old_size=[item.sizeWithUnits().width(),item.sizeWithUnits().height()]
        item.adjustSizeToText()
        item.attemptResize(QgsLayoutSize(max(old_size[0],item.sizeWithUnits().width()),max(old_size[1],item.sizeWithUnits().height())))
        now=anchor(item);item.attemptMove(QgsLayoutPoint(item.pos().x()+old_anchor[0]-now[0],item.pos().y()+old_anchor[1]-now[1]))
        assert max(abs(x-y) for x,y in zip(old_anchor,anchor(item)))<1e-6
        anchors.append({'id':item.id(),'anchor_mm':anchor(item)})
        new_size=[item.sizeWithUnits().width(),item.sizeWithUnits().height()]
        if max(abs(x-y) for x,y in zip(new_size,old_size))>1e-6:
            adjustments.append({'id':item.id(),'before_mm':old_size,'after_mm':new_size,'anchor_unchanged':True})
    labels=panel_labels.add(layout,panel_labels.load(OUTPUT),font_pt=fonts.get('panel_labels',10.))
    for item in layout.items():
        if hasattr(item,'id') and callable(item.id) and item.id().startswith('Panel_label_'):item.setVisibility(False)
    after=state(layout)
    assert before==after, 'Map extent/rotation/layer order changed'
    layout.refresh()
    settings=QgsLayoutExporter.PdfExportSettings();settings.dpi=1440
    settings.forceVectorOutput=True;settings.rasterizeWholeImage=False;settings.simplifyGeometries=False
    settings.textRenderFormat=Qgis.TextRenderFormat.AlwaysText;settings.appendGeoreference=False
    exporter=QgsLayoutExporter(layout)
    assert exporter.exportToPdf(str(OUTPUT/'map_A4.pdf'),settings)==QgsLayoutExporter.Success
    if labels:panel_labels.export_top_layer(layout,OUTPUT/'panel_labels_A4.pdf')
    for item in layout.items():
        if hasattr(item,'id') and callable(item.id) and item.id().startswith('Panel_label_'):item.setVisibility(True)
    # Include the chart SVG in the saved editable layout for visual context.
    # Chart typography is controlled in the companion Python source. The final
    # PDF uses its embedded-font PDF overlay, preserving searchable text.
    picture=QgsLayoutItemPicture(layout);picture.setId('Python_chart_overlay')
    layout.addLayoutItem(picture)
    picture.attemptMove(QgsLayoutPoint(*PLAN['figure_origin_mm']))
    picture.attemptResize(QgsLayoutSize(*PLAN['figure_size_mm']))
    picture.setResizeMode(QgsLayoutItemPicture.Stretch)
    picture.setPicturePath(PLAN['overlay_svg']);picture.setZValue(100)
    target=OUTPUT/'06_insar_deformation_A4.qgz'
    project.setFileName(str(target));project.setFilePathStorage(Qgis.FilePathType.Relative);assert project.write()
    template=OUTPUT/'Figure06_A4.qpt'
    save_ctx=QgsReadWriteContext();save_ctx.setPathResolver(QgsPathResolver(str(template)))
    assert layout.saveAsTemplate(str(template),save_ctx)
    assert original_hash==digest(source)
    record={'project':str(target),'template':str(template),'layout_name':'Figure06_A4',
            'map_fonts':rows,'map_state_before':before,'map_state_after':after,
            'map_extent_rotation_layer_order_unchanged':True,'map_text_unchanged':True,
            'physical_graphic_scale':factor,'anchors':anchors,
            'text_frame_adjustments':adjustments,'position_adjustments':[],
            'assets':assets,'source_project_unchanged':True,'panel_labels':labels}
    (OUTPUT/'map_report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'project':str(target),'map_export':str(OUTPUT/'map_A4.pdf'),'visible_map_fonts':len(rows),'frames_resized':len(adjustments)},indent=2),flush=True)
    return project,layout


if __name__=='__main__':
    project,layout=main()
    os._exit(0)
