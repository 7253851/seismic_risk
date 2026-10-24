"""Edit typography only in an independent native QGIS layout, then export.

Keeping the native page geometry preserves all physical map symbol widths.
The companion compositor maps this native layout onto the agreed A4 figure.
"""
from pathlib import Path
import json, os
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from qgis.core import (Qgis, QgsApplication, QgsProject, QgsPrintLayout,
    QgsReadWriteContext, QgsPathResolver, QgsLayoutExporter, QgsLayoutItemMap,
    QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize)
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtXml import QDomDocument
from layout_scale_utils import digest, collect_assets

D=Path(__file__).resolve().parents[1]
S=json.loads((D/'session.json').read_text());R=Path(S['root'])
FACTOR=S['map_scale_in_native']*S['figure_width_mm']/248
TARGETS=S['font_targets_a4_pt']
KP=json.loads((D/'paper_scale.json').read_text())['K']  # unspecified sizes also print at A4 size
APP=None

def role(key):
    if key in ['Wuhua','Panlong','Xishan','Guandu','Chenggong']:return 'districts'
    if key=='Dian_Lake':return 'lake'
    if key.startswith('Fault_'):return 'faults'
    if key in ['Historical_event_0','Event_2026_annotation','GNSS_station_label']:return 'events_gnss'
    if key=='North_text':return 'north'
    if key.startswith('Transect_') and '_station_' in key:
        return 'endpoints' if key[-1] in 'ABCD' else 'chainage'
    raise ValueError(key)

def anchor(item):
    z=item.sizeWithUnits()
    x=1 if item.hAlign()==Qt.AlignRight else .5 if item.hAlign()==Qt.AlignHCenter else 0
    y=1 if item.vAlign()==Qt.AlignBottom else .5 if item.vAlign()==Qt.AlignVCenter else 0
    p=item.mapToScene(QPointF(x*z.width(),y*z.height()))
    return [p.x(),p.y()]

def state(layout):
    return {i.id():{'extent':[i.extent().xMinimum(),i.extent().yMinimum(),i.extent().xMaximum(),i.extent().yMaximum()],
        'rotation':i.mapRotation(),'position':[i.pos().x(),i.pos().y()],
        'size':[i.sizeWithUnits().width(),i.sizeWithUnits().height()],
        'layers':[l.id() for l in i.layers()],
        'overrides':{k:ET.canonicalize(v,strip_text=True) for k,v in i.layerStyleOverrides().items()}}
        for i in layout.items() if isinstance(i,QgsLayoutItemMap)}

def main():
    global APP
    assert D.is_relative_to(R/'plot')
    source=R/'plot/10_risk_transects/qgis/projects/10_risk_transects.qgz';original_hash=digest(source)
    APP=QgsApplication([],False);APP.initQgis()
    project=QgsProject();assert project.read(str(source))
    original=project.layoutManager().layoutByName('Kunming_Risk_Transects_AB_CD');assert original
    assert all(l.isValid() for i in original.items() if isinstance(i,QgsLayoutItemMap) for l in i.layers())
    before=state(original)
    ctx=QgsReadWriteContext();ctx.setPathResolver(QgsPathResolver(str(source)))
    doc=QDomDocument();doc.appendChild(original.writeXml(doc,ctx));root=ET.fromstring(doc.toString())
    # Recover scene positions from the saved XML, avoiding stale position caches.
    with ZipFile(source) as z:
        qgs=ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.qgs'))))
    original_xml=next(x for x in qgs.findall('.//Layout') if x.get('name')==original.name())
    positions={i.get('id'):i.get('positionOnPage') for i in original_xml.findall('LayoutItem') if i.get('id')}
    assets=collect_assets(root,ctx,D)
    rows=[];labels={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
    for item in root.findall('LayoutItem'):
        key=item.get('id','')
        if positions.get(key):
            for p in ['position','positionOnPage']:item.set(p,positions[key])
        style=item.find('./text-style')
        top=float(item.get('positionOnPage','0,0,mm').split(',')[1])
        if top>=201:
            # Outside the same 201 mm map crop used by the adopted composition.
            item.set('visibility','0');item.set('excludeFromExports','1')
        if item.get('labelText') and top<201 and item.get('visibility')!='0':
            category=role(key);old=float(style.get('fontSize'))
            target=TARGETS.get(category,old*FACTOR*KP);native=target/FACTOR
            style.set('fontFamily','Arial');style.set('fontSize',format(native,'.15g'))
            rows.append({'id':key,'role':category,'text':item.get('labelText'),
                'target_a4_pt':target,'native_pt':native,'old_native_pt':old,
                'italic':style.get('fontItalic')=='1','specified':category in TARGETS})
        for grid in item.findall('./ComposerMapGrid'):
            f=grid.find('./text-style');f.set('fontFamily','Arial')
            f.set('fontSize',format(TARGETS['coordinates']/FACTOR,'.15g'))
            rows.append({'id':key+'_coordinates','role':'coordinates','text':'Longitude and latitude',
                'target_a4_pt':TARGETS['coordinates'],'native_pt':TARGETS['coordinates']/FACTOR,'specified':True})
        if key=='Overview_scale':
            old=float(style.get('fontSize'));style.set('fontSize',format(old*KP,'.15g'))
            rows.append({'id':key,'role':'scale_bar','text':'0, 2 km','target_a4_pt':old*FACTOR*KP,
                'native_pt':old*KP,'old_native_pt':old,'italic':False,'specified':False})
    assert labels=={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
    root.set('name','Figure10_Map_Fonts_For_A4');root.set('printResolution',str(int(round(S['map_dpi']))))
    doc=QDomDocument();assert doc.setContent(ET.tostring(root,encoding='unicode'))[0]
    layout=QgsPrintLayout(project);layout.initializeDefaults();_,ok=layout.loadFromTemplate(doc,ctx,True);assert ok
    layout.renderContext().setDpi(S['map_dpi'])
    project.layoutManager().addLayout(layout)
    anchors=[];frames=[]
    for item in layout.items():
        if not isinstance(item,QgsLayoutItemLabel) or item.id() not in {r['id'] for r in rows}:continue
        p=anchor(item);size=item.sizeWithUnits();old=[size.width(),size.height()]
        item.adjustSizeToText();new=item.sizeWithUnits()
        item.attemptResize(QgsLayoutSize(max(old[0],new.width()),max(old[1],new.height())))
        now=anchor(item)
        item.attemptMove(QgsLayoutPoint(item.pos().x()+p[0]-now[0],item.pos().y()+p[1]-now[1]))
        assert max(abs(a-b) for a,b in zip(p,anchor(item)))<1e-6
        anchors.append({'id':item.id(),'native_anchor_mm':p,'new_anchor_mm':anchor(item)})
        frames.append({'id':item.id(),'old_mm':old,'new_mm':[item.sizeWithUnits().width(),item.sizeWithUnits().height()]})
    after=state(layout)
    (D/'work/map_state_check.json').write_text(json.dumps({'before':before,'after':after},ensure_ascii=False,indent=2)+'\n')
    assert before==after,'Map geometry or layer styles changed'
    for other in list(project.layoutManager().layouts()):
        if other!=layout:project.layoutManager().removeLayout(other)
    pdf=D/'work/map_native_fonts.pdf'
    settings=QgsLayoutExporter.PdfExportSettings();settings.dpi=S['map_dpi']
    settings.forceVectorOutput=True;settings.rasterizeWholeImage=False;settings.simplifyGeometries=False
    settings.textRenderFormat=Qgis.TextRenderFormat.AlwaysText;settings.appendGeoreference=False
    layout.refresh();print('Exporting map '+str(pdf),flush=True)
    assert QgsLayoutExporter(layout).exportToPdf(str(pdf),settings)==QgsLayoutExporter.Success
    target=D/'10_risk_transects_fonts.qgz';project.setFileName(str(target))
    project.setFilePathStorage(Qgis.FilePathType.Relative);assert project.write()
    template=D/'Figure10_Map_Fonts_For_A4.qpt';outctx=QgsReadWriteContext();outctx.setPathResolver(QgsPathResolver(str(template)))
    assert layout.saveAsTemplate(str(template),outctx)
    assert digest(source)==original_hash
    report={'pdf':str(pdf),'project':str(target),'qpt':str(template),'layout':layout.name(),
        'native_page_mm':[195,232],'map_factor_to_a4':FACTOR,'export_dpi':settings.dpi,
        'map_geometry_layer_styles_unchanged':True,'text_content_unchanged':True,
        'fonts':rows,'anchors':anchors,'text_frames':frames,'position_adjustments':[],
        'assets':assets,'map_state_before':before,'map_state_after':after,'source_sha256':original_hash}
    (D/'map_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'fonts':len(rows),'source_unchanged':True,'pdf':str(pdf)},ensure_ascii=False),flush=True)
    return project,layout

if __name__=='__main__':
    keep=main();os._exit(0)
