"""QGIS two-campus, three-column satellite / risk / deformation comparison."""
from pathlib import Path
import json,os,hashlib,shutil
from qgis.core import *
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor,QFont

ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'result/validation/13_event_validation/maps';ASSETS=OUT/'campus_2x3'
TARGET=ROOT/'plot/13_event_validation/qgis/support/validation_campuses_2x3.qgz'
NODES=[(-18,'#B2182B'),(-12,'#E34A33'),(-6,'#ECD6A8'),(-3,'#C8E6AE'),(0,'#8AC65A'),(3,'#C5E4B5'),(6,'#92C7DC'),(12,'#4C91BF'),(18,'#18558C')]
COLORS=['#FFF7BC','#FEE391','#FEC44F','#FC4E2A','#BD0026']

def text(layout,id_,value,x,y,w,h,size=9,bold=True,color='#24333B'):
    item=QgsLayoutItemLabel(layout);item.setId(id_);item.setText(value)
    fmt=QgsTextFormat();font=QFont('Arial');font.setBold(bold);fmt.setFont(font);fmt.setSize(size);fmt.setColor(QColor(color))
    item.setTextFormat(fmt);item.setMargin(0);item.setVAlign(Qt.AlignVCenter)
    layout.addLayoutItem(item);item.attemptMove(QgsLayoutPoint(x,y));item.attemptResize(QgsLayoutSize(w,h));return item

def rectangle(layout,x,y,w,h,fill,stroke='transparent',width=.2):
    item=QgsLayoutItemShape(layout);item.setShapeType(QgsLayoutItemShape.Rectangle)
    item.setSymbol(QgsFillSymbol.createSimple({'color':fill,'outline_color':stroke,'outline_width':str(width)}))
    layout.addLayoutItem(item);item.attemptMove(QgsLayoutPoint(x,y));item.attemptResize(QgsLayoutSize(w,h));return item

def border_symbol():
    symbol=QgsFillSymbol.createSimple({'style':'no','outline_color':'white','outline_width':'.85'})
    line=QgsSimpleFillSymbolLayer.create({'style':'no','outline_color':'#08A9BE','outline_width':'.52'})
    symbol.appendSymbolLayer(line);return symbol

def main():
    image_manifest=json.loads((ASSETS/'imagery_manifest.json').read_text())
    source_manifest=json.loads((ASSETS/'panel_data_manifest.json').read_text())
    protected=source_manifest['sources_sha256']
    project=QgsProject();project.setCrs(QgsCoordinateReferenceSystem('EPSG:3857'));project.setEllipsoid('WGS84')
    project.setTitle('财大与农大验证 · 卫星影像 / 最终风险 / 形变 · 2×3')
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setBackgroundColor(QColor('white'))
    layout=QgsPrintLayout(project);layout.initializeDefaults();layout.setName('Validation_Campuses_2x3')
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(285,250));layout.renderContext().setDpi(1200)
    project.layoutManager().addLayout(layout)
    gp=str(ASSETS/'campus_panel_data.gpkg')
    breaks=json.loads((ROOT/'result/risk/scs_paper_method/calculation_summary.json').read_text())['jenks_breaks']
    all_layers=[];maps=[];records=[]
    def add(layer,group,visible=False):
        assert layer.isValid(),layer.source();project.addMapLayer(layer,False);node=group.addLayer(layer);node.setItemVisibilityChecked(visible);all_layers.append(layer);return layer
    for row,cid in enumerate(['CF','NY']):
        case='YUFE' if cid=='CF' else 'YNAU'
        group=project.layerTreeRoot().addGroup(case+' · satellite / risk / deformation')
        cached=next(x for x in image_manifest['cases'] if x['case_id']==cid)
        sat=add(QgsRasterLayer(str(ROOT/cached['tif']),case+' · Esri satellite cache','gdal'),group,True)
        md=sat.metadata();md.setTitle('Esri World Imagery campus context');md.setAbstract('Cached public World Imagery context, accessed 2026-10-17. Mosaic acquisition dates vary; not event-time damage imagery. '+image_manifest['source'])
        md.setRights([str(image_manifest.get('copyright','Esri and imagery contributors'))]);sat.setMetadata(md)
        boundary=add(QgsVectorLayer(gp+'|layername=campus_boundaries',case+' · campus reference boundaries','ogr'),group,True)
        assert boundary.setSubsetString(f'"case_id"=\'{cid}\'');boundary.setRenderer(QgsSingleSymbolRenderer(border_symbol()))
        labeled=boundary.clone();labeled.setName(case+' · labeled boundaries');add(labeled,group)
        labels=QgsPalLayerSettings();labels.fieldName="CASE WHEN location_id='CF01' THEN 'South' WHEN location_id='CF02' THEN 'North' WHEN location_id='NY01' THEN 'East' ELSE 'West' END";labels.isExpression=True
        fmt=QgsTextFormat();fmt.setFont(QFont('Arial',12,QFont.Bold));fmt.setSize(12);fmt.setColor(QColor('#24282B'))
        halo=QgsTextBufferSettings();halo.setEnabled(True);halo.setSize(.55);halo.setColor(QColor('white'));fmt.setBuffer(halo);labels.setFormat(fmt)
        labeled.setLabeling(QgsVectorLayerSimpleLabeling(labels));labeled.setLabelsEnabled(True)
        risk=add(QgsVectorLayer(gp+'|layername=campus_buildings',case+' · final risk (current classes)','ogr'),group)
        assert risk.setSubsetString(f'"case_id"=\'{cid}\' AND "Risk_Final" IS NOT NULL')
        ranges=[QgsRendererRange(breaks[i],breaks[i+1],QgsFillSymbol.createSimple({'color':COLORS[i],'outline_color':'#3E545D','outline_width':'.10'}),['Very Low','Low','Moderate','High','Very High'][i]) for i in range(5)]
        risk.setRenderer(QgsGraduatedSymbolRenderer('Risk_Final',ranges))
        missing=add(QgsVectorLayer(gp+'|layername=campus_buildings',case+' · risk unavailable','ogr'),group)
        assert missing.setSubsetString(f'"case_id"=\'{cid}\' AND "Risk_Final" IS NULL')
        missing.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'style':'no','outline_color':'#A6A6A6','outline_width':'.25'})))
        known=add(QgsVectorLayer(gp+'|layername=confirmed_damage',case+' · user-confirmed damage','ogr'),group)
        assert known.setSubsetString(f'"case_id"=\'{cid}\'')
        sym=QgsFillSymbol.createSimple({'style':'no','outline_color':'white','outline_width':'.85'})
        sym.appendSymbolLayer(QgsSimpleFillSymbolLayer.create({'style':'no','outline_color':'#D827C8','outline_width':'.42'}))
        known.setRenderer(QgsSingleSymbolRenderer(sym))
        velocity=add(QgsRasterLayer(str(ASSETS/f'{cid}_vertical_velocity.tif'),case+' · vertical deformation (20 m)','gdal'),group)
        ramp=QgsColorRampShader(-18,18);ramp.setColorRampType(QgsColorRampShader.Interpolated)
        ramp.setColorRampItemList([QgsColorRampShader.ColorRampItem(v,QColor(col),str(v)) for v,col in NODES]);ramp.setClip(False)
        shader=QgsRasterShader(-18,18);shader.setRasterShaderFunction(ramp)
        renderer=QgsSingleBandPseudoColorRenderer(velocity.dataProvider(),1,shader);renderer.setClassificationMin(-18);renderer.setClassificationMax(18);renderer.setOpacity(.85)
        velocity.setRenderer(renderer)
        ordered=[[labeled,sat],[known,boundary,risk,missing,sat],[known,boundary,velocity,sat]]
        extent=QgsRectangle(*cached['bounds_3857'])
        y=16 if row==0 else 122
        for col,layers in enumerate(ordered):
            x=10+92*col;letter=chr(97+row*3+col)
            title=[f'({letter}) {case}: satellite imagery',f'({letter}) {case}: final building risk',f'({letter}) {case}: vertical deformation'][col]
            text(layout,'Title_'+letter,title,x,y-9,86,7,10.5)
            m=QgsLayoutItemMap(layout);layout.addLayoutItem(m);m.setId('Campus_'+letter)
            m.attemptMove(QgsLayoutPoint(x,y));m.attemptResize(QgsLayoutSize(86,82));m.setCrs(project.crs());m.setLayers(layers)
            m.setKeepLayerSet(True);m.setFollowVisibilityPreset(False);m.zoomToExtent(extent)
            styles={}
            for layer in layers:
                style=QgsMapLayerStyle();style.readFromLayer(layer);styles[layer.id()]=style.xmlData()
            m.setLayerStyleOverrides(styles);m.setKeepLayerStyles(True)
            m.setFrameEnabled(True);m.setFrameStrokeColor(QColor('#26343B'));m.setFrameStrokeWidth(QgsLayoutMeasurement(.25))
            maps.append(m);records.append(dict(panel=letter,case_id=cid,role=['satellite','final risk','vertical deformation'][col],extent=m.extent().toString(9),layers=[l.name() for l in layers]))
            if col==0:
                # Reuse the study-area map's arrow and typography, below the map frame.
                north_svg=ASSETS/'north_arrow_reference.svg'
                shutil.copy2(ROOT/'plot/01_study_area/qgis/layouts/study_area/north_arrow.svg',north_svg)
                n=text(layout,'North_'+letter,'N',x+2.5,y+84,5,4,9)
                nf=n.textFormat();nf.setFont(QFont('Times New Roman',9,QFont.Bold));nf.setSize(9);n.setTextFormat(nf);n.setHAlign(Qt.AlignHCenter)
                arrow=QgsLayoutItemPicture(layout);arrow.setId('True_North_'+letter);layout.addLayoutItem(arrow)
                arrow.attemptMove(QgsLayoutPoint(x+3,y+88));arrow.attemptResize(QgsLayoutSize(4,7))
                arrow.setPicturePath(str(north_svg));arrow.setLinkedMap(m);arrow.setNorthMode(QgsLayoutItemPicture.TrueNorth)
                scale=QgsLayoutItemScaleBar(layout);scale.setId('Scale_'+letter);scale.setStyle('Line Ticks Up');scale.setLinkedMap(m)
                scale.setUnits(Qgis.DistanceUnit.Meters);scale.setUnitsPerSegment(200);scale.setNumberOfSegments(1);scale.setNumberOfSegmentsLeft(0);scale.setUnitLabel('m');scale.setHeight(1.2)
                sf=QgsTextFormat();sf.setFont(QFont('Arial',10,QFont.Bold));sf.setSize(10);sf.setColor(QColor('#24282B'));scale.setTextFormat(sf)
                scale.setLineSymbol(QgsLineSymbol.createSimple({'line_color':'#24282B','line_width':'.22'}))
                scale.setLabelBarSpace(.7);scale.setBoxContentSpace(.8);scale.setBackgroundEnabled(False)
                layout.addLayoutItem(scale);scale.attemptMove(QgsLayoutPoint(x+17,y+86))
    # Column-specific common legends.
    rectangle(layout,10,225,7,3,'transparent','#08A9BE',.52);text(layout,'Boundary_key','Campus reference boundary',19,223,76,7,9)
    rectangle(layout,10,232,7,3,'transparent','#A6A6A6',.25);text(layout,'Missing_key','Risk unavailable (35 buildings)',19,230,76,7,9)
    rectangle(layout,10,239,7,3,'transparent','#D827C8',.42);text(layout,'Known_key','Confirmed damage (3 buildings)',19,237,76,7,9)
    text(layout,'Risk_key_title','Final risk: current five-class result',102,223,86,6,9.5)
    for i,name in enumerate(['Very Low','Low','Moderate','High','Very High']):
        x=102+i*17.2;rectangle(layout,x,231,15,3.2,COLORS[i],'#48545A',.12);text(layout,'Risk_key_'+str(i),name,x,235,17,5,8)
    text(layout,'Velocity_key_title','Vertical deformation rate (mm/yr)',194,223,86,6,9.5)
    svg=ASSETS/'velocity_legend.svg'
    stops=''.join(f'<stop offset="{(v+18)/36*100:.6f}%" stop-color="{col}"/>' for v,col in NODES)
    ticks=''.join(f'<line x1="{20+(v+18)/36*960:.3f}" x2="{20+(v+18)/36*960:.3f}" y1="48" y2="57" stroke="#24333B"/><text x="{20+(v+18)/36*960:.3f}" y="91" text-anchor="middle" font-family="Arial" font-size="32" font-weight="bold">{v:g}</text>' for v,_ in NODES)
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="105" viewBox="0 0 1000 105"><defs><linearGradient id="r">{stops}</linearGradient></defs><rect x="20" y="10" width="960" height="38" fill="url(#r)" stroke="#384750"/>{ticks}</svg>')
    picture=QgsLayoutItemPicture(layout);layout.addLayoutItem(picture);picture.setPicturePath(str(svg));picture.attemptMove(QgsLayoutPoint(194,230));picture.attemptResize(QgsLayoutSize(86,11))
    project.layerTreeRoot().setHasCustomLayerOrder(True);project.layerTreeRoot().setCustomLayerOrder(all_layers)
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(maps[0].extent(),project.crs()))
    project.setCustomVariables({'validation_sites':'YUFE and YNAU only','layout_grid':'2 rows x 3 columns','deformation_input':'2017-2019 vertical rate; existing 20 m raster','satellite_role':'Context only; acquisition dates vary'})
    for row in (0,1):assert all(maps[row*3].extent()==maps[row*3+i].extent() for i in (1,2))
    assert project.write(str(TARGET))
    exporter=QgsLayoutExporter(layout)
    for dpi,suffix in [(180,'preview'),(1200,'1200dpi')]:
        im=exporter.renderPageToImage(0,dpi=dpi);assert not im.isNull()
        im.setDotsPerMeterX(round(dpi/.0254));im.setDotsPerMeterY(round(dpi/.0254));assert im.save(str(OUT/f'validation_campuses_2x3_{suffix}.png'))
    settings=QgsLayoutExporter.PdfExportSettings();settings.dpi=1200;settings.forceVectorOutput=True;settings.textRenderFormat=Qgis.TextRenderFormat.AlwaysText;settings.simplifyGeometries=False
    assert exporter.exportToPdf(str(OUT/'validation_campuses_2x3.pdf'),settings)==QgsLayoutExporter.Success
    context=QgsReadWriteContext();context.setPathResolver(QgsPathResolver(str(OUT/'validation_campuses_2x3.qpt')))
    assert layout.saveAsTemplate(str(OUT/'validation_campuses_2x3.qpt'),context)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in protected.items())
    (ASSETS/'layout_verification.json').write_text(json.dumps(dict(project=str(TARGET),layout=layout.name(),rows=2,columns=3,site_n=2,
      panels=records,satellite_local=True,source_data_unchanged=True,building_risk_thresholds=breaks,deformation_nodes=NODES,
      deformation_opacity=.85,scope='Campus reference boundaries, no buffers; Jiangnanchun excluded',pdf_dpi=1200,
      visible_footer_notes=False,orientation_and_scale='below each campus row, outside map frames',
      annotation_style={'reference':'QGIS study-area and hazard maps','font':'Arial Bold','panel_titles_pt':10.5,
        'campus_labels_pt':12,'campus_labels_halo_mm':.55,'legend_titles_pt':9.5,'legend_items_pt':9,
        'north_N':'Times New Roman Bold 9 pt','scale':'Arial Bold 10 pt, Line Ticks Up, 200 m'}),ensure_ascii=False,indent=2)+'\n')
    print(TARGET,flush=True);os._exit(0)

if __name__=='__main__':
    app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis();main()
