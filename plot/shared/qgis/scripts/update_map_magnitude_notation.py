"""Update current map callouts to the user-requested Mw notation."""
from qgis_paths import export_path, project_path
from pathlib import Path
import json,os,hashlib,re
from qgis.core import *
from qgis_paths import ROOT,EXPORTS
from draw_hazard_streets import save_project
from map_series_support import magnitude_notation,export_layout,save_template

MAPS=[
    ('04_seismic_hazard.qgz','Kunming_Hazard_PGA',EXPORTS,'Kunming_Building_Hazard',ROOT/'04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt'),
    ('04_seismic_hazard_streets.qgz','Kunming_Hazard_PGA_Streets',export_path('hazard_streets'),'Kunming_Building_Hazard_Streets',ROOT/'04_seismic_hazard/qgis/layouts/hazard_streets/Kunming_Hazard_PGA_Streets.qpt'),
    ('10_risk_base.qgz','Kunming_Final_Risk',export_path('final_risk'),'Kunming_Final_Building_Risk',ROOT/'10_risk_transects/qgis/layouts/final_risk/Kunming_Final_Risk.qpt'),
]


def update_reports():
    reports=[export_path('hazard_print_report.json'),export_path('current_layout_record/verification_summary.json'),
             export_path('hazard_streets/hazard_streets_report.json'),export_path('final_risk/final_risk_map_report.json')]
    def replace(value):
        if isinstance(value,str):return re.sub(r'(?m)^M\s+(\d)',r'Mw \1',value)
        if isinstance(value,list):return [replace(item) for item in value]
        if isinstance(value,dict):return {key:replace(item) for key,item in value.items()}
        return value
    for path in reports:
        if not path.exists():continue
        content=replace(json.loads(path.read_text()))
        content['magnitude_display_notation']='Mw'
        content['magnitude_values_unchanged']=True
        content['magnitude_notation_basis']='User-requested display notation; numerical magnitudes unchanged, no conversion performed'
        if 'protected_files_sha256' in content:
            content['protected_files_sha256']={file:hashlib.sha256(Path(file).read_bytes()).hexdigest() for file in content['protected_files_sha256']}
        path.write_text(json.dumps(content,ensure_ascii=False,indent=2)+'\n')


def update():
    changes=[]
    for filename,name,out,stem,template in MAPS:
        file=project_path(filename)
        project=QgsProject();assert project.read(str(file))
        layout=project.layoutManager().layoutByName(name);assert layout
        changes.append({'project':str(file),'annotations':magnitude_notation(layout)})
        export_layout(layout,out,stem)
        save_template(layout,template)
        save_project(project,target=file,source=file)
        check=QgsProject();assert check.read(str(file))
        restored=check.layoutManager().layoutByName(name);assert restored
        for entry in changes[-1]['annotations']:assert restored.itemById(entry['id']).text()==entry['text']
        print('Mw updated: '+filename,flush=True)
    update_reports()
    from save_indicator_framework_style import save
    save()
    update_reports()
    (export_path('magnitude_notation_update.json')).write_text(json.dumps({'notation':'Mw','numeric_magnitudes_unchanged':True,'maps':changes},ensure_ascii=False,indent=2)+'\n')


if __name__ in ('__main__','__console__'):
    if not QgsApplication.instance():
        app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    update()
    from qgis.utils import iface
    if not iface:os._exit(0)
