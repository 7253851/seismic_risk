"""Map SCS vulnerability and exposure with the current H/V/E/R figure design."""
from qgis_paths import export_path, layout_directory, project_path
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import csv,hashlib,json,os
import numpy as np
from qgis.core import *
from qgis_paths import ROOT,EXPORTS
from draw_hazard_streets import save_project
from revise_hazard_layout import map_polygon
from map_series_support import magnitude_notation,export_layout,save_template
from recolor_vulnerability_map import apply_palette

BASE=ROOT/'10_risk_transects/qgis/projects/10_risk_base.qgz'
CLASSES=['Very Low','Low','Moderate','High','Very High']
CONFIGS=[
    dict(key='vulnerability',title='Vulnerability',legend='Vul. level',table='building_comprehensive_vulnerability',
         file=ROOT/'../result/vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg',
         field='Vul_Index',class_field='Vul_Class',expected=41939),
    dict(key='exposure',title='Exposure',legend='Exp. level',table='building_exposure_scs',
         file=ROOT/'../result/exposure/scs_paper_method/building_exposure.gpkg',
         field='Exp_Final',class_field='Exposure_Class',expected=53513),
]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantile_jenks(values,k=5):
    # Compatibility wrapper: one implementation across calculation and maps.
    import sys
    script_root=ROOT.parent/'project/code'
    if str(script_root) not in sys.path:sys.path.insert(0,str(script_root))
    from classification import jenks_breaks
    return jenks_breaks(values,k)


def draw(config):
    key,title=config['key'],config['title']
    out=export_path(key);out.mkdir(parents=True,exist_ok=True)
    target=project_path('seismic_building_'+key+'.qgz')
    template=layout_directory(key)/('Kunming_'+title+'.qpt')
    protected={str(path):digest(path) for path in [BASE,config['file']]}
    project=QgsProject();assert project.read(str(BASE))
    layout=project.layoutManager().layoutByName('Kunming_Final_Risk');assert layout
    main=layout.itemById('Risk_Main_Map');extent=QgsRectangle(main.extent())
    ordered=main.layers();overrides=main.layerStyleOverrides()
    old=next(layer for layer in ordered if layer.customProperty('seismic_building/result_key','')=='risk')
    source_style=old.clone();QgsMapLayerStyle(overrides[old.id()]).writeToLayer(source_style)
    renderer=source_style.renderer().clone()
    layer=next(layer for layer in project.mapLayers().values() if layer.customProperty('seismic_building/result_key','')==key)
    layer.setDataSource(str(config['file'])+'|layername='+config['table'],'建筑'+('易损性' if key=='vulnerability' else '暴露性')+' · SCS 五级','ogr')
    assert layer.isValid() and layer.featureCount()==config['expected'] and not layer.subsetString()
    values=np.array([float(feature[config['field']]) for feature in layer.getFeatures(QgsFeatureRequest().setSubsetOfAttributes([config['field']],layer.fields()).setFlags(QgsFeatureRequest.NoGeometry))])
    assert np.isfinite(values).all() and values.min()>=0 and values.max()<=1
    if key=='vulnerability':
        manifest=json.loads((config['file'].parent/'run_manifest.json').read_text())
        breaks=manifest['jenks_breaks'];method='Existing Vul_Class and source Jenks breaks preserved'
    else:
        manifest=json.loads((config['file'].parent/'run_manifest.json').read_text());breaks=manifest['jenks_breaks'];method='Shared five-class Jenks and stored Exposure_Class, identical to statistical figures'
    if key=='vulnerability':apply_palette(renderer,layout)
    settings=[]
    for index,(rule,name) in enumerate(zip(renderer.rootRule().children(),CLASSES)):
        if config['class_field']:
            expression='"'+config['class_field']+'" = '+"'"+name+"'"
        else:
            field='"'+config['field']+'"'
            expression=field+' <= '+repr(breaks[index+1]) if index==0 else field+' > '+repr(breaks[index])+' AND '+field+' <= '+repr(breaks[index+1])
        rule.setFilterExpression(expression);rule.setLabel(name)
        settings.append(dict(name=name,expression=expression,color=rule.symbol().color().name(),lower=breaks[index],upper=breaks[index+1]))
    layer.setRenderer(renderer);layer.setLabelsEnabled(False);layer.setOpacity(1);layer.setScaleBasedVisibility(False)
    simplify=QgsVectorSimplifyMethod();simplify.setSimplifyHints(Qgis.VectorRenderingSimplificationFlag.NoSimplification);layer.setSimplifyMethod(simplify)
    style=QgsMapLayerStyle();style.readFromLayer(layer)
    overrides.pop(old.id());overrides[layer.id()]=style.xmlData()
    ordered=[layer if item.id()==old.id() else item for item in ordered]
    main.setLayers(ordered);main.setLayerStyleOverrides(overrides);main.setId(title+'_Main_Map')
    layout.setName('Kunming_'+title);layout.setCustomProperty('seismic_building/result','SCS_'+key)
    project.setTitle('Kunming building '+key+' - SCS five classes')
    layout.itemById('Legend_title').setText(config['legend'])
    for index,name in enumerate(CLASSES):layout.itemById('Legend_range_'+str(index)).setText(name)
    events=magnitude_notation(layout)
    root=project.layerTreeRoot()
    for node in root.findLayers():node.setItemVisibilityChecked(node.layerId() in overrides)
    for item in ordered:
        node=root.findLayer(item.id())
        while node and node is not root:node.setItemVisibilityChecked(True);node=node.parent()
    root.setHasCustomLayerOrder(True);root.setCustomLayerOrder(ordered+[item for item in project.mapLayers().values() if item.id() not in overrides])
    clip=map_polygon(extent,main.crs(),layer.crs(),project)
    clip_engine=QgsGeometry.createGeometryEngine(clip.constGet());clip_engine.prepareGeometry()
    counties=ordered[4];assert counties.featureCount()==5
    cg=next(feature.geometry() for feature in counties.getFeatures() if feature['name']=='呈贡区')
    cg.transform(QgsCoordinateTransform(counties.crs(),layer.crs(),project));cg_engine=QgsGeometry.createGeometryEngine(cg.constGet());cg_engine.prepareGeometry()
    full,visible=Counter(),Counter();cg_full=cg_visible=0
    attributes=[config['field']]+([config['class_field']] if config['class_field'] else [])
    for feature in layer.getFeatures(QgsFeatureRequest().setSubsetOfAttributes(attributes,layer.fields())):
        name=str(feature[config['class_field']]) if config['class_field'] else CLASSES[int(np.searchsorted(breaks[1:-1],float(feature[config['field']]),side='left'))]
        assert name in CLASSES;full[name]+=1
        in_map=clip_engine.intersects(feature.geometry().constGet())
        if in_map:visible[name]+=1
        in_cg=cg_engine.intersects(feature.geometry().constGet());cg_full+=in_cg;cg_visible+=in_cg and in_map
    assert sum(full.values())==config['expected'] and cg_full==cg_visible and sum(visible.values())>.99*config['expected']
    stem='Kunming_Building_'+title
    print(json.dumps(dict(map=key,source=config['expected'],mapped=sum(visible.values()),classes=dict(full),visible_classes=dict(visible),chenggong=cg_visible,breaks=breaks),ensure_ascii=False),flush=True)
    export_layout(layout,out,stem);save_template(layout,template)
    message,ok=layer.saveNamedStyle(str(template.parent/('building_'+key+'.qml')),QgsMapLayer.Symbology|QgsMapLayer.Labeling|QgsMapLayer.Rendering|QgsMapLayer.Legend);assert ok,message
    assert all(digest(path)==sha for path,sha in protected.items())
    save_project(project,target=target,source=BASE)
    check=QgsProject();assert check.read(str(target))
    restored=check.layoutManager().layoutByName('Kunming_'+title);assert restored and restored.itemById(title+'_Main_Map')
    assert len(restored.itemById(title+'_Main_Map').layers())==9 and all(item.isValid() for item in restored.itemById(title+'_Main_Map').layers())
    for event in events:assert restored.itemById(event['id']).text()==event['text']
    report=dict(created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),project=str(target),layout='Kunming_'+title,
                source=layer.source(),field=config['field'],class_field=config['class_field'],classes=settings,classification_method=method,
                source_count=config['expected'],mapped_count=sum(visible.values()),source_class_counts=dict(full),visible_class_counts=dict(visible),
                source_chenggong_count=cg_full,visible_chenggong_count=cg_visible,breaks=breaks,exposure_classification_display_only=False,
                source_data_unchanged=True,protected_files_sha256=protected,map_extent=extent.toString(12),page_mm=[195,211],
                county_boundary_pt=2,street_boundary_pt=.6,building_outline_pt=.1,basemap_roads_visible=False,
                magnitude_notation='Mw',event_annotations=events,legend_title=config['legend'],project_reload_success=True)
    (out/(key+'_map_report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (out/(key+'_map_class_breaks.csv')).open('w',newline='',encoding='utf-8-sig') as file:
        writer=csv.writer(file);writer.writerow(['class','lower','upper','source_count','mapped_count'])
        for setting in settings:writer.writerow([setting['name'],setting['lower'],setting['upper'],full[setting['name']],visible[setting['name']]])
    print('Saved '+str(target),flush=True)


if __name__ in ('__main__','__console__'):
    if not QgsApplication.instance():
        app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    for config in CONFIGS:draw(config)
    from qgis.utils import iface
    if not iface:os._exit(0)
