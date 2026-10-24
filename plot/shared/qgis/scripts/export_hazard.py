"""Export the existing saved hazard layout; do not regenerate its design or data."""
from qgis_paths import export_path
import json
import os
import sys
from qgis.core import QgsApplication,QgsProject,QgsLayoutExporter,Qgis
from qgis_paths import PROJECT,EXPORTS
from map_series_support import export_layout

def export():
    from qgis.utils import iface
    if iface and QgsProject.instance().isDirty():
        raise RuntimeError('请先保存当前工程，然后导出。')
    project=QgsProject();assert project.read(str(PROJECT))
    layout=project.layoutManager().layoutByName('Kunming_Hazard_PGA');assert layout
    record=export_path('current_layout_record')
    record.mkdir(parents=True,exist_ok=True);EXPORTS.mkdir(parents=True,exist_ok=True)
    png=export_path('Kunming_Building_Hazard_1200dpi.png')
    export_layout(layout,EXPORTS,'Kunming_Building_Hazard')
    (record/'export_record.json').write_text(json.dumps(dict(project=str(PROJECT),layout=layout.name(),png=str(png),dpi=1200,format='PNG',administrative_level='county + township/subdistrict'),indent=2)+'\n')
    print('已导出：',png,flush=True)

if __name__ in ('__main__','__console__'):
    from qgis.utils import iface
    if not QgsApplication.instance():
        app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    export()
    if not iface: os._exit(0)
