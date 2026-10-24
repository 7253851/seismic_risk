"""Align all current thematic maps with study-area earthquake and GNSS symbols."""
from qgis_paths import export_path, layout_directory, project_path
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib,json,os
from qgis.core import *
from qgis_paths import ROOT,EXPORTS
from draw_hazard_streets import save_project
from map_series_support import export_layout,save_template,magnitude_notation

CONFIGS=[
 ('04_seismic_hazard.qgz','Kunming_Hazard_PGA','hazard','Kunming_Building_Hazard','',export_path('hazard_print_report.json')),
 ('04_seismic_hazard_streets.qgz','Kunming_Hazard_PGA_Streets','hazard_streets','Kunming_Building_Hazard_Streets','hazard_streets',export_path('hazard_streets/hazard_streets_report.json')),
 ('10_risk_base.qgz','Kunming_Final_Risk','final_risk','Kunming_Final_Building_Risk','final_risk',export_path('final_risk/final_risk_map_report.json')),
 ('08a_vulnerability.qgz','Kunming_Vulnerability','vulnerability','Kunming_Building_Vulnerability','vulnerability',export_path('vulnerability/vulnerability_map_report.json')),
 ('08b_exposure.qgz','Kunming_Exposure','exposure','Kunming_Building_Exposure','exposure',export_path('exposure/exposure_map_report.json')),
]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def update():
    reference=ROOT/'01_study_area/qgis/layouts/study_area/verification.json'
    gnss=json.loads(reference.read_text())['gnss_station']
    assert gnss['longitude']==102.8 and gnss['latitude']==25.03
    changed=[]
    for filename,name,folder,stem,sub,report_file in CONFIGS:
        path=project_path(filename);out=export_path(sub)
        project_digest=digest(path)
        p=QgsProject();assert p.read(str(path))
        layout=p.layoutManager().layoutByName(name);assert layout
        main=layout.referenceMap();assert main
        extent=main.extent().toString(12)
        layer_ids=[layer.id() for layer in main.layers()]
        source_hashes={layer.source().split('|')[0]:digest(layer.source().split('|')[0]) for layer in main.layers()}
        events=magnitude_notation(layout)
        points=export_layout(layout,out,stem)
        if folder=='hazard':
            for layer in main.layers():
                if layer.customProperty('seismic_building/validation_role','')=='epicenter':key='event_2026'
                elif layer.customProperty('seismic_building/base_key','')=='earthquakes_local':key='earthquakes'
                else:continue
                message,ok=layer.saveNamedStyle(str(ROOT/'04_seismic_hazard/qgis/layouts/hazard/print_styles'/(key+'.qml')))
                assert ok,message
        assert main.extent().toString(12)==extent and [layer.id() for layer in main.layers()]==layer_ids
        save_template(layout,layout_directory(folder)/(name+'.qpt'))
        assert digest(path)==project_digest,'Concurrent external project update'
        save_project(p,target=path,source=path)
        check=QgsProject();assert check.read(str(path))
        restored=check.layoutManager().layoutByName(name);assert restored
        assert restored.itemById('GNSS_station_label').text()=='GNSS station'
        assert restored.itemById('Earthquake_legend_label').text()=='Earthquakes'
        assert restored.itemById('GNSS_legend_label').text()=='GNSS station'
        assert restored.itemById('Event_2026_legend_symbol') is None
        assert all(digest(file)==sha for file,sha in source_hashes.items())
        report=json.loads(report_file.read_text())
        report['point_symbol_update_time']=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        report['reference_point_symbols']=points
        report['context_legend_entries']=points['legend_entries']
        report['gnss_station']=dict(longitude=102.8,latitude=25.03,symbol='red five-point star',label='GNSS station',reference=str(reference))
        report['event_annotation_style']='Arial Bold Italic, red, 12 pt, white halo'
        report['map_annotation_count']=15
        if 'earthquake_overlay' in report:
            report['earthquake_overlay'].update(historical_symbol='red triangle with white casing',historical_size_mm=3.8,
                                                event_2026_symbol='red triangle with white casing',event_2026_size_mm=3.8)
        for key in ['map_annotation_entries','map_annotations']:
            if key not in report:continue
            annotations=[entry for entry in report[key] if entry['id']!='GNSS_station_label']
            for entry in annotations:
                item=layout.itemById(entry['id'])
                if item:
                    entry['text']=item.text();entry['font_italic']=item.textFormat().font().italic();entry['text_color']=item.textFormat().color().name()
            label=layout.itemById('GNSS_station_label');center=label.sceneBoundingRect().center()
            annotations.append(dict(id='GNSS_station_label',text='GNSS station',font_pt=12,font_italic=True,text_color='#E22D32',center_mm=[center.x(),center.y()]))
            report[key]=annotations
        report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if folder=='hazard':(export_path('current_layout_record/verification_summary.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        changed.append(dict(project=str(path),layout=name,png=str(out/(stem+'_1200dpi.png')),export_format='PNG',export_dpi=1200,point_symbols=points))
        print('Updated point symbols: '+name,flush=True)
    from save_indicator_framework_style import save
    save()
    for _,_,_,_,_,report_file in CONFIGS:
        report=json.loads(report_file.read_text())
        if 'protected_files_sha256' in report:
            report['protected_files_sha256']={file:digest(file) for file in report['protected_files_sha256']}
            report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    record_file=export_path('point_symbol_update.json')
    previous=json.loads(record_file.read_text()) if record_file.exists() else {}
    merged={item['project']:item for item in previous.get('maps',[])}
    merged.update({item['project']:item for item in changed})
    record_file.write_text(json.dumps(dict(reference=str(reference),reference_sha256=digest(reference),gnss_coordinates=[102.8,25.03],maps=list(merged.values())),ensure_ascii=False,indent=2)+'\n')


if __name__ in ('__main__','__console__'):
    if not QgsApplication.instance():
        app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    update()
    from qgis.utils import iface
    if not iface:os._exit(0)
