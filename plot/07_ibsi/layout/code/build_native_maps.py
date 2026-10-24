"""Editable native QGIS A4 drafts; all writes remain inside this session."""
from pathlib import Path
from zipfile import ZipFile
import json
import os
import xml.etree.ElementTree as ET

from qgis.core import (Qgis, QgsApplication, QgsProject, QgsTextFormat,
    QgsMapLayerStyle, QgsSimpleFillSymbolLayer, QgsReadWriteContext,
    QgsPathResolver, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel,
    QgsLayoutItemPicture, QgsLayoutPoint, QgsLayoutSize, QgsLayoutExporter)
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument
from layout_scale_utils import digest, multiply, scale_measure, scale_physical_styles, collect_assets

D = Path(__file__).resolve().parents[1]
PLAN = json.loads((D/'session.json').read_text())
R = Path(PLAN['root'])
DISTRICTS = {'Wuhua','Panlong','Xishan','Guandu','Chenggong'}
EVENTS = {'Historical_event_0','Event_2026_annotation','GNSS_station_label'}
_APP = None


def state(layout):
    return {i.id(): {'extent': [i.extent().xMinimum(),i.extent().yMinimum(),
                               i.extent().xMaximum(),i.extent().yMaximum()],
                     'rotation':i.mapRotation(),'layers':[l.id() for l in i.layers()]}
            for i in layout.items() if isinstance(i,QgsLayoutItemMap)}


def anchor(item):
    size=item.sizeWithUnits()
    hx=1 if item.hAlign()==Qt.AlignRight else .5 if item.hAlign()==Qt.AlignHCenter else 0
    vy=1 if item.vAlign()==Qt.AlignBottom else .5 if item.vAlign()==Qt.AlignVCenter else 0
    p=item.mapToScene(QPointF(hx*size.width(),vy*size.height()))
    return [p.x(),p.y()]


def role(ident):
    if ident in DISTRICTS:return 'districts'
    if ident=='Dian_Lake':return 'lake'
    if ident in EVENTS:return 'events_gnss'
    if ident=='Legend_title':return 'legend_title'
    if ident.startswith('Legend_range_'):return 'class_labels'
    if 'legend_label' in ident:return 'context_legend'
    if ident.startswith('Fault_'):return 'faults'
    if ident=='North_text':return 'north'
    if ident=='Overview_scale':return 'scale_bar'
    raise ValueError('Unassigned visible text: '+ident)


def palette(layout,project,spec):
    main=layout.referenceMap()
    layer=next(l for l in main.layers() if l.customProperty('seismic_building/result_key','')==spec['key'])
    assert layer.isValid() and layer.featureCount()==spec['n'] and not layer.subsetString()
    overrides=main.layerStyleOverrides()
    if layer.id() in overrides:QgsMapLayerStyle(overrides[layer.id()]).writeToLayer(layer)
    rules=layer.renderer().rootRule().children()
    filters=[r.filterExpression() for r in rules]
    for k,(rule,color) in enumerate(zip(rules,spec['colors'])):
        symbol=rule.symbol().clone();symbol.setColor(QColor(color))
        for fill in symbol.symbolLayers():
            if isinstance(fill,QgsSimpleFillSymbolLayer):fill.setStrokeColor(QColor(color))
        rule.setSymbol(symbol)
        swatch=layout.itemById(f'Legend_class_{k}')
        symbol=swatch.symbol().clone();symbol.setColor(QColor(color))
        for fill in symbol.symbolLayers():
            if isinstance(fill,QgsSimpleFillSymbolLayer):fill.setStrokeColor(QColor(color))
        swatch.setSymbol(symbol)
    style=QgsMapLayerStyle();style.readFromLayer(layer)
    overrides[layer.id()]=style.xmlData();main.setLayerStyleOverrides(overrides)
    return {'n':layer.featureCount(),'filters':filters,'colors':[r.symbol().color().name() for r in rules]}


def convert(project,old,spec):
    number=spec['figure'];key=spec['key'];factor=spec['factor'];origin=spec['origin']
    KF=json.loads((D/'paper_scale.json').read_text())[str(number)]  # print at A4 sizes in the paper
    before=state(old)
    assert all(l.isValid() for i in old.items() if isinstance(i,QgsLayoutItemMap) for l in i.layers())
    source=R/spec['source'];ctx=QgsReadWriteContext();ctx.setPathResolver(QgsPathResolver(str(source)))
    doc=QDomDocument('qgis');doc.appendChild(old.writeXml(doc,ctx));root=ET.fromstring(doc.toString())
    # Reading the saved project has already restored the stale cached position.
    # Recover the actual Figure 7 scene positions from the original XML before
    # QGIS normalizes that discrepancy on loading.
    rendered_positions={}
    if number==7:
        with ZipFile(source) as archive:
            qgs=ET.fromstring(archive.read(next(n for n in archive.namelist() if n.endswith('.qgs'))))
        original_layout=next(l for l in qgs.findall('.//Layout') if l.get('name')==spec['layout'])
        rendered_positions={i.get('id'):i.get('positionOnPage') for i in original_layout.findall('LayoutItem')
                            if i.get('id') and i.get('positionOnPage')}
    assets=collect_assets(root,ctx,D)
    original_text={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
    rows=[]
    for item in root.iter('LayoutItem'):
        ident=item.get('id','')
        if item.get('type')=='65638':item.set('size','210,297,mm');continue
        # Several Figure 7 labels were moved with QGraphicsItem.setPos(). QGIS
        # cached `position` was not updated, whereas `positionOnPage` records
        # their rendered scene position. Use the rendered coordinate for both
        # fields so loading the template cannot revert those original moves.
        actual_position=rendered_positions.get(ident) or item.get('positionOnPage') or item.get('position')
        if actual_position:
            position=scale_measure(actual_position,factor,origin)
            for name in ['position','positionOnPage']:item.set(name,position)
        for name in ['size','outlineWidthM','labelMargin','cornerRadiusMeasure']:
            if item.get(name):item.set(name,scale_measure(item.get(name),factor))
        for name in ['marginX','marginY','svgBorderWidth','pictureWidth','pictureHeight',
                     'boxContentSpace','labelBarSpace','outlineWidth','height','subdivisionsHeight',
                     'minBarWidth','maxBarWidth','segmentMillimeters']:
            if item.get(name):item.set(name,multiply(item.get(name),factor))
        for node in item.findall('./nodes/node'):
            for name in ['x','y']:node.set(name,multiply(node.get(name),factor))
        if item.get('labelText','').strip() in ['(a)','(b)','(c)','(d)']:
            item.set('visibility','0');item.set('excludeFromExports','1')
        for grid in item.findall('./ComposerMapGrid'):
            for name in ['gridFrameWidth','gridFramePenThickness','gridFrameMargin','frameAnnotationDistance','crossLength']:
                if grid.get(name):grid.set(name,multiply(grid.get(name),factor))
            style=grid.find('text-style')
            if style is not None:
                target=PLAN['font_targets'][str(number)]['coordinates']*KF
                style.set('fontFamily','Arial');style.set('fontSize',str(target))
                rows.append({'id':ident+'_coordinates','role':'coordinates','target_pt':target})
        style=item.find('text-style')
        if style is not None:
            initial=float(style.get('fontSize'))*factor
            visible=item.get('visibility')!='0' and item.get('excludeFromExports')!='1'
            category=role(ident) if visible else 'hidden'
            target=PLAN['font_targets'][str(number)].get(category,initial)*KF
            style.set('fontFamily','Arial');style.set('fontSize',str(target))
            if visible:rows.append({'id':ident,'role':category,'text':item.get('labelText') or 'Scale bar',
                                    'target_pt':target,'old_a4_pt':initial,
                                    'italic':style.get('fontItalic')=='1'})
    scale_physical_styles(root,factor)
    root.set('name',f'Figure{number:02}_{key}_A4');root.set('printResolution','1440')
    assert original_text=={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
    doc=QDomDocument();assert doc.setContent(ET.tostring(root,encoding='unicode'))[0]
    layout=QgsPrintLayout(project);layout.initializeDefaults()
    _,ok=layout.loadFromTemplate(doc,ctx,True);assert ok
    layout.renderContext().setDpi(1440)
    project.layoutManager().addLayout(layout)
    frames=[];anchors=[]
    for item in layout.items():
        if not isinstance(item,QgsLayoutItemLabel) or not item.isVisible() or item.excludeFromExports():continue
        old_anchor=anchor(item);size=item.sizeWithUnits();old_size=[size.width(),size.height()]
        item.adjustSizeToText()
        item.attemptResize(QgsLayoutSize(max(old_size[0],item.sizeWithUnits().width()),max(old_size[1],item.sizeWithUnits().height())))
        now=anchor(item);item.attemptMove(QgsLayoutPoint(item.pos().x()+old_anchor[0]-now[0],item.pos().y()+old_anchor[1]-now[1]))
        assert max(abs(a-b) for a,b in zip(old_anchor,anchor(item)))<1e-6
        anchors.append({'id':item.id(),'original_anchor_mm':old_anchor,'anchor_mm':anchor(item)})
        size=item.sizeWithUnits();new_size=[size.width(),size.height()]
        if new_size!=old_size:frames.append({'id':item.id(),'old_mm':old_size,'new_mm':new_size})
    # The larger title can touch the first class swatch. Keep the swatches and
    # five grade anchors fixed, shifting only the title by the necessary amount.
    shifts=[]
    if number==8:
        title=layout.itemById('Legend_title');swatch=layout.itemById('Legend_class_0')
        right=title.pos().x()+title.sizeWithUnits().width()
        dx=min(0.,swatch.pos().x()-.45-right)
        if dx<0:
            title.attemptMove(QgsLayoutPoint(title.pos().x()+dx,title.pos().y()))
            shifts.append({'id':'Legend_title','dx_mm':dx,'dy_mm':0,
                           'reason':'Maintain 0.45 mm gap from first swatch at 7 pt; other legend anchors unchanged'})
        label=layout.itemById('GNSS_station_label')
        label.attemptMove(QgsLayoutPoint(label.pos().x(),label.pos().y()+1.5))
        shifts.append({'id':'GNSS_station_label','dx_mm':0,'dy_mm':1.5,
                       'reason':'Separate enlarged GNSS text from Guandu; station symbol and district anchor unchanged'})
    if number==7:
        # Paper-size fonts: separate the enlarged 2023 event label from the Puduhe fault name.
        for ident,dx,dy,why in [('Fault_Puduhe',.3,-2.5,'Move fault name up along the fault, clear of the 2023 event label'),
                                ('Historical_event_0',-.6,0,'Small left shift to clear the Puduhe fault name')]:
            it=layout.itemById(ident);it.attemptMove(QgsLayoutPoint(it.pos().x()+dx,it.pos().y()+dy))
            shifts.append({'id':ident,'dx_mm':dx,'dy_mm':dy,'reason':why})
    after=state(layout);assert before==after,'Map extent/rotation/layers changed'
    for lay in list(project.layoutManager().layouts()):
        if lay!=layout:project.layoutManager().removeLayout(lay)
    layout.refresh()
    path=D/'work'/f'{number:02}_{key}_map_A4.pdf'
    settings=QgsLayoutExporter.PdfExportSettings();settings.dpi=1440
    settings.forceVectorOutput=True;settings.rasterizeWholeImage=False;settings.simplifyGeometries=False
    settings.textRenderFormat=Qgis.TextRenderFormat.AlwaysText;settings.appendGeoreference=False
    print('Exporting '+str(path),flush=True)
    assert QgsLayoutExporter(layout).exportToPdf(str(path),settings)==QgsLayoutExporter.Success
    if number==7:
        picture=QgsLayoutItemPicture(layout);picture.setId('Python_histograms_and_IBSI_legend')
        layout.addLayoutItem(picture);picture.attemptMove(QgsLayoutPoint(15,25))
        picture.attemptResize(QgsLayoutSize(180,106.5));picture.setResizeMode(QgsLayoutItemPicture.Stretch)
        picture.setPicturePath(str(D/'work/figure07_charts.svg'));picture.setZValue(100)
    project_path=D/f'{number:02}_{key}_A4.qgz'
    project.setFileName(str(project_path));project.setFilePathStorage(Qgis.FilePathType.Relative);assert project.write()
    template=D/f'Figure{number:02}_{key}_A4.qpt'
    save_ctx=QgsReadWriteContext();save_ctx.setPathResolver(QgsPathResolver(str(template)))
    assert layout.saveAsTemplate(str(template),save_ctx)
    return {'figure':number,'key':key,'source':str(source),'native_pdf':str(path),
            'project':str(project_path),'template':str(template),'map_state_before':before,
            'map_state_after':after,'map_geometry_unchanged':True,'text_content_unchanged':True,
            'fonts':rows,'frame_expansions':frames,'original_anchors':anchors,
            'position_adjustments':shifts,'assets':assets,
            'source_rendered_positions_restored':number==7}


def main():
    global _APP
    assert D.is_relative_to(R/'plot')
    _APP=QgsApplication([],False);_APP.initQgis()
    specs=[{'figure':7,'key':'ibsi','source':'plot/07_ibsi/qgis/projects/07_ibsi.qgz',
            'layout':'Kunming_IBSI_review','factor':93/195,'origin':[58.5,25+106.5-8-93*200/195]},
           {'figure':8,'key':'vulnerability','source':'plot/08_vulnerability_exposure/qgis/projects/08a_vulnerability.qgz',
            'layout':'Kunming_Vulnerability','factor':180/395,'origin':[15,25],
            'n':41939,'colors':['#F6F2F8','#EBDEF0','#DCC3E8','#BE7BDE','#4F0671']},
           {'figure':8,'key':'exposure','source':'plot/diagnostics/exposure_maps/output/20261016_191617_68d9a7/building_exposure_BuGn.qgz',
            'layout':'Kunming_Exposure','factor':180/395,'origin':[15+200*180/395,25],
            'n':53513,'colors':['#F0F5F3','#D4E7E0','#A5D6C5','#31A97E','#033825']}]
    refs={};reports=[];keep=[]
    for spec in specs:
        source=R/spec['source'];before_hash=digest(source)
        project=QgsProject();assert project.read(str(source));keep.append(project)
        layout=project.layoutManager().layoutByName(spec['layout']);assert layout
        color_report=None
        if spec['figure']==8:
            color_report=palette(layout,project,spec)
            if not refs:
                refs={'labels':{i.id():{'format':QgsTextFormat(i.textFormat()),'pos':i.pos(),
                          'size':i.sizeWithUnits()} for i in layout.items() if isinstance(i,QgsLayoutItemLabel)},
                      'grid':QgsTextFormat(layout.referenceMap().grid().annotationTextFormat()),
                      'scale':QgsTextFormat(layout.itemById('Overview_scale').textFormat())}
            else:
                for item in layout.items():
                    if isinstance(item,QgsLayoutItemLabel) and item.id() in refs['labels']:
                        ref=refs['labels'][item.id()];item.setTextFormat(QgsTextFormat(ref['format']))
                        item.attemptResize(ref['size']);item.attemptMove(QgsLayoutPoint(ref['pos'].x(),ref['pos'].y()))
                layout.referenceMap().grid().setAnnotationTextFormat(QgsTextFormat(refs['grid']))
                layout.itemById('Overview_scale').setTextFormat(QgsTextFormat(refs['scale']))
        report=convert(project,layout,spec)
        report['classification']=color_report
        assert digest(source)==before_hash
        report['source_unchanged']=True;reports.append(report)
    (D/'native_map_reports.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'maps':len(reports),'position_adjustments':[{r['key']:r['position_adjustments']} for r in reports]},ensure_ascii=False),flush=True)
    return keep


if __name__=='__main__':
    keep=main()
    os._exit(0)
