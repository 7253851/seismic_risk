"""Draw the confirmed SCS final-risk classes using the current map design."""
from qgis_paths import export_path
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os

from qgis.core import *
from qgis_paths import ROOT,EXPORTS
from draw_hazard_streets import save_project
from revise_hazard_layout import map_polygon
from map_series_support import export_layout

BASE_PROJECT = ROOT/'04_seismic_hazard/qgis/projects/04_seismic_hazard_streets.qgz'
PROJECT = ROOT/'10_risk_transects/qgis/projects/10_risk_base.qgz'
OUT = export_path('final_risk')
TEMPLATE = ROOT/'10_risk_transects/qgis/layouts/final_risk/Kunming_Final_Risk.qpt'
RISK_FILE = ROOT/'../result/risk/scs_paper_method/building_risk.gpkg'
SUMMARY_FILE = RISK_FILE.parent/'calculation_summary.json'
LAYOUT_NAME = 'Kunming_Final_Risk'
CLASSES = ['Very Low','Low','Moderate','High','Very High']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def draw():
    OUT.mkdir(parents=True,exist_ok=True)
    TEMPLATE.parent.mkdir(parents=True,exist_ok=True)
    protected = [BASE_PROJECT,export_path('hazard_streets/Kunming_Building_Hazard_Streets_1200dpi.png'),
                 ROOT/'shared/styles/Kunming_Indicator_Framework_Distribution/style_manifest.json',RISK_FILE,SUMMARY_FILE]
    hashes = {str(path):digest(path) for path in protected}
    summary = json.loads(SUMMARY_FILE.read_text())
    project = QgsProject()
    assert project.read(str(BASE_PROJECT))
    layout = project.layoutManager().layoutByName('Kunming_Hazard_PGA_Streets')
    assert layout
    main = layout.itemById('Hazard_Main_Map')
    extent = QgsRectangle(main.extent())
    existing_layers = main.layers()
    overrides = main.layerStyleOverrides()
    hazard = next(layer for layer in existing_layers if layer.customProperty('seismic_building/result_key','')=='hazard')
    original_hazard = hazard.clone()
    QgsMapLayerStyle(overrides[hazard.id()]).writeToLayer(original_hazard)
    renderer = original_hazard.renderer().clone()
    rules = renderer.rootRule().children()
    assert len(rules)==5
    class_settings=[]
    for rule,name in zip(rules,CLASSES):
        expression='"Risk_Class" = '+"'"+name+"'"
        rule.setFilterExpression(expression)
        rule.setLabel(name)
        class_settings.append({'name':name,'expression':expression,'color':rule.symbol().color().name(),
                               'source_count':summary['class_counts'][name]})
    risk = next(layer for layer in project.mapLayers().values() if layer.customProperty('seismic_building/result_key','')=='risk')
    risk.setDataSource(str(RISK_FILE)+'|layername=building_risk_scs','建筑最终风险 R · SCS 五级','ogr')
    assert risk.isValid() and risk.featureCount()==summary['complete_risk_buildings']==40000
    assert not risk.subsetString()
    assert risk.fields().indexFromName('Risk_Class')>=0 and risk.fields().indexFromName('Risk_Final')>=0
    risk.setRenderer(renderer)
    risk.setLabelsEnabled(False)
    risk.setOpacity(1)
    risk.setScaleBasedVisibility(False)
    simplify=QgsVectorSimplifyMethod();simplify.setSimplifyHints(Qgis.VectorRenderingSimplificationFlag.NoSimplification)
    risk.setSimplifyMethod(simplify)
    risk.setCustomProperty('seismic_building/risk_method','SCS complete H-V-E sample; existing five Jenks classes')
    metadata=risk.metadata()
    metadata.setTitle('SCS final building risk - five classes')
    metadata.setAbstract('Risk_Final = minmax(minmax(PGA_g) * Vul_Index * Exp_Final). Existing Risk_Class is used directly. This is a relative normalized risk index. Only the complete 40,000-building H-V-E sample is classified.')
    risk.setMetadata(metadata)
    risk_style=QgsMapLayerStyle();risk_style.readFromLayer(risk)
    overrides.pop(hazard.id())
    overrides[risk.id()]=risk_style.xmlData()
    ordered=[risk if layer.id()==hazard.id() else layer for layer in existing_layers]
    main.setLayers(ordered)
    main.setLayerStyleOverrides(overrides)
    main.setId('Risk_Main_Map')
    layout.setName(LAYOUT_NAME)
    layout.setCustomProperty('seismic_building/result','SCS_final_risk')
    project.setTitle('Kunming final building seismic risk - SCS five classes')
    project.setCustomVariables(dict(project.customVariables(),mapped_result='SCS_final_risk'))
    legend_title=layout.itemById('Legend_title')
    legend_title.setText('Risk level')
    for index,name in enumerate(CLASSES):
        layout.itemById('Legend_range_'+str(index)).setText(name)
    root=project.layerTreeRoot()
    for node in root.findLayers():
        node.setItemVisibilityChecked(node.layerId() in overrides)
    for layer in ordered:
        node=root.findLayer(layer.id())
        while node and node is not root:
            node.setItemVisibilityChecked(True)
            node=node.parent()
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(ordered+[layer for layer in project.mapLayers().values() if layer.id() not in overrides])
    clip=map_polygon(extent,main.crs(),risk.crs(),project)
    clip_engine=QgsGeometry.createGeometryEngine(clip.constGet());clip_engine.prepareGeometry()
    counties=next(layer for layer in ordered if layer.customProperty('seismic_building/base_key','')=='districts')
    cg=next(feature.geometry() for feature in counties.getFeatures() if feature['name']=='呈贡区')
    cg.transform(QgsCoordinateTransform(counties.crs(),risk.crs(),project))
    cg_engine=QgsGeometry.createGeometryEngine(cg.constGet());cg_engine.prepareGeometry()
    all_counts,visible_counts=Counter(),Counter()
    source_cg=visible_cg=0
    for feature in risk.getFeatures(QgsFeatureRequest().setSubsetOfAttributes(['Risk_Class','Risk_Final'],risk.fields())):
        name=str(feature['Risk_Class']);value=float(feature['Risk_Final'])
        assert name in CLASSES and 0<=value<=1
        all_counts[name]+=1
        visible=clip_engine.intersects(feature.geometry().constGet())
        if visible:visible_counts[name]+=1
        in_cg=cg_engine.intersects(feature.geometry().constGet())
        source_cg+=in_cg;visible_cg+=in_cg and visible
    assert dict(all_counts)==summary['class_counts']
    assert visible_cg==source_cg
    assert sum(visible_counts.values())>.99*risk.featureCount()
    assert main.extent().toString(12)==extent.toString(12)
    assert len(ordered)==9 and not any(layer.customProperty('seismic_building/print_base','')=='roads' for layer in ordered)
    assert ordered[4].id()==counties.id() and counties.featureCount()==5
    print(json.dumps({'source_risk_buildings':risk.featureCount(),'mapped_risk_buildings':sum(visible_counts.values()),
                      'source_classes':dict(all_counts),'visible_classes':dict(visible_counts),'chenggong_risk_buildings':visible_cg},ensure_ascii=False),flush=True)
    export_layout(layout,OUT,'Kunming_Final_Building_Risk')
    context=QgsReadWriteContext();context.setPathResolver(QgsPathResolver(str(TEMPLATE)))
    assert layout.saveAsTemplate(str(TEMPLATE),context)
    message,ok=risk.saveNamedStyle(str(TEMPLATE.parent/'building_final_risk.qml'),QgsMapLayer.Symbology|QgsMapLayer.Labeling|QgsMapLayer.Rendering|QgsMapLayer.Legend)
    assert ok,message
    assert all(digest(path)==sha for path,sha in hashes.items())
    save_project(project,target=PROJECT,source=BASE_PROJECT)
    check=QgsProject();assert check.read(str(PROJECT))
    restored=check.layoutManager().layoutByName(LAYOUT_NAME);assert restored
    restored_main=restored.itemById('Risk_Main_Map');assert restored_main
    assert len(restored_main.layers())==9 and all(layer.isValid() for layer in restored_main.layers())
    mapped=next(layer for layer in restored_main.layers() if layer.customProperty('seismic_building/result_key','')=='risk')
    assert mapped.source().split('|')[0]==str(RISK_FILE) and mapped.featureCount()==40000
    assert restored_main.extent().toString(12)==extent.toString(12)
    assert restored.itemById('Legend_title').text()=='Risk level'
    assert all(digest(path)==sha for path,sha in hashes.items())
    baseline_report=json.loads((export_path('hazard_streets/hazard_streets_report.json')).read_text())
    report={'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'project':str(PROJECT),'layout':LAYOUT_NAME,
            'png':str(OUT/'Kunming_Final_Building_Risk_1200dpi.png'),'export_format':'PNG','export_dpi':1200,'source':mapped.source(),'source_choice':'User confirmed the newly calculated SCS final risk',
            'risk_field':'Risk_Final','classification_field':'Risk_Class','classes':class_settings,'existing_classes_preserved':True,
            'jenks_breaks':summary['jenks_breaks'],'source_building_count':risk.featureCount(),'mapped_building_count':sum(visible_counts.values()),
            'source_class_counts':dict(all_counts),'visible_class_counts':dict(visible_counts),'source_chenggong_count':source_cg,'visible_chenggong_count':visible_cg,
            'map_extent':extent.toString(12),'page_mm':[195,211],'building_outline_pt':.1,'county_boundary_pt':2,'street_boundary_pt':.6,
            'basemap_roads_visible':False,'legend_title':'Risk level','legend_classes':CLASSES,
            'all_source_and_hazard_files_unchanged':True,'protected_files_sha256':hashes,
            'saved_project_reload_success':True,'all_map_layers_valid':True,'layer_order':[layer.name() for layer in ordered],
            'map_annotations':baseline_report['map_annotations'],'relative_risk_index':True,
            'classification_method':summary['jenks_method'],'risk_method':summary['method']}
    (OUT/'final_risk_map_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Saved '+str(PROJECT),flush=True)


if __name__ in ('__main__','__console__'):
    if not QgsApplication.instance():
        app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    draw()
    from qgis.utils import iface
    if not iface:os._exit(0)
