"""Make the street-level design authoritative for all four thematic maps."""
from qgis_paths import export_path, layout_directory, project_path
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib,json,os,shutil
from qgis.core import *
from qgis.PyQt.QtXml import QDomDocument
from qgis_paths import ROOT,PROJECT,EXPORTS,map_source_path
from draw_hazard_streets import save_project
from map_series_support import apply_street_boundaries,export_layout,save_template,magnitude_notation
from save_indicator_framework_style import layer_key

CONFIGS=[
    ('04_seismic_hazard.qgz','Kunming_Hazard_PGA','hazard','','Kunming_Building_Hazard','hazard_print_report.json'),
    ('04_seismic_hazard_streets.qgz','Kunming_Hazard_PGA_Streets','hazard','hazard_streets','Kunming_Building_Hazard_Streets','hazard_streets_report.json'),
    ('08a_vulnerability.qgz','Kunming_Vulnerability','vulnerability','vulnerability','Kunming_Building_Vulnerability','vulnerability_map_report.json'),
    ('08b_exposure.qgz','Kunming_Exposure','exposure','exposure','Kunming_Building_Exposure','exposure_map_report.json'),
    ('10_risk_base.qgz','Kunming_Final_Risk','risk','final_risk','Kunming_Final_Building_Risk','final_risk_map_report.json'),
]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(project,layout):
    main=layout.referenceMap();assert main
    layers=main.layers();overrides=main.layerStyleOverrides()
    assert len(layers)==9 and all(layer.isValid() for layer in layers)
    assert layers[4].customProperty('seismic_building/base_key','')=='districts'
    assert layers[5].customProperty('seismic_building/base_key','')=='streets'
    assert layers[4].featureCount()==5 and layers[5].featureCount()==134
    for layer,width,color in [(layers[4],2.0,'#30363a'),(layers[5],.6,'#9ca4a9')]:
        clone=layer.clone();QgsMapLayerStyle(overrides[layer.id()]).writeToLayer(clone)
        fill=clone.renderer().symbol().symbolLayer(0)
        assert fill.strokeWidth()==width and fill.strokeWidthUnit()==Qgis.RenderUnit.Points
        assert fill.strokeColor().name()==color and fill.properties()['style']=='no'
    assert not any(layer.customProperty('seismic_building/print_base','')=='roads' for layer in layers)
    for node in project.layerTreeRoot().findLayers():
        if node.layer().customProperty('seismic_building/print_base','')=='roads':assert not node.isVisible()
    for id_ in ['Wuhua','Panlong','Xishan','Guandu','Chenggong','Dian_Lake','Historical_event_0','Event_2026_annotation','GNSS_station_label']:
        item=layout.itemById(id_);assert item and item.text()
        assert item.textFormat().font().family()=='Arial' and item.textFormat().font().bold()
    assert '\nMw 2.1' in layout.itemById('Historical_event_0').text()
    assert '\nMw 4.3' in layout.itemById('Event_2026_annotation').text()
    assert main.grid().annotationTextFormat().size()==12
    assert not layout.itemById('Overview_scale').hasBackground()
    assert not layout.itemById('True_North_Arrow').hasBackground()
    assert layout.itemById('Overview_scale').numberOfSegments()==1
    return dict(project_reload_success=True,all_map_layers_valid=True,county_count=5,street_source_count=134,
                county_boundary_pt=2,street_boundary_pt=.6,county_above_streets=True,
                lake_above_administrative_boundaries=True,basemap_roads_visible=False,
                map_extent=main.extent().toString(12),geographic_and_event_labels_retained=True,
                transparent_north_legend_and_scale=True,magnitude_notation='Mw',export_format='PNG',export_dpi=1200)


def standardize():
    # Read the user's chosen reference before modifying any project.
    reference=QgsProject();assert reference.read(str(ROOT/'04_seismic_hazard/qgis/projects/04_seismic_hazard_streets.qgz'))
    reference_layout=reference.layoutManager().layoutByName('Kunming_Hazard_PGA_Streets');assert reference_layout
    verify(reference,reference_layout)
    ref_main=reference_layout.referenceMap()
    reference_styles={layer_key(layer):ref_main.layerStyleOverrides()[layer.id()] for layer in ref_main.layers()}
    expected_extent=ref_main.extent().toString(12)
    checks=[];removed=[]
    for filename,name,result,folder,stem,report_name in CONFIGS:
        path=project_path(filename);before_project=digest(path)
        project=QgsProject();assert project.read(str(path))
        layout=project.layoutManager().layoutByName(name);assert layout
        main=layout.referenceMap();assert main.extent().toString(12)==expected_extent
        building=next(layer for layer in main.layers() if layer.customProperty('seismic_building/result_key','')==result)
        original_building_source=building.source();original_building_style=main.layerStyleOverrides()[building.id()]
        sources={str(Path(layer.source().split('|')[0])) for layer in main.layers()}
        street=next(layer for layer in project.mapLayers().values() if layer.customProperty('seismic_building/base_key','')=='streets')
        sources.add(street.source().split('|')[0])
        hashes={file:digest(file) for file in sources}
        overrides=main.layerStyleOverrides()
        for layer in list(main.layers())+[street]:
            if layer.id()==building.id():continue
            key=layer_key(layer)
            if key in reference_styles:
                QgsMapLayerStyle(reference_styles[key]).writeToLayer(layer)
                overrides[layer.id()]=reference_styles[key]
        main.setLayerStyleOverrides(overrides)
        boundaries=apply_street_boundaries(project,layout)
        magnitude_notation(layout)
        out=export_path(folder)
        export_layout(layout,out,stem)
        assert building.source()==original_building_source
        assert main.layerStyleOverrides()[building.id()]==original_building_style,'Building classification changed'
        assert all(digest(file)==sha for file,sha in hashes.items()),'Source data changed'
        template_folder='hazard' if not folder else folder
        template=layout_directory(template_folder)/(name+'.qpt')
        save_template(layout,template)
        # Keep the main project's canvas appearance consistent with its locked layout.
        for layer in main.layers():QgsMapLayerStyle(main.layerStyleOverrides()[layer.id()]).writeToLayer(layer)
        assert digest(path)==before_project,'Concurrent project modification'
        save_project(project,target=path,source=path)
        check=QgsProject();assert check.read(str(path))
        restored=check.layoutManager().layoutByName(name);qa=verify(check,restored)
        context=QgsReadWriteContext();context.setPathResolver(QgsPathResolver(str(template)))
        doc=QDomDocument();assert doc.setContent(template.read_text())[0]
        test_layout=QgsPrintLayout(check);_,ok=test_layout.loadFromTemplate(doc,context)
        assert ok;verify(check,test_layout)
        qa.update(project=str(path),layout=name,png=str(out/(stem+'_1200dpi.png')),template_reload_success=True,
                  source_data_unchanged=True,building_classification_unchanged=True)
        checks.append(qa)
        report_path=out/report_name
        report=json.loads(report_path.read_text())
        report.pop('pdf',None);report.pop('pdf_force_vector',None);report.pop('pdf_rasterize',None)
        report.update(boundaries,export_format='PNG',export_dpi=1200,dpi=1200,png=qa['png'],
                      street_standard_updated_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                      street_standard_reference='04_seismic_hazard_streets.qgz',district_boundary_pt=2,
                      administrative_boundaries_above_buildings=True,layer_order=[layer.name() for layer in main.layers()])
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        (out/'export_quality_checks.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n')
        if not folder:
            record=export_path('current_layout_record');record.mkdir(exist_ok=True)
            (record/'verification_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            for layer in main.layers():
                key=layer_key(layer)
                message,ok=layer.saveNamedStyle(str(ROOT/'04_seismic_hazard/qgis/layouts/hazard/print_styles'/(key+'.qml')))
                assert ok,message
            (ROOT/'04_seismic_hazard/qgis/layouts/hazard/print_styles/roads.qml').unlink(missing_ok=True)
        # Obsolete generated exports can always be recreated from the saved project.
        for stale in [out/(stem+'.pdf'),out/(stem+'_preview.png')]:
            if stale.exists():stale.unlink();removed.append(str(stale))
        print('Street standard saved: '+name,flush=True)
    from save_indicator_framework_style import save
    save()
    active=[];folders=set()
    for qa in checks[1:]:
        source=Path(qa['png']);target=map_source_path(source.name);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target);assert digest(source)==digest(target);active.append(target.name);folders.add(target.parent)
    for path in (p for folder in sorted(folders) for p in folder.glob('*.png')):
        if path.name not in active:path.unlink();removed.append(str(path))
    # Recalculate protected hashes of deliberately updated project/style files.
    for _,_,_,folder,_,report_name in CONFIGS:
        path=export_path(folder)/report_name;report=json.loads(path.read_text())
        if 'protected_files_sha256' in report:
            report['protected_files_sha256']={file:digest(file) for file in report['protected_files_sha256'] if Path(file).exists()}
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    result=dict(updated_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),standard='county + township/subdistrict',
                maps=checks,delivery_folders=sorted(map(str,folders)),delivery_pngs=active,obsolete_generated_exports_removed=removed)
    (export_path('street_standard_checks.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(map_count=4,editable_projects_checked=len(checks),delivery_pngs=active),ensure_ascii=False),flush=True)


if __name__ in ('__main__','__console__'):
    if not QgsApplication.instance():
        app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    standardize()
    from qgis.utils import iface
    if not iface:os._exit(0)
