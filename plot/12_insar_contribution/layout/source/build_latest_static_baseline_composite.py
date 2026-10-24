"""Current map composition using the frozen Static-only baseline results only.

This script reads published assessment derivatives, replaces the earlier map
theme, and adds the current pair's PS strip. It never fits a risk model.
"""
from pathlib import Path
import csv,json,os,shutil,sqlite3,zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from qgis.core import *
from qgis.PyQt.QtCore import QPointF,QVariant,Qt
from qgis.PyQt.QtGui import QColor,QFont
_mpl_cache=Path(__file__).resolve().parents[3]/'plot/12_insar_contribution/output/support/.mplconfig'
_mpl_cache.mkdir(parents=True,exist_ok=True);os.environ.setdefault('MPLCONFIGDIR',str(_mpl_cache))
from matplotlib import colormaps
from matplotlib.colors import LogNorm,to_hex
from build_changed_points_reference_map import OUT,ROOT,QDIR,PROJECT,TEMPLATE,FIGURE,digest,marker,text,save_and_export
from add_pair_white_block_zoom import fill,page_xy,gpkg_geometry,add_guide

LATEST=ROOT/'result/discussion/12_insar_contribution/static_baseline'
WORK=OUT/'support'
DB=ROOT/'result/intermediate/12_insar_contribution/cartography/latest_static_baseline_map.gpkg'
CONTEXT_DB=ROOT/'result/intermediate/12_insar_contribution/cartography/latest_static_baseline_block.gpkg'
STATS=LATEST/'data/static_baseline_statistics.json'
ALL=LATEST/'data/all_40000_buildings.csv'
CHANGED=LATEST/'data/all_risk_class_changes.csv'
BUILDINGS=ROOT/'result/intermediate/buildings/building_height_repaired.gpkg'
ROADS=ROOT/'data/cartography/kunming_simple_basemap.gpkg'
PS_SOURCE=ROOT/'result/intermediate/vulnerability_inputs/building_ps_points.gpkg'
PAIR=[39899,39929]
RED='#C5433C';BLUE='#2875B5';STROKE='#24282B'
LOCATOR_BLUE='#145DB8'
PREFIX='Latest_'


def csv_rows(path):
    with path.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def font_format(style,size=None):
    font=style.font();font.setFamily('Arial');font.setBold(True);font.setItalic(False)
    style.setFont(font)
    style.setSize(max(7.5,style.size() if size is None else size))
    return style


def label(layout,id_,value,x,y,w,h=5.5,size=8,bold=True,color=STROKE,center=False):
    item=text(layout,PREFIX+id_,value,x,y,w,size,True)
    item.attemptResize(QgsLayoutSize(w,h));item.setHAlign(Qt.AlignHCenter if center else Qt.AlignLeft)
    style=font_format(item.textFormat());style.setColor(QColor(color));buffer=style.buffer();buffer.setEnabled(False)
    style.setBuffer(buffer);item.setTextFormat(style);item.setZValue(80)
    return item


def shape(layout,id_,x,y,w,h,color,outline=STROKE,width=.45,z=30):
    item=QgsLayoutItemShape(layout);item.setId(PREFIX+id_);item.setShapeType(QgsLayoutItemShape.Rectangle)
    symbol=QgsFillSymbol.createSimple({'color':color,'outline_color':outline,
        'outline_style':'solid','outline_width':str(width),'joinstyle':'miter'})
    item.setSymbol(symbol);item.setBackgroundEnabled(False);item.setFrameEnabled(False)
    layout.addLayoutItem(item);item.attemptMove(QgsLayoutPoint(x,y));item.attemptResize(QgsLayoutSize(w,h));item.setZValue(z)
    return item


def regional_cartography():
    """Prune prior thematic layers before opening the historical project."""
    with zipfile.ZipFile(PROJECT) as archive:
        root=ET.fromstring(archive.read(next(n for n in archive.namelist() if n.endswith('.qgs'))))
    layout=root.find('.//Layouts/Layout')
    main=next(e for e in layout.findall('LayoutItem') if e.get('id')=='Changed_building_points_map')
    active={e.text for e in main.findall('LayerSet/Layer')}
    keep=set()
    for layer in list(root.find('projectlayers')):
        datasource=layer.findtext('datasource','')
        thematic=any(n in datasource for n in ['changed_building_points_1542.gpkg','latest_static_baseline_map.gpkg','latest_static_baseline_block.gpkg'])
        if layer.findtext('id') not in active or thematic:
            root.find('projectlayers').remove(layer);continue
        keep.add(layer.findtext('id'));ds=layer.find('datasource');parts=ds.text.split('|')
        if not Path(parts[0]).is_absolute():parts[0]=str((PROJECT.parent/parts[0]).resolve())
        ds.text='|'.join(parts)
    for e in list(main.find('LayerSet')):
        if e.text not in keep:main.find('LayerSet').remove(e)
    for item in list(layout.findall('LayoutItem')):
        if item.get('id','').startswith(('Pair_zoom_','Changed_points_legend',PREFIX)):
            layout.remove(item);continue
        if item.get('type')=='65640' and item.get('file'):
            path=Path(item.get('file'))
            if not path.is_absolute():item.set('file',str((PROJECT.parent/path).resolve()))
    for parent in root.iter():
        for child in list(parent):
            if child.tag=='layer-tree-layer' and child.get('id') not in keep:parent.remove(child)
    path=WORK/'regional_cartography.qgs';ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
    project=QgsProject();assert project.read(str(path))
    return project


def add_layer(project,path,table,name):
    layer=QgsVectorLayer(str(path)+'|layername='+table+'|option:IMMUTABLE=YES',name,'ogr')
    assert layer.isValid(),name;project.addMapLayer(layer);layer.setLabelsEnabled(False)
    layer.setCustomProperty('discussion/current_protocol','static_only_frozen_normalization_and_jenks')
    return layer


def write_layer(layer,path,name,create=False):
    options=QgsVectorFileWriter.SaveVectorOptions();options.driverName='GPKG';options.layerName=name
    options.actionOnExistingFile=QgsVectorFileWriter.CreateOrOverwriteFile if create else QgsVectorFileWriter.CreateOrOverwriteLayer
    result=QgsVectorFileWriter.writeAsVectorFormatV3(layer,str(path),QgsCoordinateTransformContext(),options)
    assert result[0]==QgsVectorFileWriter.NoError,result


def context_copy(project,bounds):
    window=QgsGeometry.fromRect(bounds)
    buildings=QgsVectorLayer('MultiPolygonZ?crs=EPSG:32648','block context','memory')
    buildings.dataProvider().addAttributes([QgsField('Build_ID',QVariant.LongLong)]);buildings.updateFields();features=[]
    with sqlite3.connect('file:'+str(BUILDINGS)+'?mode=ro&immutable=1',uri=True) as c:
        rows=c.execute('''SELECT b.Build_ID,b.geom FROM building_height_repaired b
            JOIN rtree_building_height_repaired_geom r ON b.fid=r.id
            WHERE r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=?''',
            (bounds.xMaximum(),bounds.xMinimum(),bounds.yMaximum(),bounds.yMinimum())).fetchall()
    for bid,blob in rows:
        geom=gpkg_geometry(blob)
        if not geom.intersects(window):continue
        geom.convertToMultiType();f=QgsFeature(buildings.fields());f.setAttributes([bid]);f.setGeometry(geom);features.append(f)
    assert buildings.dataProvider().addFeatures(features)[0];buildings.updateExtents()
    assert set(PAIR)<=set(int(f['Build_ID']) for f in features)
    write_layer(buildings,CONTEXT_DB,'block_buildings',True)
    roads=QgsVectorLayer('MultiLineString?crs=EPSG:32648','roads','memory')
    roads.dataProvider().addAttributes([QgsField('kind',QVariant.String)]);roads.updateFields();lines=[]
    to_geo=QgsCoordinateTransform(buildings.crs(),QgsCoordinateReferenceSystem('EPSG:4326'),project)
    bbox=to_geo.transformBoundingBox(bounds)
    to_local=QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),buildings.crs(),project)
    with sqlite3.connect('file:'+str(ROADS)+'?mode=ro&immutable=1',uri=True) as c:
        rows=c.execute('''SELECT b.kind,b.geom FROM roads b JOIN rtree_roads_geom r ON b.fid=r.id
            WHERE r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=? AND b.kind!='platform' ''',
            (bbox.xMaximum(),bbox.xMinimum(),bbox.yMaximum(),bbox.yMinimum())).fetchall()
    for kind,blob in rows:
        geom=gpkg_geometry(blob);geom.transform(to_local)
        if not geom.intersects(window):continue
        geom.convertToMultiType();f=QgsFeature(roads.fields());f.setAttributes([kind]);f.setGeometry(geom);lines.append(f)
    assert roads.dataProvider().addFeatures(lines)[0];roads.updateExtents();write_layer(roads,CONTEXT_DB,'block_roads')
    return len(features),len(lines)


def ps_context_copy(bounds):
    """Copy observed building-linked PS in the window; do not interpolate."""
    layer=QgsVectorLayer('Point?crs=EPSG:32648','block PS','memory')
    layer.dataProvider().addAttributes([QgsField('ps_key',QVariant.String),QgsField('Build_ID',QVariant.LongLong),
        QgsField('v_vertical',QVariant.Double),QgsField('coherence',QVariant.Double)])
    layer.updateFields();features=[];seen=set();actual={};case_counts=Counter()
    with sqlite3.connect('file:'+str(PS_SOURCE)+'?mode=ro&immutable=1',uri=True) as c:
        rows=c.execute('''SELECT p.source,p.ps_id,p.Build_ID,p.v_vertical,p.coh,p.geom
            FROM building_ps_points p JOIN rtree_building_ps_points_geom r ON r.id=p.fid
            WHERE r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=?''',
            (bounds.xMaximum(),bounds.xMinimum(),bounds.yMaximum(),bounds.yMinimum())).fetchall()
    for source,ps_id,bid,rate,coherence,blob in rows:
        geom=gpkg_geometry(blob);pt=geom.asPoint()
        if not bounds.contains(pt):continue
        key=f'{source}:{ps_id}';assert key not in seen;seen.add(key)
        assert -7<=rate<=1,'Observed rate outside the shared figure scale'
        f=QgsFeature(layer.fields());f.setAttributes([key,bid,rate,coherence]);f.setGeometry(geom);features.append(f)
        if bid in PAIR:
            case_counts[bid]+=1;actual[(bid,pt.x(),pt.y())]=(rate,coherence)
    assert case_counts=={39899:109,39929:57},case_counts
    for row in csv_rows(LATEST/'data/case_panel_PS_nodes.csv'):
        bid=int(row['Build_ID']);key=(bid,float(row['x']),float(row['y']))
        assert key in actual,key
        assert abs(actual[key][0]-float(row['observed_rate']))<1e-12
        assert abs(actual[key][1]-float(row['coherence']))<1e-12
    assert layer.dataProvider().addFeatures(features)[0];layer.updateExtents()
    write_layer(layer,CONTEXT_DB,'observed_block_PS')
    return {'source':str(PS_SOURCE),'source_scope':'All building-linked PS in the inset window',
        'unique_source_and_ps_id':len(features),'case_PS_counts':dict(case_counts),
        'context_PS_count':len(features)-sum(case_counts.values()),
        'shared_vertical_rate_scale_mm_per_yr':[-7,1],
        'observed_range_mm_per_yr':[min(f['v_vertical'] for f in features),max(f['v_vertical'] for f in features)],
        'interpolated_or_displaced':False,'case_nodes_match_latest_saved_diagnostics':True}


def ps_renderer(size,opacity,outline_width):
    ranges=[]
    for i in range(256):
        lo=-7+i/32;hi=-7+(i+1)/32;color=to_hex(colormaps['viridis']((i+.5)/256))
        symbol=QgsMarkerSymbol.createSimple({'name':'circle','color':color,'size':str(size),
            'outline_style':'solid' if outline_width else 'no','outline_color':'#FFFFFF',
            'outline_width':str(outline_width)})
        symbol.setOpacity(opacity);ranges.append(QgsRendererRange(lo,hi,symbol,f'{lo:.3f}–{hi:.3f}'))
    return QgsGraduatedSymbolRenderer('v_vertical',ranges)


def inset_rate_key(layout,x,y):
    """Small vector gradient key using the same Viridis scale as all PS panels."""
    stops=''.join(f'<stop offset="{i/16:.6f}" stop-color="{to_hex(colormaps["viridis"](i/16))}"/>' for i in range(17))
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="44mm" height="11.2mm" viewBox="0 0 44 11.2">
    <defs><linearGradient id="v">{stops}</linearGradient></defs>
    <g font-family="Arial" font-weight="700" font-size="2.645833" fill="#24282B">
    <text x="22" y="2.85" text-anchor="middle">Vertical rate (mm/yr)</text>
    <rect x="3" y="4.2" width="38" height="1.7" fill="url(#v)" stroke="#24282B" stroke-width="0.15"/>
    <path d="M3 5.9V6.6M22 5.9V6.6M41 5.9V6.6" stroke="#24282B" stroke-width="0.15"/>
    <text x="3" y="9.6" text-anchor="start">−7</text><text x="22" y="9.6" text-anchor="middle">−3</text>
    <text x="41" y="9.6" text-anchor="end">1</text></g></svg>'''
    path=WORK/'inset_PS_rate_key.svg';path.write_text(svg)
    item=QgsLayoutItemPicture(layout);item.setId(PREFIX+'inset_PS_colorbar');layout.addLayoutItem(item)
    item.setPicturePath(str(path));item.setResizeMode(QgsLayoutItemPicture.Zoom)
    item.attemptMove(QgsLayoutPoint(x,y));item.attemptResize(QgsLayoutSize(44,11.2))
    item.setBackgroundEnabled(False);item.setFrameEnabled(False);item.setZValue(75)


def case_annotation(layout,inset,feature,row,color,x,y,width):
    """Place compact native labels beside the footprint, leaving its PS visible."""
    bid=int(row['Build_ID']);height=25
    shape(layout,f'case_info_panel_{bid}',x,y,width,height,'0,0,0,0',color,.2,70)
    lines=[(f'{bid}  '+('M → H' if bid==39899 else 'M → M'),8.6,color),
        (f'IBSI {float(row["IBSI"]):.3f} | PS {row["PS_Count"]} | Q {float(row["Q_insar"]):.3f}',7.5,STROKE),
        (f'RMS {float(row["V_RMS"]):.3f} mm/yr',7.5,STROKE),
        (f'Tilt {float(row["Tilt_Angle"]):.6f}°/yr',7.5,STROKE),
        (f'DGI {float(row["DGI_Str"]):.3f} mm/(m yr)',7.5,STROKE),
        (f'Coh {float(row["PS_CohMn"]):.3f} | Coverage {float(row["PS_Cov"]):.3f}',7.5,STROKE)]
    for i,(value,size,text_color) in enumerate(lines):
        item=label(layout,f'case_info_{bid}_{i}',value,x+1.3,y+.8+i*3.85,width-2.6,3.7,size,color=text_color)
        style=item.textFormat();halo=style.buffer();halo.setEnabled(True);halo.setColor(QColor('#FFFFFF'))
        halo.setSize(.17);style.setBuffer(halo);item.setTextFormat(style)
    pt=page_xy(inset,feature.geometry().centroid().asPoint())
    anchor=QPointF(x,y+height-4.5) if pt.x()<x else QPointF(x+width,y+height*.6)
    extent=inset.extent();s=inset.sizeWithUnits()
    world=QgsPointXY(extent.xMinimum()+(anchor.x()-inset.pos().x())/s.width()*extent.width(),
                     extent.yMaximum()-(anchor.y()-inset.pos().y())/s.height()*extent.height())
    edge=feature.geometry().nearestPoint(QgsGeometry.fromPointXY(world)).asPoint()
    points=[page_xy(inset,edge),anchor]
    for stroke,line_width,z,id_ in [('#FFFFFF',.85,64,'halo'),(color,.35,65,'line')]:
        guide=add_guide(layout,points,stroke,line_width,z,f'case_info_{bid}_{id_}')
        guide.setId(PREFIX+f'case_info_connector_{bid}_{id_}')


def legend(layout):
    reference=layout.itemById('Earthquake_legend_label');symbol_x=layout.itemById('Earthquake_legend_symbol').sceneBoundingRect().center().x()
    for i,(id_,color,mark,value,source) in enumerate([
        ('upgraded',RED,'circle','Upgraded (2,391)','Earthquake_legend_symbol'),
        ('pair',LOCATOR_BLUE,'star','Matched pair','GNSS_legend_symbol')]):
        y=reference.pos().y()-(2-i)*5.5
        symbol=layout.itemById(source).symbol().clone()
        for j in range(symbol.symbolLayerCount()):
            props=symbol.symbolLayer(j).properties();props['name']=mark
            if j==symbol.symbolLayerCount()-1:
                props['color']=color
                if props.get('outline_style')!='no':props['outline_color']=color
            symbol.changeSymbolLayer(j,QgsSimpleMarkerSymbolLayer.create(props))
        if id_=='pair':symbol.setSize(5.2)
        item=QgsLayoutItemMarker(layout);item.setId(PREFIX+'legend_symbol_'+id_);item.setSymbol(symbol)
        item.setBackgroundEnabled(False);item.setFrameEnabled(False);layout.addLayoutItem(item)
        item.setReferencePoint(QgsLayoutItem.Middle);item.attemptMove(QgsLayoutPoint(symbol_x,y+2.5));item.setZValue(60)
        label(layout,'legend_label_'+id_,value,reference.pos().x(),y,34,5,7.4)


def heatmap(layout,main,inset,stats):
    matrix=stats['matrix'];x=inset.pos().x();y=inset.pos().y()+inset.sizeWithUnits().height()+4
    width=inset.sizeWithUnits().width();height=main.pos().y()+main.sizeWithUnits().height()-y
    shape(layout,'heatmap_panel',x,y,width,height,'#FFFFFF')
    label(layout,'heatmap_title','Frozen Static-only baseline',x+2,y+1,width-4,5.2,8.8)
    label(layout,'heatmap_sample','n = 40,000  |  counts and row %',x+2,y+6.2,width-4,3.3,7)
    gx=x+13.6;gy=y+12;cell=(width-15.6)/5
    for i in range(5):
        total=sum(matrix[i])
        for j in range(5):
            count=matrix[i][j];xx=gx+j*cell;yy=gy+i*cell
            color=to_hex(colormaps['Blues'](LogNorm(1,14000)(count))) if count else '#F4F5F6'
            shape(layout,f'heatmap_cell_{i}_{j}',xx,yy,cell,cell,color,'#FFFFFF',.18,40)
            content=f'{count:,}\n{100*count/total:.2f}%' if count else '0'
            label(layout,f'heatmap_value_{i}_{j}',content,xx+.2,yy+.5,cell-.4,cell-1,7.2,
                  color='#FFFFFF' if count>2000 else '#20272D',center=True)
    shape(layout,'heatmap_M_to_H',gx+3*cell,gy+2*cell,cell,cell,'0,0,0,0',RED,.5,55)
    for i,short in enumerate(['VL','L','M','H','VH']):
        label(layout,'heatmap_row_'+short,short,x+6.6,gy+i*cell,6.2,cell,7.5,center=True)
        label(layout,'heatmap_col_'+short,short,gx+i*cell,gy+5*cell+.3,cell,3.5,7.5,center=True)
    ylabel=label(layout,'heatmap_y_axis','Static-only baseline class',x+1.2,gy+(5*cell+38)/2,38,3.6,7.1,center=True)
    ylabel.setItemRotation(-90);ylabel.attemptMove(QgsLayoutPoint(x+1.2,gy+(5*cell+38)/2),False)
    label(layout,'heatmap_x_axis','InSAR-informed class',gx,gy+5*cell+3.7,5*cell,3.1,7.4,center=True)
    label(layout,'heatmap_overall','Unchanged 94.02%  |  Upgraded 5.98%',x+1,y+height-7.4,width-2,3.2,7,center=True)
    label(layout,'heatmap_down','Downgraded 0  |  Moderate → High 696',x+1,y+height-3.7,width-2,3,6.9,center=True)
    return {'matrix':matrix,'position_mm':[x,y],'size_mm':[width,height],'source':str(STATS),'classification':stats['protocol']}


def all_arial_bold(layout):
    for item in layout.items():
        if isinstance(item,(QgsLayoutItemLabel,QgsLayoutItemScaleBar)):
            item.setTextFormat(font_format(item.textFormat()))
        if isinstance(item,QgsLayoutItemMap):
            for grid in item.grids().asList():grid.setAnnotationTextFormat(font_format(grid.annotationTextFormat()))


def main():
    WORK.mkdir(exist_ok=True,parents=True)
    protected_files=list((LATEST/'data').glob('*'))+[LATEST/'QGIS/data/static_baseline_5_1.gpkg',BUILDINGS,ROADS,
        ROOT/'result/risk/scs_paper_method/building_risk.gpkg',ROOT/'result/intermediate/vulnerability_inputs/building_ps_points.gpkg']
    protected=[{'path':str(p),'sha256':digest(p)} for p in protected_files if p.is_file()]
    (WORK/'preservation_before.json').write_text(json.dumps(protected,ensure_ascii=False,indent=2)+'\n')
    stats=json.loads(STATS.read_text());rows=csv_rows(ALL);upgrades=csv_rows(CHANGED)
    assert stats['protocol']=='static_only_frozen_normalization_and_jenks'
    assert stats['normalization_or_Jenks_refitted_after_InSAR'] is False
    assert len(rows)==40000 and len(upgrades)==2391 and stats['pair_ids']==PAIR
    order=stats['class_order'];matrix=[[0]*5 for _ in range(5)]
    for r in rows:matrix[order.index(r['static_class'])][order.index(r['insar_class'])]+=1
    assert matrix==stats['matrix'] and matrix[2][3]==696
    assert Counter(r['change'] for r in rows)=={'Unchanged':37609,'Upgraded':2391}
    project=regional_cartography();layout=project.layoutManager().layouts()[0]
    layout.setName('01_Static_only_baseline_reference_composite')
    main_map=layout.itemById('Changed_building_points_map');extent=main_map.extent().toString(12)
    background=list(main_map.layers());shutil.copy2(LATEST/'QGIS/data/static_baseline_5_1.gpkg',DB)
    pair=add_layer(project,DB,'primary_pair_footprints','最新主配对 · 39899 / 39929')
    assert pair.featureCount()==2;values={int(f['Build_ID']):f for f in pair.getFeatures()};assert set(values)==set(PAIR)
    pair.setRenderer(QgsCategorizedSymbolRenderer('Build_ID',[
        QgsRendererCategory(39899,fill('0,0,0,0',RED,.65),'39899 · M → H'),
        QgsRendererCategory(39929,fill('0,0,0,0',BLUE,.65),'39929 · M → M')]))
    centers=[values[b].geometry().centroid().asPoint() for b in PAIR]
    center=QgsPointXY(sum(p.x() for p in centers)/2,sum(p.y() for p in centers)/2)
    mean=QgsVectorLayer('Point?crs=EPSG:32648','pair center','memory')
    mean.dataProvider().addAttributes([QgsField('case_ids',QVariant.String)]);mean.updateFields()
    f=QgsFeature(mean.fields());f.setAttributes(['39899 / 39929']);f.setGeometry(QgsGeometry.fromPointXY(center))
    mean.dataProvider().addFeatures([f]);write_layer(mean,DB,'matched_pair_location')
    pair_point=add_layer(project,DB,'matched_pair_location','最新配对位置 · Matched pair')
    locator=marker(LOCATOR_BLUE,4.0,1,'star');locator.symbolLayer(0).setStrokeWidth(.28)
    pair_point.setRenderer(QgsSingleSymbolRenderer(locator))
    upgraded=add_layer(project,DB,'upgraded_building_points','最新升档建筑 · Frozen Static-only (2,391)')
    assert upgraded.featureCount()==2391;upgraded.setRenderer(QgsSingleSymbolRenderer(marker(RED,.62,.78)))
    main_map.setLayers([pair_point,upgraded]+background);main_map.setKeepLayerSet(True);main_map.setKeepLayerStyles(False)
    main_map.setLayerStyleOverrides({});main_map.setFollowVisibilityPreset(False);main_map.setExtent(QgsRectangle(*[float(v) for v in extent.replace(' : ',',').split(',')]))
    main_map.setFrameStrokeWidth(QgsLayoutMeasurement(.45));main_map.setFrameStrokeColor(QColor(STROKE))
    legend(layout)

    bounds=QgsRectangle(center.x()-150,center.y()-170,center.x()+150,center.y()+170)
    n_context,n_roads=context_copy(project,bounds)
    ps_record=ps_context_copy(bounds)
    context=add_layer(project,CONTEXT_DB,'block_buildings','最新街区白模 · 背景建筑')
    assert context.setSubsetString('"Build_ID" NOT IN (39899,39929)')
    context.setRenderer(QgsSingleSymbolRenderer(fill('#FCFCFC','#BBC5CC',.14)))
    roads=add_layer(project,CONTEXT_DB,'block_roads','最新街区 · 道路与步道')
    roads.setRenderer(QgsCategorizedSymbolRenderer('kind',[
        QgsRendererCategory(kind,QgsLineSymbol.createSimple({'line_color':'#D3DADF','line_width':str(width),'line_style':style}),kind)
        for kind,width,style in [('service',.5,'solid'),('residential',.58,'solid'),('unclassified',.5,'solid'),('footway',.25,'dash'),('steps',.25,'dash')]]))
    roofs=add_layer(project,DB,'primary_pair_footprints','案例建筑 · 白模填充')
    roofs.setRenderer(QgsSingleSymbolRenderer(fill('#FFFFFF','#FFFFFF',0)))
    context_ps=add_layer(project,CONTEXT_DB,'observed_block_PS','街区形变PS · 背景观测')
    assert context_ps.setSubsetString('"Build_ID" NOT IN (39899,39929)')
    context_ps.setRenderer(ps_renderer(.52,.48,.06))
    case_ps=add_layer(project,CONTEXT_DB,'observed_block_PS','主配对形变PS · 109 / 57')
    assert case_ps.setSubsetString('"Build_ID" IN (39899,39929)')
    assert case_ps.featureCount()==166
    case_ps.setRenderer(ps_renderer(.95,1,.11))
    inset=QgsLayoutItemMap(layout);inset.setId(PREFIX+'pair_map');layout.addLayoutItem(inset)
    ix=main_map.pos().x()+main_map.sizeWithUnits().width()+4
    inset.attemptMove(QgsLayoutPoint(ix,8.5));inset.attemptResize(QgsLayoutSize(82,82*340/300))
    inset.setCrs(pair.crs());inset.setLayers([pair,case_ps,context_ps,roofs,context,roads]);inset.setKeepLayerSet(True);inset.setKeepLayerStyles(False)
    inset.setExtent(bounds);inset.setBackgroundEnabled(True);inset.setBackgroundColor(QColor('#EDF0F2'))
    inset.setFrameEnabled(True);inset.setFrameStrokeWidth(main_map.frameStrokeWidth());inset.setFrameStrokeColor(main_map.frameStrokeColor());inset.setZValue(30)
    label(layout,'pair_title','Dianchi resort block',ix,.6,82,5.5,8.8)
    case_rows={int(r['Build_ID']):r for r in csv_rows(LATEST/'data/primary_pair_reassessment.csv')}
    case_annotation(layout,inset,values[39929],case_rows[39929],BLUE,ix+29,11.5,50)
    case_annotation(layout,inset,values[39899],case_rows[39899],RED,ix+3,52.5,48)
    inset_rate_key(layout,ix+35,87)
    scale=QgsLayoutItemScaleBar(layout);scale.setId(PREFIX+'pair_scale');scale.setStyle('Line Ticks Up');scale.setLinkedMap(inset)
    scale.setUnits(Qgis.DistanceUnit.Meters);scale.setUnitsPerSegment(25);scale.setNumberOfSegments(2);scale.setNumberOfSegmentsLeft(0)
    scale.setUnitLabel('m');scale.setHeight(.8);scale.setBoxContentSpace(0);scale.setLabelBarSpace(.7)
    scale.setTextFormat(layout.itemById('Overview_scale').textFormat());scale.setBackgroundEnabled(False);scale.setFrameEnabled(False)
    layout.addLayoutItem(scale);scale.attemptMove(QgsLayoutPoint(ix+3,92));scale.setZValue(60)
    north=QgsLayoutItemPicture(layout);north.setId(PREFIX+'pair_north');layout.addLayoutItem(north)
    north.setPicturePath(str(ROOT/'plot/shared/styles/Kunming_Indicator_Framework_Distribution/symbols/north_arrow.svg'))
    north.attemptMove(QgsLayoutPoint(ix+5,17.5));north.attemptResize(QgsLayoutSize(3.4,5.6));north.setZValue(60)
    label(layout,'pair_N','N',ix+4.4,13,5,4,7.5)
    to_map=QgsCoordinateTransform(pair.crs(),main_map.crs(),project);anchor=page_xy(main_map,to_map.transform(center))
    baiyi=layout.itemById('Fault_Baiyi').sceneBoundingRect();guandu=layout.itemById('Guandu').sceneBoundingRect()
    guide_y=(baiyi.bottom()+guandu.top())/2
    wuhua=layout.itemById('Wuhua').sceneBoundingRect();panlong=layout.itemById('Panlong').sceneBoundingRect()
    bend_x=(wuhua.right()+panlong.left())/2
    dx,dy=bend_x-anchor.x(),guide_y-anchor.y();length=(dx*dx+dy*dy)**.5
    points=[QPointF(anchor.x()+2.3*dx/length,anchor.y()+2.3*dy/length),QPointF(bend_x,guide_y),QPointF(ix,guide_y)]
    for color,width,z,id_ in [('#FFFFFF',1.1,24,'latest_guide_halo'),(LOCATOR_BLUE,.6,25,'latest_guide')]:
        guide=add_guide(layout,points,color,width,z,id_);guide.setId(PREFIX+id_)
    heatmap_record=heatmap(layout,main_map,inset,stats)

    strip_record=json.loads((WORK/'case_strip_manifest.json').read_text())
    assert strip_record['building_ids']==PAIR
    strip=QgsLayoutItemPicture(layout);strip.setId(PREFIX+'case_strip');layout.addLayoutItem(strip)
    strip.setPicturePath(str(WORK/'latest_case_strip.svg'))
    # Use the authored SVG's physical dimensions directly. Zoom relies on Qt's
    # rounded intrinsic pixel size and can leave the visible right edge inset.
    strip.setResizeMode(QgsLayoutItemPicture.Stretch)
    strip_x=main_map.pos().x()-strip_record['frame_grid_left_mm']
    strip_y=main_map.pos().y()+main_map.sizeWithUnits().height()+4-strip_record['frame_grid_top_mm']
    strip.attemptMove(QgsLayoutPoint(strip_x,strip_y));strip.attemptResize(QgsLayoutSize(strip_record['width_mm'],strip_record['height_mm']))
    strip.setBackgroundEnabled(False);strip.setFrameEnabled(False);strip.setZValue(40)
    page_w=ix+82+5;page_h=strip_y+strip_record['height_mm']+3
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(page_w,page_h))
    all_arial_bold(layout)
    tree=project.layerTreeRoot();main_layers=main_map.layers()
    inset_layers=[pair,case_ps,context_ps,roofs,context,roads]
    for title,layers,visible in [('固定Static-only基准 · 最新结果',[upgraded,pair_point],True),('39899 / 39929 · 白模与PS放大图',inset_layers,False)]:
        group=tree.insertGroup(0,title)
        for layer in layers:
            node=tree.findLayer(layer.id());group.addChildNode(node.clone());node.parent().removeChildNode(node)
        group.setItemVisibilityChecked(visible);group.setExpanded(False)
        for node in group.findLayers():node.setExpanded(False)
    visible={l.id() for l in main_layers}
    for node in tree.findLayers():node.setItemVisibilityChecked(node.layerId() in visible)
    tree.setHasCustomLayerOrder(True);tree.setCustomLayerOrder(main_layers+inset_layers)
    project.setTitle('5.1 Frozen Static-only baseline · current cases 39899 / 39929')
    project.setCustomVariables({'current_protocol':stats['protocol'],'primary_pair_ids':'39899 / 39929','upgraded_n':2391,'downgraded_n':0})
    meta=project.metadata();meta.setTitle('Frozen Static-only baseline: current changes and matched PS cases')
    meta.setAbstract('Current fixed Static-only normalization and Jenks boundaries. 2,391 upgrades, 37,609 unchanged, 0 downgrades. Current matched pair39899/39929. Original independent-Jenks thematic layers removed. Source data unmodified.')
    project.setMetadata(meta);project.setCrs(main_map.crs());project.setFilePathStorage(Qgis.FilePathType.Relative);layout.setReferenceMap(main_map)
    save_and_export(project,layout)
    checked_project=QgsProject();assert checked_project.read(str(PROJECT));assert all(l.isValid() for l in checked_project.mapLayers().values())
    checked=checked_project.layoutManager().layouts()[0];checked_main=checked.itemById('Changed_building_points_map')
    assert checked_main.extent().toString(12)==extent
    assert len([x for x in checked.items() if isinstance(x,QgsLayoutItemMap)])==2
    assert all('changed_building_points_1542.gpkg' not in l.source() for l in checked_project.mapLayers().values())
    checked_inset=checked.itemById(PREFIX+'pair_map')
    checked_strip=checked.itemById(PREFIX+'case_strip')
    panels=strip_record['axes'];first=panels[0]['rect_mm_from_bottom_left'];last=panels[-1]['rect_mm_from_bottom_left']
    assert abs(checked_strip.pos().x()+first[0]-checked_main.pos().x())<.001
    assert abs(checked_strip.pos().x()+last[0]+last[2]-checked_inset.pos().x()-checked_inset.sizeWithUnits().width())<.001
    for a,b in zip(panels,panels[1:]):
        ra,rb=a['rect_mm_from_bottom_left'],b['rect_mm_from_bottom_left']
        assert abs(rb[0]-ra[0]-ra[2]-4)<.001 and ra[1:]==rb[1:]
    assert len(checked_inset.layers())==6
    assert checked.itemById(PREFIX+'inset_PS_colorbar') is not None
    assert sum(l.featureCount() for l in checked_inset.layers() if l.source().find('layername=observed_block_PS')!=-1)==828
    for item in checked.items():
        if isinstance(item,(QgsLayoutItemLabel,QgsLayoutItemScaleBar)):
            font=item.textFormat().font();assert font.family()=='Arial' and font.bold(),item.id()
    source_by_id={int(r['Build_ID']):r for r in upgrades};clipped=[];trans=QgsCoordinateTransform(upgraded.crs(),main_map.crs(),project)
    for f in upgraded.getFeatures():
        r=source_by_id[int(f['Build_ID'])];p=f.geometry().asPoint()
        assert abs(p.x()-float(r['centroid_x_utm48n_m']))<1e-7 and abs(p.y()-float(r['centroid_y_utm48n_m']))<1e-7
        assert f['static_class']==r['static_class'] and f['insar_class']==r['insar_class']
        if not main_map.extent().contains(trans.transform(p)):clipped.append(int(f['Build_ID']))
    assert all(digest(x['path'])==x['sha256'] for x in protected),'Source data changed'
    record={'protocol':stats['protocol'],'sample_n':40000,'upgraded_n':2391,'unchanged_n':37609,'downgraded_n':0,
        'moderate_to_high_n':696,'pair_ids':PAIR,'pair_distance_m':stats['primary_pair_distance_m'],
        'main_map_extent':extent,'main_map_extent_unchanged':True,'visible_upgraded_points':2391-len(clipped),
        'frame_clipped_ids':clipped,'point_displacement_or_sampling':False,'heatmap':heatmap_record,
        'context_buildings':n_context,'context_roads':n_roads,'block_extent':bounds.toString(12),
        'inset_observed_PS':ps_record,'inset_case_metrics':'Native on-map information panels with footprint connectors',
        'inset_information_background':'transparent',
        'fonts':'Arial bold throughout','main_map_frame_width_mm':.45,'inset_frame_width_mm':.45,
        'frame_alignment':'Bottom row outer edges align with main map and right inset; four equal frames, 4 mm gaps',
        'pair_locator_symbol':{'shape':'star','color':LOCATOR_BLUE,'size_mm':4.0,'legend_size_mm':5.2},
        'regional_guide':{'color':LOCATOR_BLUE,'width_mm':.6,'white_halo_width_mm':1.1},
        'case_strip':strip_record,'page_mm':[page_w,page_h],'preserved_source_files':len(protected),
        'project':str(PROJECT),'template':str(TEMPLATE),'png':str(FIGURE)+'.png','svg':str(FIGURE)+'.svg','dpi':600}
    (WORK/'composite_manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(record,ensure_ascii=False),flush=True);os._exit(0)


if __name__=='__main__':
    app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    main()
