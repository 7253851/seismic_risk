"""Apply the Figure 13 layout changes to the editable working copy.

Starts from the approved font draft (placements already recovered), sets the
five-level class captions to the 4 pt A4 target, enlarges the observed-PS
markers to 1.1 mm native without outline, and checks the D1/D2 group gap
(4.0 mm native).  Map extents, panel sizes, photo/satellite content, data and
all other text anchors are preserved.  Every export stays inside this draft.
"""
from pathlib import Path
from zipfile import ZipFile
import json,os,sys,xml.etree.ElementTree as ET
from qgis.core import (Qgis,QgsApplication,QgsProject,QgsPrintLayout,QgsReadWriteContext,
 QgsPathResolver,QgsLayoutExporter,QgsLayoutItemMap,QgsLayoutItemLabel,QgsLayoutPoint,QgsLayoutSize,
 QgsSimpleMarkerSymbolLayer,QgsSimpleMarkerSymbolLayerBase,QgsRenderContext)
from qgis.PyQt.QtCore import Qt,QPointF
from qgis.PyQt.QtXml import QDomDocument
from layout_scale_utils import digest,collect_assets
D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text());R=Path(S['root'])
F=S['font_targets_a4_pt'];FY=S['font_scale_y'];APP=None
KP=json.loads((D/'paper_scale.json').read_text())['K']  # unspecified sizes also print at A4 size
PS_LAYERS=['D1 - observed PS for building 34360','D2 - observed PS for building 35945',
           'Observed PS - buildings 34360 and 35945']
PS_DIAM=S['PS_marker_diameter_native_mm'];GAP=S['right_group_gap_native_mm']

def role(k):
 if k.startswith('District_label_'):return 'districts'
 if k.startswith('Campus_label_'):return 'campus'
 if k=='Event_date_label':return 'event'
 if k.startswith('Legend_text_'):return 'symbols'
 if k.startswith('Locator_letter_'):return 'locator'
 if k=='North_N':return 'main_north'
 if k.startswith('Inset_location_'):return 'inset_title'
 if k.startswith('Inset_building_ID_'):return 'inset_building'
 if k.endswith('_header'):return 'group_header'
 if '_title_' in k:return 'panel_title'
 if k.endswith('_case'):return 'case'
 if k.endswith('_grade'):return 'grade'
 if '_class_' in k:return 'classes'
 if k.endswith('_hazard_units'):return 'pga_units'
 if k.endswith('_PS_N'):return 'PS_north'
 if k.endswith('_N'):return 'thematic_north'
 if k.endswith('_PS_count') or k.endswith('_PS_legend_units'):return 'PS_count_units'
 if '_PS_legend_tick_' in k:return 'PS_ticks'
 raise ValueError(k)
def position(it):return [float(v) for v in it.get('positionOnPage',it.get('position')).split(',')[:2]]
def anchor(it):
 z=it.sizeWithUnits();x=1 if it.hAlign()==Qt.AlignRight else .5 if it.hAlign()==Qt.AlignHCenter else 0
 y=1 if it.vAlign()==Qt.AlignBottom else .5 if it.vAlign()==Qt.AlignVCenter else 0
 p=it.mapToScene(QPointF(x*z.width(),y*z.height()));return [p.x(),p.y()]
def mapstate(layout):
 return {i.id():{'extent':i.extent().toString(10),'rotation':i.mapRotation(),
  'position':[i.pos().x(),i.pos().y()],'size':[i.sizeWithUnits().width(),i.sizeWithUnits().height()],
  'layers':[l.id() for l in i.layers()],
  'styles':i.layerStyleOverrides()} for i in layout.items() if isinstance(i,QgsLayoutItemMap)}
def normalize_style(s):
 t=ET.fromstring(s)
 for f in t.findall('.//labeling/settings/text-style'):
  if f.get('fieldName')=='FN_En':f.set('fontSize','FONT_TARGET')
 return ET.canonicalize(ET.tostring(t,encoding='unicode'),strip_text=True)

def fix_ps_style(style_element):
 """Enlarge the graduated observed-PS circle markers and drop their outline."""
 changed=0
 for symbol in style_element.iter('symbol'):
  if symbol.get('type')!='marker':continue
  layer=symbol.find('layer')
  if layer is None or layer.get('class')!='SimpleMarker':continue
  options={o.get('name'):o for o in layer.iter('Option') if o.get('name')}
  if 'size' not in options:continue
  if float(options['size'].get('value'))<=0.7:
   options['size'].set('value',format(PS_DIAM,'.15g'))
   if 'outline_style' in options:options['outline_style'].set('value','no')
   if 'outline_width' in options:options['outline_width'].set('value','0')
   changed+=1
 return changed

def main():
 global APP
 APP=QgsApplication([],False);APP.initQgis()
 source=Path(S['source_project']);protected=digest(source)
 project=QgsProject();assert project.read(str(source))
 original=project.layoutManager().layoutByName(S['source_layout']);assert original
 assert all(l.isValid() for i in original.items() if isinstance(i,QgsLayoutItemMap) for l in i.layers())
 ctx=QgsReadWriteContext();ctx.setPathResolver(QgsPathResolver(str(source)))
 doc=QDomDocument();doc.appendChild(original.writeXml(doc,ctx));root=ET.fromstring(doc.toString())
 with ZipFile(source) as z:qgs=ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.qgs'))))
 original_state=mapstate(original);assets=collect_assets(root,ctx,D)
 rows=[];text_before={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
 ps_style_changes=[]
 for it in root.findall('LayoutItem'):
  k=it.get('id','');style=it.find('./text-style')
  if it.get('labelText'):
   cat=role(k);native=float(style.get('fontSize'));target=F.get(cat,native*FY*KP)
   style.set('fontSize',format(target/FY,'.15g'))
   if cat in F:
    style.set('fontFamily','Arial')
   rows.append({'id':k,'role':cat,'text':it.get('labelText'),'target_pt':target,
    'native_pt':target/FY,'specified':cat in F,
    'italic':style.get('fontItalic')=='1'})
  for grid in it.findall('./ComposerMapGrid'):
   f=grid.find('./text-style')
   f.set('fontSize',str(F['coordinates']/FY));f.set('fontFamily','Arial')
   rows.append({'id':k+'_coordinates','role':'coordinates','text':'Longitude / latitude','target_pt':F['coordinates'],
    'native_pt':float(f.get('fontSize')),'specified':True})
  if it.get('type')=='65646':
   cat='main_scale' if k=='Scale_0_1_km' else 'inset_scale' if k.startswith('Inset_scale_') else 'PS_scale' if '_PS_' in k else 'thematic_scale'
   style.set('fontSize',format(float(style.get('fontSize'))*KP,'.15g'))
   rows.append({'id':k,'role':cat,'text':'scale bar','target_pt':float(style.get('fontSize'))*FY,
    'native_pt':float(style.get('fontSize')),'specified':False})
  if k=='Event_Distribution_Main_Map':
   for f in it.findall('./LayerStyles/LayerStyle/qgis/labeling/settings/text-style'):
    if f.get('fieldName')=='FN_En':f.set('fontSize',str(F['faults']/FY));f.set('fontFamily','Arial')
  for ls in it.findall('./LayerStyles/LayerStyle'):
   if 'observed PS' in (ls.get('name') or ''):
    n=fix_ps_style(ls)
    if n:ps_style_changes.append({'map_item':k,'layer':ls.get('name'),'symbols':n})
 assert text_before=={i.get('id'):i.get('labelText') for i in root.findall('LayoutItem') if i.get('labelText')}
 root.set('name',S['native_layout'])
 root.set('printResolution',str(round(S['native_export_dpi'])))
 doc=QDomDocument();assert doc.setContent(ET.tostring(root,encoding='unicode'))[0]
 layout=QgsPrintLayout(project);layout.initializeDefaults();_,ok=layout.loadFromTemplate(doc,ctx,True);assert ok
 project.layoutManager().addLayout(layout);layout.refresh()
 assert layout.name()==S['native_layout']
 anchors=[];frames=[]
 for i in layout.items():
  if not isinstance(i,QgsLayoutItemLabel):continue
  k=i.id();old=anchor(i);z=i.sizeWithUnits();size=[z.width(),z.height()]
  i.adjustSizeToText();n=i.sizeWithUnits()
  i.attemptResize(QgsLayoutSize(max(size[0],n.width()),max(size[1],n.height())))
  now=anchor(i);i.attemptMove(QgsLayoutPoint(i.pos().x()+old[0]-now[0],i.pos().y()+old[1]-now[1]))
  after=anchor(i);assert max(abs(a-b) for a,b in zip(old,after))<1e-6
  anchors.append({'id':k,'before_mm':old,'after_mm':after,'adjusted':False})
  frames.append({'id':k,'old_mm':size,'new_mm':[i.sizeWithUnits().width(),i.sizeWithUnits().height()],
   'native_font_stretch':i.textFormat().font().stretch()})
 project_ps=[]
 for lname in PS_LAYERS:
  for l in project.mapLayers().values():
   if l.name()!=lname:continue
   r=l.renderer();rc=QgsRenderContext();n=0
   for sym in r.symbols(rc):
    for i in range(sym.symbolLayerCount()):
     sl=sym.symbolLayer(i)
     if isinstance(sl,QgsSimpleMarkerSymbolLayer) and sl.shape()==QgsSimpleMarkerSymbolLayerBase.Circle and abs(sl.size()-0.65)<1e-6:
      sl.setSize(PS_DIAM);sl.setStrokeStyle(Qt.NoPen);sl.setStrokeWidth(0);n+=1
   l.triggerRepaint();project_ps.append({'layer':lname,'symbols':n})
 faults=next(l for l in project.mapLayers().values() if l.name()=='Local fault traces')
 settings=faults.labeling().settings();fmt=settings.format();fmt.setSize(F['faults']/FY);settings.setFormat(fmt)
 faults.labeling().setSettings(settings)
 rows.append({'id':'fault_layer_label','role':'faults','text':'Heilongtan–Guandu fault','target_pt':F['faults'],
  'native_pt':F['faults']/FY,'specified':True})
 after_state=mapstate(layout)
 for k,b in original_state.items():
  a=after_state[k];assert a['extent']==b['extent'] and a['rotation']==b['rotation'] and a['size']==b['size'] and a['layers']==b['layers']
  assert max(abs(x-y) for x,y in zip(a['position'],b['position']))<1e-6,(k,a['position'],b['position'])
  assert set(a['styles'])==set(b['styles'])
 items={i.id():i for i in layout.items() if hasattr(i,'id')}
 d1=items['D1_group_frame'];d2=items['D2_group_frame']
 gap=d2.pos().y()-(d1.pos().y()+d1.sizeWithUnits().height())
 assert abs(gap-GAP)<0.01,(gap,GAP)
 # Paper-size fonts: keep the enlarged epicenter date clear of satellite inset A.
 ev=items['Event_date_label'];dx=-3.0/S['font_scale_x']
 ev.attemptMove(QgsLayoutPoint(ev.pos().x()+dx,ev.pos().y()))
 report_shifts=[{'id':'Event_date_label','dx_a4_mm':-3.0,'reason':'Clear satellite inset A at paper-size fonts'}]
 for other in list(project.layoutManager().layouts()):
  if other!=layout:project.layoutManager().removeLayout(other)
 layout.renderContext().setDpi(S['native_export_dpi'])
 pdf=D/'work/figure13_native_aligned.pdf';config=QgsLayoutExporter.PdfExportSettings()
 config.dpi=S['native_export_dpi'];config.forceVectorOutput=True;config.rasterizeWholeImage=False
 config.simplifyGeometries=False;config.textRenderFormat=Qgis.TextRenderFormat.AlwaysText;config.appendGeoreference=False
 print('Exporting '+str(pdf),flush=True);layout.refresh()
 assert QgsLayoutExporter(layout).exportToPdf(str(pdf),config)==QgsLayoutExporter.Success
 target=D/'13_event_validation_aligned.qgz';project.setFileName(str(target))
 project.setFilePathStorage(Qgis.FilePathType.Relative);assert project.write()
 qpt=D/'Figure13_Aligned_Layout.qpt';save=QgsReadWriteContext();save.setPathResolver(QgsPathResolver(str(qpt)))
 assert layout.saveAsTemplate(str(qpt),save)
 assert digest(source)==protected
 report={'pdf':str(pdf),'project':str(target),'qpt':str(qpt),'layout_name':S['native_layout'],'fonts':rows,
  'anchors':anchors,'frames':frames,'position_adjustments':[],'adopted_position_recovery':[],
  'ps_marker_changes':{'diameter_native_mm':PS_DIAM,'outline':'none','layout_styles':ps_style_changes,
   'project_layers':project_ps},
  'right_group_gap_mm':{'target':GAP,'measured':gap,'d1_frame':[d1.pos().x(),d1.pos().y()],
   'd2_frame':[d2.pos().x(),d2.pos().y()],'frame_height':d1.sizeWithUnits().height()},
  'assets':assets,
  'map_geometry_layers_and_nonfont_styles_preserved':True,'text_content_preserved':True,
  'original_anchors_preserved_except_listed_class_captions':True,
  'class_caption_font_changed_to_a4_pt':F.get('classes'),
  'map_state_before':original_state,'map_state_after':after_state,
  'source_matches_adopted_panels':True,'native_dpi':config.dpi}
 (D/'native_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'native_pdf':str(pdf),'font_items':len(rows),'ps_layout_symbols':sum(x['symbols'] for x in ps_style_changes),
  'ps_project_symbols':sum(x['symbols'] for x in project_ps),'gap_mm':gap,'layout':layout.name()},ensure_ascii=False),flush=True)
 return project,layout
if __name__=='__main__':
 main();os._exit(0)
