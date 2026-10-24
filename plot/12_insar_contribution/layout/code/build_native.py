"""Edit fonts in an isolated QGIS project, preserving map and layout geometry."""
from pathlib import Path
from zipfile import ZipFile
import json,os,xml.etree.ElementTree as ET
from qgis.core import (Qgis,QgsApplication,QgsProject,QgsPrintLayout,QgsReadWriteContext,
    QgsPathResolver,QgsLayoutExporter,QgsLayoutItemMap,QgsLayoutItemLabel,QgsLayoutPoint,QgsLayoutSize)
from qgis.PyQt.QtCore import Qt,QPointF
from qgis.PyQt.QtXml import QDomDocument
from layout_scale_utils import digest,collect_assets
D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text());R=Path(S['root'])
F=S['font_targets_a4_pt'];FY=S['font_scale_y'];APP=None
KP=json.loads((D/'paper_scale.json').read_text())['K']  # unspecified sizes also print at A4 size

def role(k):
    if k in ['Wuhua','Panlong','Xishan','Guandu','Chenggong']:return 'districts'
    if k=='Dian_Lake':return 'lake'
    if k.startswith('Fault_') and not k.endswith('_legend_label'):return 'faults'
    if k in ['GNSS_station_label','Historical_event_0','Event_2026_annotation']:return 'events_gnss'
    if k=='North_text':return 'main_north'
    if k.endswith('_legend_label') or k.startswith('Latest_legend_label_'):return 'map_symbols'
    if k=='Latest_pair_title':return 'inset_title'
    if k=='Latest_pair_N':return 'inset_north'
    if k.startswith('Latest_case_info_'):return 'inset_ids' if k.endswith('_0') else 'inset_metrics'
    if k=='Latest_heatmap_title':return 'heat_title'
    if k=='Latest_heatmap_sample':return 'heat_sample'
    if k.startswith('Latest_heatmap_value_'):return 'heat_values'
    if k.startswith(('Latest_heatmap_row_','Latest_heatmap_col_')):return 'heat_classes'
    if k in ['Latest_heatmap_x_axis','Latest_heatmap_y_axis']:return 'heat_axes'
    if k in ['Latest_heatmap_overall','Latest_heatmap_down']:return 'heat_summary'
    raise ValueError(k)

def state(layout):
    return {i.id():{'extent':[i.extent().xMinimum(),i.extent().yMinimum(),i.extent().xMaximum(),i.extent().yMaximum()],
        'rotation':i.mapRotation(),'position':[i.pos().x(),i.pos().y()],
        'size':[i.sizeWithUnits().width(),i.sizeWithUnits().height()],
        'layers':[l.id() for l in i.layers()],
        'styles':{k:ET.canonicalize(v,strip_text=True) for k,v in i.layerStyleOverrides().items()}}
        for i in layout.items() if isinstance(i,QgsLayoutItemMap)}

def anchor(item):
    z=item.sizeWithUnits();x=1 if item.hAlign()==Qt.AlignRight else .5 if item.hAlign()==Qt.AlignHCenter else 0
    y=1 if item.vAlign()==Qt.AlignBottom else .5 if item.vAlign()==Qt.AlignVCenter else 0
    p=item.mapToScene(QPointF(x*z.width(),y*z.height()));return [p.x(),p.y()]

def main():
    global APP
    APP=QgsApplication([],False);APP.initQgis()
    source=Path(S['source_project']);before_hash=digest(source)
    project=QgsProject();assert project.read(str(source))
    original=project.layoutManager().layoutByName('01_Static_only_baseline_reference_composite');assert original
    assert all(l.isValid() for i in original.items() if isinstance(i,QgsLayoutItemMap) for l in i.layers())
    before=state(original)
    ctx=QgsReadWriteContext();ctx.setPathResolver(QgsPathResolver(str(source)))
    doc=QDomDocument();doc.appendChild(original.writeXml(doc,ctx));root=ET.fromstring(doc.toString())
    with ZipFile(source) as z:qgs=ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.qgs'))))
    raw=next(x for x in qgs.findall('.//Layout') if x.get('name')==original.name())
    positions={i.get('id'):i.get('positionOnPage') for i in raw.findall('LayoutItem') if i.get('id')}
    assets=collect_assets(root,ctx,D)
    rows=[];text_before={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
    for it in root.findall('LayoutItem'):
        k=it.get('id','');style=it.find('./text-style')
        if positions.get(k):
            for attr in ['position','positionOnPage']:it.set(attr,positions[k])
        if it.get('labelText'):
            category=role(k);native=float(style.get('fontSize'));target=F.get(category,native*FY*KP)
            style.set('fontFamily','Arial');style.set('fontSize',format(target/FY,'.15g'))
            rows.append({'id':k,'role':category,'text':it.get('labelText'),'target_pt':target,
                'native_pt':target/FY,'specified':category in F,'italic':style.get('fontItalic')=='1'})
        if k in ['Overview_scale','Latest_pair_scale']:
            pt=float(style.get('fontSize'));rows.append({'id':k,'role':'main_scale' if k=='Overview_scale' else 'inset_scale',
                'text':'0 / 2 km' if k=='Overview_scale' else '0 / 25 / 50 m','target_pt':pt*FY,'native_pt':pt,'specified':False})
        for grid in it.findall('./ComposerMapGrid'):
            f=grid.find('./text-style');f.set('fontFamily','Arial');f.set('fontSize',str(F['coordinates']/FY))
            rows.append({'id':k+'_coordinates','role':'coordinates','text':'Longitude / latitude',
                'target_pt':F['coordinates'],'native_pt':F['coordinates']/FY,'specified':True})
        if k=='Latest_case_strip':it.set('file',str(D/'work/latest_case_strip.svg'))
        if k=='Latest_inset_PS_colorbar':
            path=Path(it.get('file'));svg=ET.parse(path);ns='http://www.w3.org/2000/svg';ET.register_namespace('',ns)
            style=next(e for e in svg.iter() if e.get('font-family')=='Arial')
            style.set('font-size',str(F['inset_colorbar']/FY*25.4/72))
            # QGIS Zoom rounded this picture to 44 x 11 mm inside its original
            # 44 x 11.2 mm frame. Correct glyph height around each unchanged
            # text baseline, leaving the gradient and all anchors untouched.
            ratio=float(it.get('pictureHeight'))/11.2
            for e in svg.iter():
                if e.tag.rsplit('}',1)[-1]=='text':
                    y=float(e.get('y'))
                    e.set('transform',f'translate(0 {y}) scale(1 {1/ratio}) translate(0 {-y})')
            path=D/'assets/inset_PS_rate_key_fonts.svg';svg.write(path,encoding='utf-8',xml_declaration=True)
            it.set('file',str(path));rows.append({'id':k,'role':'inset_colorbar','text':'Vertical rate (mm/yr) / −9 / −4 / 1',
                'target_pt':F['inset_colorbar'],'native_pt':F['inset_colorbar']/FY,'specified':True})
    assert text_before=={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
    root.set('name','Figure12_Fonts_For_A4');root.set('printResolution',str(round(S['native_export_dpi'])))
    doc=QDomDocument();assert doc.setContent(ET.tostring(root,encoding='unicode'))[0]
    layout=QgsPrintLayout(project);layout.initializeDefaults();_,ok=layout.loadFromTemplate(doc,ctx,True);assert ok
    layout.renderContext().setDpi(S['native_export_dpi']);project.layoutManager().addLayout(layout)
    anchors=[];frames=[]
    for i in layout.items():
        if not isinstance(i,QgsLayoutItemLabel):continue
        old=anchor(i);z=i.sizeWithUnits();size=[z.width(),z.height()]
        i.adjustSizeToText();n=i.sizeWithUnits();i.attemptResize(QgsLayoutSize(max(size[0],n.width()),max(size[1],n.height())))
        now=anchor(i);i.attemptMove(QgsLayoutPoint(i.pos().x()+old[0]-now[0],i.pos().y()+old[1]-now[1]))
        assert max(abs(a-b) for a,b in zip(old,anchor(i)))<1e-6
        anchors.append({'id':i.id(),'before_mm':old,'after_mm':anchor(i)})
        frames.append({'id':i.id(),'old_mm':size,'new_mm':[i.sizeWithUnits().width(),i.sizeWithUnits().height()]})
    after=state(layout);assert before==after,'Map geometry/layers/styles changed'
    strip=layout.itemById('Latest_case_strip');sz=strip.sizeWithUnits();p=strip.pos()
    strip_box=[p.x(),p.y(),sz.width(),sz.height()]
    for other in list(project.layoutManager().layouts()):
        if other!=layout:project.layoutManager().removeLayout(other)
    colorbar=layout.itemById('Latest_inset_PS_colorbar');cs=colorbar.sizeWithUnits();cp=colorbar.pos()
    colorbar_box=[cp.x(),cp.y(),cs.width(),cs.height()]
    colorbar_xml=next(it for it in root.findall('LayoutItem') if it.get('id')=='Latest_inset_PS_colorbar')
    picture_size=[float(colorbar_xml.get('pictureWidth')),float(colorbar_xml.get('pictureHeight'))]
    # Compose this small SVG as a separate embedded-font PDF, retaining the
    # same gradient and anchors; Qt outlines SVG text in its map PDF exporter.
    strip.setExcludeFromExports(True);colorbar.setExcludeFromExports(True)
    settings=QgsLayoutExporter.PdfExportSettings();settings.dpi=S['native_export_dpi']
    settings.forceVectorOutput=True;settings.rasterizeWholeImage=False;settings.simplifyGeometries=False
    settings.textRenderFormat=Qgis.TextRenderFormat.AlwaysText;settings.appendGeoreference=False
    pdf=D/'work/map_native_fonts.pdf';layout.refresh();print('Exporting '+str(pdf),flush=True)
    assert QgsLayoutExporter(layout).exportToPdf(str(pdf),settings)==QgsLayoutExporter.Success
    strip.setExcludeFromExports(False);colorbar.setExcludeFromExports(False)
    target=D/'12_insar_contribution_fonts.qgz';project.setFileName(str(target));project.setFilePathStorage(Qgis.FilePathType.Relative);assert project.write()
    qpt=D/'Figure12_Fonts_For_A4.qpt';save=QgsReadWriteContext();save.setPathResolver(QgsPathResolver(str(qpt)));assert layout.saveAsTemplate(str(qpt),save)
    assert digest(source)==before_hash
    (D/'map_report.json').write_text(json.dumps({'pdf':str(pdf),'project':str(target),'qpt':str(qpt),
        'fonts':rows,'anchors':anchors,'frames':frames,'strip_box_mm':strip_box,'map_state_before':before,
        'map_state_after':after,'map_geometry_layer_styles_preserved':True,'text_content_preserved':True,
        'position_adjustments':[],'assets':assets,'native_dpi':settings.dpi,
        'colorbar_box_mm':colorbar_box,'colorbar_picture_mm':picture_size,
        'colorbar_svg':str(D/'assets/inset_PS_rate_key_fonts.svg')},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'pdf':str(pdf),'font_items':len(rows),'original_anchors_preserved':True},ensure_ascii=False),flush=True)
    return project,layout

if __name__=='__main__':
    keep=main();os._exit(0)
