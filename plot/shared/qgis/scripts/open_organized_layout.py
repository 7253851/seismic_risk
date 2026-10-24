"""QGIS --code entry: show the canonical project/layout without an Open dialog.

QGIS --project <project.qgz> --code <this.py>
No data, symbols or project files are modified.
"""
from pathlib import Path
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from qgis.core import QgsProject,QgsVectorLayer
from qgis.PyQt.QtCore import QTimer
from qgis.utils import iface
script_dir=Path(QgsProject.instance().fileName()).resolve().parents[3]/'shared/qgis/scripts'
sys.path.insert(0,str(script_dir))
from qgis_paths import PROJECT,HISTORY

def show_layout():
    project=QgsProject.instance()
    if Path(project.fileName()).resolve()!=PROJECT:
        if project.isDirty():raise RuntimeError('请先保存当前工程。')
        assert iface.addProject(str(PROJECT))
    layout=project.layoutManager().layoutByName('Kunming_Hazard_PGA')
    assert layout
    designer=iface.openLayoutDesigner(layout)
    designer.view().zoomFull()
    report=dict(time=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                project=project.fileName(),project_crs=project.crs().authid(),
                layout=layout.name(),total_layers=len(project.mapLayers()),
                local_vectors=[dict(name=l.name(),valid=l.isValid(),count=l.featureCount(),source=l.source())
                               for l in project.mapLayers().values() if isinstance(l,QgsVectorLayer)],
                dirty=project.isDirty(),displayed=True)
    assert len(report['local_vectors'])==25
    assert all(l['valid'] for l in report['local_vectors'])
    record=HISTORY/'2026-10-14_002_workspace_reorganization'
    (record/'live_qgis_reload.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Organized project and existing layout opened:',PROJECT)

QTimer.singleShot(1200,show_layout)
