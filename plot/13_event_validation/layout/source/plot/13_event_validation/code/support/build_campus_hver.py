"""Two-campus 2x5 layout: remote sensing plus original H/V/E/R maps on the hazard basemap."""
from pathlib import Path
import json,os,hashlib
import xml.etree.ElementTree as ET
from qgis.core import *
from qgis.PyQt.QtCore import Qt,QPointF
from qgis.PyQt.QtGui import QColor,QFont,QPolygonF
from qgis.PyQt.QtXml import QDomDocument
from build_campus_2x3 import text,rectangle,border_symbol

ROOT=Path(__file__).resolve().parents[4];OUT=ROOT/'result/validation/13_event_validation/maps';ASSETS=OUT/'campus_hver'
TARGET=ROOT/'QGIS/13_event_validation/support/validation_campuses_2x5.qgz'
BASE=ROOT/'QGIS/04_seismic_hazard/projects/04_seismic_hazard_streets.qgz'
NAMES=['Very Low','Low','Moderate','High','Very High']
PHOTO_CASES={'CF':{'id':34360,'label':'D1','label_mm':(68,64)},
             'NY':{'id':35945,'label':'D2','label_mm':(6,31)}}

def halo_text(item,width=.55):
    fmt=item.textFormat();halo=QgsTextBufferSettings();halo.setEnabled(True)
    halo.setSize(width);halo.setColor(QColor('white'));fmt.setBuffer(halo)
    item.setTextFormat(fmt);item.setBackgroundEnabled(False);item.setFrameEnabled(False)

def damage_callout(layout,map_item,feature,case,letter,indicator=None):
    """Place the selected photo case on the same footprint in all five panels."""
    # The caller has transformed the footprint from its layer CRS to the map CRS.
    point=feature.geometry().pointOnSurface().asPoint()
    extent=map_item.extent();x=map_item.pos().x();y=map_item.pos().y()
    px=x+(point.x()-extent.xMinimum())/extent.width()*86
    py=y+(extent.yMaximum()-point.y())/extent.height()*82
    dx,dy=((58,61) if case['label']=='D1' else (3,25)) if indicator else case['label_mm']
    lx=x+dx;ly=y+dy
    # White casing and a thin magenta leader remain visible on both base maps.
    end_x=lx+21 if indicator and case['label']=='D2' else lx+(9 if dx<40 else 0)
    line=QgsLayoutItemPolyline(QPolygonF([QPointF(px,py),QPointF(end_x,ly+3)]),layout)
    line.setId('Damage_leader_'+letter)
    symbol=QgsLineSymbol.createSimple({'line_color':'white','line_width':'.85'})
    symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color':'#B20A8F','line_width':'.28'}))
    line.setSymbol(symbol);layout.addLayoutItem(line);line.setZValue(30)
    label=text(layout,'Damage_'+case['label']+'_'+letter,case['label'],lx,ly,10,6,11,True,'#B20A8F')
    halo_text(label,.65);label.setZValue(31)
    label.setCustomProperty('validation/Build_ID',case['id'])
    label.setCustomProperty('validation/target_3857',f'{point.x():.6f},{point.y():.6f}')
    if indicator:
        level=feature[indicator['class_field']];assert level in NAMES
        color=indicator['colors'][NAMES.index(level)]
        caption=level+' risk' if indicator['key']=='risk' else level
        grade=text(layout,'Damage_Grade_'+letter,caption,lx,ly+5,27,7,12,True,color)
        halo_text(grade,.65);grade.setZValue(31)
        # A thin dark edge makes the original yellow Low class legible on white.
        if level in ('Very Low','Low'):
            fmt=grade.textFormat();buffer=fmt.buffer();buffer.setColor(QColor('#384047'));buffer.setSize(.10);fmt.setBuffer(buffer);grade.setTextFormat(fmt)
        grade.setCustomProperty('validation/Build_ID',case['id'])
        grade.setCustomProperty('validation/indicator',indicator['key'])
        grade.setCustomProperty('validation/class_field',indicator['class_field'])
        grade.setCustomProperty('validation/class',level)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def appearance(layer):
    style=QgsMapLayerStyle();style.readFromLayer(layer);root=ET.fromstring(style.xmlData())
    node=root.find('renderer-v2') if isinstance(layer,QgsVectorLayer) else root.find('./pipe/rasterrenderer')
    assert node is not None,layer.name()
    return hashlib.sha256(ET.canonicalize(ET.tostring(node,encoding='unicode')).encode()).hexdigest()

def main():
    data=json.loads((ASSETS/'data_manifest.json').read_text())
    image_manifest=json.loads((OUT/'campus_2x3/imagery_manifest.json').read_text())
    protected=dict(data['sources_sha256']);protected[str(BASE)]=sha(BASE)
    manuscript=ROOT/'manuscript/tex/manuscript.tex'
    reference_hash={'path':str(manuscript),'historical_sha256':protected.pop(str(manuscript)),
                    'sha256_at_start':sha(manuscript),'written_by_validation':False}
    reference=QgsProject();assert reference.read(str(BASE))
    base_layout=reference.layoutManager().layoutByName('Kunming_Hazard_PGA_Streets');assert base_layout
    source_map=base_layout.itemById('Hazard_Main_Map');source_overrides=source_map.layerStyleOverrides()
    project=QgsProject();project.setCrs(QgsCoordinateReferenceSystem('EPSG:3857'));project.setEllipsoid('WGS84')
    project.setTitle('财大与农大验证 · 遥感影像 / H / V / E / R · 2×5');project.setFilePathStorage(Qgis.FilePathType.Relative)
    layout=QgsPrintLayout(project);layout.initializeDefaults();layout.setName('Validation_Campuses_HVER')
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(474,219));layout.renderContext().setDpi(1200);project.layoutManager().addLayout(layout)
    foundation=project.layerTreeRoot().addGroup('危险性空间布局底图 · 原样式')
    base_order=[];base_records=[];all_layers=[]
    for src in source_map.layers():
        if src.customProperty('seismic_building/result_key','')=='hazard':base_order.append(None);continue
        clone=src.clone()
        if src.id() in source_overrides:QgsMapLayerStyle(source_overrides[src.id()]).writeToLayer(clone)
        assert clone.isValid();project.addMapLayer(clone,False);node=foundation.addLayer(clone);node.setItemVisibilityChecked(False)
        style_hash=appearance(clone);clone.setCustomProperty('validation/hazard_basemap_style_sha256',style_hash)
        clone.setCustomProperty('validation/hazard_basemap_source_id',src.id())
        base_records.append(dict(name=clone.name(),source=clone.source(),source_layer_id=src.id(),appearance_sha256=style_hash))
        base_order.append(clone);all_layers.append(clone)
    assert len(base_order)==len(source_map.layers()) and base_order.count(None)==1
    source_buildings=str(ASSETS/'campus_hver.fgb');maps=[];panels=[]
    def add(layer,group,visible=False):
        assert layer.isValid(),layer.source();project.addMapLayer(layer,False);node=group.addLayer(layer);node.setItemVisibilityChecked(visible);all_layers.append(layer);return layer
    for row,cid in enumerate(['CF','NY']):
        case='YUFE' if cid=='CF' else 'YNAU';group=project.layerTreeRoot().insertGroup(row,case+' · remote sensing / H / V / E / R')
        cached=next(c for c in image_manifest['cases'] if c['case_id']==cid)
        sat=add(QgsRasterLayer(str(ROOT/cached['tif']),case+' · remote sensing imagery','gdal'),group,True)
        md=sat.metadata();md.setAbstract('Cached Esri World Imagery context; acquisition dates vary. '+image_manifest['source']);md.setRights([image_manifest['copyright']]);sat.setMetadata(md)
        boundary=add(QgsVectorLayer(str(ASSETS/'campus_boundaries.fgb'),case+' · campus reference boundaries','ogr'),group,True)
        assert boundary.setSubsetString(f'"case_id"=\'{cid}\'');boundary.setRenderer(QgsSingleSymbolRenderer(border_symbol()))
        labeled=boundary.clone();labeled.setName(case+' · labeled boundaries');add(labeled,group)
        labels=QgsPalLayerSettings();labels.fieldName="CASE WHEN location_id='CF01' THEN 'South' WHEN location_id='CF02' THEN 'North' WHEN location_id='NY01' THEN 'East' ELSE 'West' END";labels.isExpression=True
        fmt=QgsTextFormat();fmt.setFont(QFont('Arial',12,QFont.Bold));fmt.setSize(12);fmt.setColor(QColor('#24282B'))
        halo=QgsTextBufferSettings();halo.setEnabled(True);halo.setSize(.55);halo.setColor(QColor('white'));fmt.setBuffer(halo);labels.setFormat(fmt)
        labeled.setLabeling(QgsVectorLayerSimpleLabeling(labels));labeled.setLabelsEnabled(True)
        selected=PHOTO_CASES[cid]
        known=add(QgsVectorLayer(str(ASSETS/'confirmed_damage.fgb'),case+' · photographed damage '+selected['label'],'ogr'),group)
        assert known.setSubsetString(f'"case_id"=\'{cid}\' AND "Build_ID"={selected["id"]}')
        features=list(known.getFeatures());assert len(features)==1
        target=QgsFeature(features[0]);target_geometry=QgsGeometry(target.geometry())
        target_geometry.transform(QgsCoordinateTransform(known.crs(),project.crs(),project))
        target.setGeometry(target_geometry)
        sym=QgsFillSymbol.createSimple({'style':'no','outline_color':'white','outline_width':'.85'})
        sym.appendSymbolLayer(QgsSimpleFillSymbolLayer.create({'style':'no','outline_color':'#D827C8','outline_width':'.42'}));known.setRenderer(QgsSingleSymbolRenderer(sym))
        emphasis=known.clone();emphasis.setName(known.name()+' · indicator emphasis');add(emphasis,group)
        sym=QgsFillSymbol.createSimple({'style':'no','outline_color':'white','outline_width':'1.15'})
        sym.appendSymbolLayer(QgsSimpleFillSymbolLayer.create({'style':'no','outline_color':'#D827C8','outline_width':'.65'}));emphasis.setRenderer(QgsSingleSymbolRenderer(sym))
        ordered=[[known,labeled,sat]]
        for config in data['configs']:
            key=config['key'];value=config['value']
            layer=add(QgsVectorLayer(source_buildings,case+' · '+key,'ogr'),group)
            assert layer.setSubsetString(f'"case_id"=\'{cid}\' AND "{value}" IS NOT NULL')
            document=QDomDocument();assert document.setContent((ROOT/config['renderer']).read_text())[0]
            renderer=QgsFeatureRenderer.load(document.documentElement(),QgsReadWriteContext());assert renderer
            layer.setRenderer(renderer);layer.setLabelsEnabled(False);layer.setScaleBasedVisibility(False)
            missing=add(QgsVectorLayer(source_buildings,case+' · '+key+' unavailable','ogr'),group)
            assert missing.setSubsetString(f'"case_id"=\'{cid}\' AND "{value}" IS NULL')
            missing.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'style':'no','outline_color':'#A6A6A6','outline_width':'.25'})))
            stack=[emphasis,boundary]
            for base in base_order:stack.extend([layer,missing] if base is None else [base])
            ordered.append(stack)
        extent=QgsRectangle(*cached['bounds_3857']);y=16 if row==0 else 109
        bookmark=QgsBookmark();bookmark.setName(case);bookmark.setGroup('验证校园');bookmark.setExtent(QgsReferencedRectangle(extent,project.crs()));project.bookmarkManager().addBookmark(bookmark)
        for col,layers in enumerate(ordered):
            x=10+92*col;letter=chr(97+row*5+col)
            title=f'({letter}) '+(case+': remote sensing' if col==0 else ['Hazard','Vulnerability','Exposure','Risk'][col-1])
            text(layout,'Title_'+letter,title,x,y-9,86,7,10.5)
            m=QgsLayoutItemMap(layout);layout.addLayoutItem(m);m.setId('Campus_'+letter)
            m.setZValue(1)
            m.attemptMove(QgsLayoutPoint(x,y));m.attemptResize(QgsLayoutSize(86,82));m.setCrs(project.crs());m.setLayers(layers);m.setKeepLayerSet(True);m.setFollowVisibilityPreset(False);m.zoomToExtent(extent)
            styles={}
            for layer in layers:
                style=QgsMapLayerStyle();style.readFromLayer(layer);styles[layer.id()]=style.xmlData()
            m.setLayerStyleOverrides(styles);m.setKeepLayerStyles(True)
            m.setFrameEnabled(True);m.setFrameStrokeColor(QColor('#26343B'));m.setFrameStrokeWidth(QgsLayoutMeasurement(.25))
            maps.append(m);panels.append(dict(id=m.id(),case_id=cid,column=col,role=['remote sensing','hazard','vulnerability','exposure','risk'][col],
                extent=m.extent().toString(9),layers=[l.name() for l in layers]))
            damage_callout(layout,m,target,selected,letter,indicator=data['configs'][col-1] if col else None)
            if col==0:
                arrow_file=ASSETS/'north_arrow_reference.svg'
                source_arrow=(ROOT/'QGIS/01_study_area/layouts/study_area/north_arrow.svg').read_text()
                arrow_file.write_text(source_arrow.replace('fill="black"','fill="black" stroke="white" stroke-width="5" stroke-linejoin="round"'))
                n=text(layout,'North_'+letter,'N',x+76.5,y+3,5,4,9)
                nf=n.textFormat();nf.setFont(QFont('Arial',9,QFont.Bold));nf.setSize(9);n.setTextFormat(nf);n.setHAlign(Qt.AlignHCenter);halo_text(n,.5)
                arrow=QgsLayoutItemPicture(layout);arrow.setId('True_North_'+letter);layout.addLayoutItem(arrow);arrow.attemptMove(QgsLayoutPoint(x+77,y+7));arrow.attemptResize(QgsLayoutSize(4,7));arrow.setPicturePath(str(arrow_file));arrow.setLinkedMap(m);arrow.setNorthMode(QgsLayoutItemPicture.TrueNorth);arrow.setBackgroundEnabled(False);arrow.setFrameEnabled(False)
                scale=QgsLayoutItemScaleBar(layout);scale.setId('Scale_'+letter);scale.setStyle('Line Ticks Up');scale.setLinkedMap(m)
                scale.setUnits(Qgis.DistanceUnit.Meters);scale.setUnitsPerSegment(200);scale.setNumberOfSegments(1);scale.setNumberOfSegmentsLeft(0);scale.setUnitLabel('m');scale.setHeight(1.2)
                sf=QgsTextFormat();sf.setFont(QFont('Arial',10,QFont.Bold));sf.setSize(10);sf.setColor(QColor('#24282B'))
                halo=QgsTextBufferSettings();halo.setEnabled(True);halo.setSize(.5);halo.setColor(QColor('white'));sf.setBuffer(halo);scale.setTextFormat(sf)
                scale_line=QgsLineSymbol.createSimple({'line_color':'white','line_width':'.85'})
                scale_line.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color':'#24282B','line_width':'.22'}))
                scale.setLineSymbol(scale_line);scale.setLabelBarSpace(.7);scale.setBoxContentSpace(.8);scale.setBackgroundEnabled(False);scale.setFrameEnabled(False)
                layout.addLayoutItem(scale);scale.attemptMove(QgsLayoutPoint(x+3,y+68))
    # Legends only; methodological and source notes remain in metadata/report.
    for y,color,label in [(196,'#08A9BE','Campus reference boundary'),(203,'#A6A6A6','Unavailable result'),(210,'#D827C8','Damage: D1 (34360), D2 (35945)')]:
        rectangle(layout,10,y,7,3,'transparent',color,.52 if y==196 else .42);text(layout,'Key_'+str(y),label,19,y-2,76,7,9)
    for col,config in enumerate(data['configs'],1):
        x=10+92*col
        text(layout,'Legend_'+config['key'],['Hazard: PGA (g)','Vulnerability','Exposure','Risk'][col-1],x,194,86,6,9.5)
        for i,(name,color) in enumerate(zip(NAMES,config['colors'])):
            xx=x+i*17.2;rectangle(layout,xx,202,15,3.2,color,'#48545A',.12);text(layout,'Legend_'+config['key']+'_'+str(i),name,xx,206,17,5,8)
    project.layerTreeRoot().setHasCustomLayerOrder(True);project.layerTreeRoot().setCustomLayerOrder(all_layers)
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(maps[0].extent(),project.crs()))
    project.setCustomVariables({'validation_sites':'YUFE and YNAU only','layout_grid':'2 rows x 5 columns','indicator_order':'remote sensing, H, V, E, R','basemap_reference':str(BASE),'photographed_damage_ids':'D1:34360; D2:35945','orientation_and_scale':'inside first map per row; transparent backgrounds','damage_sample_scope':'Figure highlights 2 photographed cases; original 3 confirmed positives retained in experiment','annotation_font':'Arial Bold','indicator_emphasis':'H/V/E/R labels derive from each stored class; original fills and thresholds; thicker target outline only'})
    for row in (0,1):assert all(maps[row*5].extent()==maps[row*5+i].extent() for i in range(1,5))
    assert project.write(str(TARGET))
    exporter=QgsLayoutExporter(layout)
    for dpi,suffix in [(180,'preview'),(1200,'1200dpi')]:
        im=exporter.renderPageToImage(0,dpi=dpi);assert not im.isNull();im.setDotsPerMeterX(round(dpi/.0254));im.setDotsPerMeterY(round(dpi/.0254))
        assert im.save(str(OUT/f'validation_campuses_2x5_{suffix}.png'))
        del im
    settings=QgsLayoutExporter.PdfExportSettings();settings.dpi=1200;settings.forceVectorOutput=True;settings.textRenderFormat=Qgis.TextRenderFormat.AlwaysText;settings.simplifyGeometries=False
    assert exporter.exportToPdf(str(OUT/'validation_campuses_2x5.pdf'),settings)==QgsLayoutExporter.Success
    context=QgsReadWriteContext();context.setPathResolver(QgsPathResolver(str(OUT/'validation_campuses_2x5.qpt')))
    assert layout.saveAsTemplate(str(OUT/'validation_campuses_2x5.qpt'),context)
    assert all(sha(Path(p))==h for p,h in protected.items())
    reference_hash['sha256_at_end']=sha(manuscript)
    (ASSETS/'layout_verification.json').write_text(json.dumps(dict(project=str(TARGET),layout=layout.name(),rows=2,columns=5,
      panels=panels,basemap_project=str(BASE),basemap_layout=base_layout.name(),basemap_layers=base_records,
      basemap_styles_reused=True,satellite_only_in_first_column=True,visible_footer_notes=False,
      page_mm=[474,219],row_map_y_mm=[16,109],orientation_and_scale='inside first map per row; transparent backgrounds',
      photographed_damage_cases=PHOTO_CASES,original_positive_ids=data['positive_ids'],
      annotation_font='Arial Bold',indicator_emphasis='Stored H/V/E/R classes displayed in their own panels; original fills and thresholds preserved',
      readonly_manuscript_reference=reference_hash,
      source_values_and_projects_unchanged=True,indicator_coverage=data['counts'],sources_sha256=protected,pdf_dpi=1200),ensure_ascii=False,indent=2)+'\n')
    print(TARGET,flush=True);os._exit(0)

if __name__=='__main__':
    app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis();main()
