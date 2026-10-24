"""Add editable transects to a copy of the existing final-risk QGIS layout."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from qgis.core import *
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QPolygonF

ROOT = Path(__file__).resolve().parents[4]
QGIS_ROOT = ROOT / "plot"
SOURCE_PROJECT = QGIS_ROOT / "10_risk_transects/qgis/projects/10_risk_base.qgz"
PROJECT = QGIS_ROOT / "10_risk_transects/qgis/projects/10_risk_transects.qgz"
CONFIG = ROOT / "plot/10_risk_transects/code/transect_config.json"
DATA = ROOT / "result/statistics/Risk/transect"
OUT = QGIS_ROOT / "10_risk_transects/output/qgis/risk_transect"
TEMPLATES = QGIS_ROOT / "10_risk_transects/qgis/layouts/risk_transect"
TEAL = "#006d77"


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def canonical_style(xml):
    """XML attribute order can change on a QGIS save/reload; values must not."""
    def node(element):
        return (element.tag,tuple(sorted(element.attrib.items())),(element.text or '').strip(),
                tuple(node(child) for child in element))
    return node(ET.fromstring(xml))


def item_snapshot(item):
    result = {"id":item.id(),"position":[item.pos().x(),item.pos().y()],
              "size":[item.sizeWithUnits().width(),item.sizeWithUnits().height()],
              "rotation":item.itemRotation(),"z":item.zValue(),"visible":item.isVisible()}
    if isinstance(item,QgsLayoutItemLabel):
        fmt=item.textFormat()
        result.update(text=item.text(),font=fmt.font().toString(),size_pt=fmt.size(),color=fmt.color().name())
    return result


def add_label(layout,id_,text,position,box,size,color=TEAL):
    label=QgsLayoutItemLabel(layout);label.setId(id_);label.setText(text);label.setMargin(0)
    fmt=QgsTextFormat();font=QFont("Arial");font.setBold(True);font.setPointSizeF(size)
    fmt.setFont(font);fmt.setSize(size);fmt.setColor(QColor(color))
    halo=QgsTextBufferSettings();halo.setEnabled(True);halo.setSize(.4);halo.setColor(QColor("white"));fmt.setBuffer(halo)
    label.setTextFormat(fmt);label.setBackgroundEnabled(False)
    label.setVAlign(Qt.AlignVCenter);label.setHAlign(Qt.AlignLeft)
    layout.addLayoutItem(label);label.attemptMove(QgsLayoutPoint(*position));label.attemptResize(QgsLayoutSize(*box));label.setZValue(12)
    return label


def add_transect(project, layout, map_item, config, folder):
    code=config['id'];name=f'{code[0]}-{code[1]}';color=config.get('color',TEAL)
    route=QgsVectorLayer(str(folder/'risk_transect.gpkg')+f'|layername=transect_{code}',f'Transect {name}','ogr')
    buffer=QgsVectorLayer(str(folder/'risk_transect.gpkg')+f"|layername=corridor_{config['half_width_m']}m",
                         f"Buffer {name}: {config['half_width_m']/1000:g} km each side",'ogr')
    assert route.isValid() and buffer.isValid() and route.featureCount()==buffer.featureCount()==1
    line=next(route.getFeatures()).geometry();length=line.length()
    check_geom=QgsGeometry.fromPolylineXY([QgsPointXY(*xy) for xy in config['vertices_wgs84']])
    check_geom.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),route.crs(),project))
    assert check_geom.hausdorffDistance(line)<.001
    symbol=QgsLineSymbol.createSimple({'line_color':'white','line_width':'.75','line_width_unit':'MM','capstyle':'round','joinstyle':'round'})
    symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({'line_color':color,'line_width':'.38','line_width_unit':'MM','capstyle':'round','joinstyle':'round'}))
    route.setRenderer(QgsSingleSymbolRenderer(symbol));route.setLabelsEnabled(False)
    buffer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'style':'no','color':'0,0,0,0',
        'outline_color':color,'outline_style':'dash','outline_width':'.18','outline_width_unit':'MM','joinstyle':'round'})))
    buffer.setLabelsEnabled(False)
    memory=QgsVectorLayer(f'Point?crs={route.crs().authid()}&field=chainage_km:double&field=label:string','Stations','memory')
    features=[];rows=[];extent=map_item.extent();box=map_item.sizeWithUnits();position=map_item.pos()
    transform=QgsCoordinateTransform(route.crs(),map_item.crs(),project)
    interval=config.get('station_interval_m',10000)
    for distance in [0,*range(interval,int(length),interval),length]:
        geom=line.interpolate(distance)
        text=code[0] if distance==0 else code[1] if distance==length else f'{distance/1000:g} km'
        feature=QgsFeature(memory.fields());feature.setGeometry(geom);feature.setAttributes([distance/1000,text]);features.append(feature)
        point=transform.transform(QgsPointXY(geom.asPoint()))
        x=position.x()+(point.x()-extent.xMinimum())/extent.width()*box.width()
        y=position.y()+(extent.yMaximum()-point.y())/extent.height()*box.height()
        assert position.x()<x<position.x()+box.width() and position.y()<y<position.y()+box.height()
        endpoint=distance in (0,length)
        default=(-6.5,-7) if distance==0 else (2,-2) if distance==length else (2,-4)
        dx,dy=config.get('label_offsets_mm',{}).get(text,default)
        add_label(layout,f'Transect_{code}_station_'+text.replace(' ','_'),text,(x+dx,y+dy),
                  (7,6) if endpoint else (16,6),12 if endpoint else 9.5,color)
        rows.append({'transect':code,'chainage_km':distance/1000,'label':text,'page_mm':[x,y]})
    assert memory.dataProvider().addFeatures(features)[0];memory.updateExtents()
    options=QgsVectorFileWriter.SaveVectorOptions();options.driverName='GPKG';options.layerName='transect_stations'
    options.actionOnExistingFile=QgsVectorFileWriter.CreateOrOverwriteFile
    station_path=folder/'station_markers.gpkg'
    result=QgsVectorFileWriter.writeAsVectorFormatV3(memory,str(station_path),project.transformContext(),options)
    assert result[0]==QgsVectorFileWriter.NoError,result
    stations=QgsVectorLayer(str(station_path)+'|layername=transect_stations',f'Distance markers {name}','ogr');assert stations.isValid()
    stations.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({'name':'circle','size':'2.1','size_unit':'MM',
        'color':color,'outline_color':'white','outline_width':'.25','outline_width_unit':'MM'})))
    stations.setLabelsEnabled(False)
    return [stations,route,buffer],rows


def main():
    OUT.mkdir(parents=True,exist_ok=True);TEMPLATES.mkdir(parents=True,exist_ok=True)
    config=json.loads(CONFIG.read_text())
    route_configs=[(dict(config,id='AB',color=TEAL),DATA)]
    route_configs += [(dict(config,**extra),DATA/extra['id']) for extra in config.get('additional_transects',[])]
    codes=[cfg['id'] for cfg,_ in route_configs]
    layout_name='Kunming_Risk_Transects_'+'_'.join(codes) if len(codes)>1 else 'Kunming_Risk_Transect_AB'
    stem=layout_name+'_Map'
    protected=[SOURCE_PROJECT,ROOT/'plot/10_risk_transects/output/qgis/map_sources/Kunming_Final_Building_Risk_1200dpi.png',
               ROOT/'result/risk/scs_paper_method/building_risk.gpkg',DATA/'segment_statistics.csv',
               DATA/'building_allocation.csv',DATA/'buffer_width_sensitivity.csv',DATA/'risk_transect.gpkg']
    protected += [folder/name for _,folder in route_configs[1:] for name in ['segment_statistics.csv','building_allocation.csv','buffer_width_sensitivity.csv','risk_transect.gpkg']]
    hashes={str(p):digest(p) for p in protected}
    project=QgsProject();assert project.read(str(SOURCE_PROJECT))
    layout=project.layoutManager().layoutByName('Kunming_Final_Risk');assert layout
    map_item=layout.itemById('Risk_Main_Map');assert map_item
    original_items=[i for i in layout.items() if isinstance(i,QgsLayoutItem) and i.id()]
    before={i.id():item_snapshot(i) for i in original_items}
    base_layers=list(map_item.layers());base_styles=dict(map_item.layerStyleOverrides())
    extent=QgsRectangle(map_item.extent());box=map_item.sizeWithUnits();position=map_item.pos()
    assert len(base_layers)==9 and all(layer.isValid() for layer in base_layers)
    risk_layer=next(layer for layer in base_layers if isinstance(layer,QgsVectorLayer)
                    and 'Risk_Final' in layer.fields().names())
    risk_style_layer=risk_layer.clone()
    QgsMapLayerStyle(base_styles[risk_layer.id()]).writeToLayer(risk_style_layer)
    risk_class_colors={rule.label():rule.symbol().color().name()
                       for rule in risk_style_layer.renderer().rootRule().children() if rule.symbol()}
    assert len(risk_class_colors)==5
    assert [layout.itemById(f'Legend_class_{i}').symbol().color().name() for i in range(5)]==list(risk_class_colors.values())
    # Retain the original outside latitude annotations; the composer reserves
    # a narrow gap between them and the left analysis column.
    grid=map_item.grid();grid.setAnnotationPosition(grid.OutsideMapFrame,grid.Left)

    new_layers=[];station_rows=[];styles=dict(base_styles)
    for route_config,folder in route_configs:
        layers,rows=add_transect(project,layout,map_item,route_config,folder)
        new_layers.extend(layers);station_rows.extend(rows)
    for layer in new_layers:
        layer.setScaleBasedVisibility(False);project.addMapLayer(layer)
        style=QgsMapLayerStyle();style.readFromLayer(layer);styles[layer.id()]=style.xmlData()
        layer.saveNamedStyle(str(TEMPLATES/(layer.name().replace(' ','_').replace(':','')+'.qml')))
    map_item.setLayers(new_layers+base_layers);map_item.setKeepLayerSet(True);map_item.setKeepLayerStyles(True)
    map_item.setLayerStyleOverrides(styles)
    tree=project.layerTreeRoot();tree.setHasCustomLayerOrder(True)
    old_ids={l.id() for l in new_layers+base_layers}
    tree.setCustomLayerOrder(new_layers+base_layers+[l for l in project.mapLayers().values() if l.id() not in old_ids])

    # Keep map features and styles fixed; collect all keys below the map.
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(195,232))
    legend_moves={
        'Earthquake_legend_symbol':(17.357416666666667,222.85741666666667),
        'Earthquake_legend_label':(24,222),
        'GNSS_legend_symbol':(62.609416666666666,222.10941666666668),
        'GNSS_legend_label':(71,222),
        'Fault_legend_symbol':(110,224.5),'Fault_legend_label':(121,222),
        'Left_lateral_legend_symbol':(146,224.5),'Left_lateral_legend_label':(158.5,222),
    }
    for item_id,position_mm in legend_moves.items():
        layout.itemById(item_id).attemptMove(QgsLayoutPoint(*position_mm),False)
    for index,(route_config,_) in enumerate(route_configs):
        y=213;left=16+52*index;code=route_config['id'];color=route_config['color']
        symbol=QgsLineSymbol.createSimple({'line_color':color,'line_width':'.38','line_width_unit':'MM'})
        item=QgsLayoutItemPolyline(QPolygonF([QPointF(0,0),QPointF(8,0)]),layout)
        item.setId('Transect_key_'+code);item.setSymbol(symbol);layout.addLayoutItem(item)
        item.attemptMove(QgsLayoutPoint(left,y+2.6));item.setZValue(12)
        add_label(layout,'Transect_key_label_'+code,f'Transect {code[0]}-{code[1]}',(left+11,y),(35,5.2),9,color)
    y=213
    for index,(route_config,_) in enumerate(route_configs):
        symbol=QgsLineSymbol.createSimple({'line_color':route_config['color'],'line_width':'.18','line_width_unit':'MM','line_style':'dash'})
        item=QgsLayoutItemPolyline(QPolygonF([QPointF(0,0),QPointF(3.5,0)]),layout)
        item.setId('Transect_buffer_key_'+route_config['id']);item.setSymbol(symbol);layout.addLayoutItem(item)
        item.attemptMove(QgsLayoutPoint(127+4.5*index,y+2.6));item.setZValue(12)
    add_label(layout,'Transect_buffer_key_label',f"Buffers: {config['half_width_m']/1000:g} km / side",(139,y),(40,5.2),9,'#24282b')

    # Only the authorized legend positions change. All other item properties,
    # original layer styles and geographic map extent must be preserved.
    after={i.id():item_snapshot(i) for i in original_items}
    for item_id,original in before.items():
        expected=dict(original)
        if item_id in legend_moves:expected['position']=list(legend_moves[item_id])
        assert after[item_id]==expected,(item_id,after[item_id],expected)
    assert all(map_item.layerStyleOverrides()[key]==value for key,value in base_styles.items())
    assert map_item.extent().toString(12)==extent.toString(12)
    layout.setName(layout_name);project.setTitle('Kunming risk transects '+', '.join(codes)+' - original map styling')
    project.setFileName(str(PROJECT));assert project.write()
    context=QgsReadWriteContext();context.setPathResolver(QgsPathResolver(str(TEMPLATES/(layout_name+'.qpt'))))
    assert layout.saveAsTemplate(str(TEMPLATES/(layout_name+'.qpt')),context)
    layout.refresh();exporter=QgsLayoutExporter(layout)
    for dpi,suffix in [(1200,'1200dpi'),(200,'preview')]:
        settings=QgsLayoutExporter.ImageExportSettings();settings.dpi=dpi
        assert exporter.exportToImage(str(OUT/f'{stem}_{suffix}.png'),settings)==QgsLayoutExporter.Success
    restored=QgsProject();assert restored.read(str(PROJECT))
    restored_layout=restored.layoutManager().layoutByName(layout_name);assert restored_layout
    restored_map=restored_layout.itemById('Risk_Main_Map')
    assert restored_map.extent().toString(12)==extent.toString(12)
    assert restored_map.grid().annotationPosition(grid.Left)==grid.OutsideMapFrame
    assert len(restored_map.layers())==len(base_layers)+len(new_layers) and all(l.isValid() for l in restored_map.layers())
    assert all(canonical_style(restored_map.layerStyleOverrides()[key])==canonical_style(value)
               for key,value in base_styles.items())
    assert all(digest(p)==hashes[str(p)] for p in protected)
    from qgis_paths import map_source_path
    target=map_source_path(f'{stem}_1200dpi.png');shutil.copy2(OUT/f'{stem}_1200dpi.png',target)
    report={'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'source_project':str(SOURCE_PROJECT),
            'project':str(PROJECT),'layout':layout.name(),'config_sha256':digest(CONFIG),
            'png':str(OUT/f'{stem}_1200dpi.png'),'preview':str(OUT/f'{stem}_preview.png'),'published_map':str(target),
            'page_mm':[195,232],'legend_position':'all legends below map',
            'risk_class_colors':risk_class_colors,'left_graticule_annotation_position':'outside map frame',
            'relocated_context_legend_items':legend_moves,
            'map_crs':map_item.crs().authid(),'map_extent':extent.toString(12),
            'transects':[{'id':cfg['id'],'color':cfg['color'],'data_dir':str(folder),'vertices_wgs84':cfg['vertices_wgs84']} for cfg,folder in route_configs],
            'original_item_count':len(before),'original_layout_items':before,'station_positions':station_rows,
            'checks':{'original_layout_items_preserved_except_legend_positions':True,'original_map_extent_unchanged':True,
                      'original_outside_latitude_annotations_preserved':True,'risk_legend_matches_map_renderer':True,
                      'original_layer_style_overrides_unchanged':True,'project_reload_and_layers_valid':True,
                      'risk_statistics_unchanged':True,'source_files_unchanged':True},
            'protected_sha256':hashes,'buffer_fill':False,'source_map_restyled':False}
    (OUT/'qgis_transect_map_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['project','png','preview','checks']},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    main()
    os._exit(0)
