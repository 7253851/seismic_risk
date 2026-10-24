# -*- coding: utf-8 -*-
"""Open the saved study-area project and its editable layout in QGIS."""
from pathlib import Path
from qgis.core import QgsProject, QgsVectorLayer
from qgis.utils import iface

target = Path(__file__).resolve().parents[2] / 'projects/01_study_area.qgz'
project = QgsProject.instance()
if not project.fileName() or Path(project.fileName()).resolve() != target:
    if project.isDirty():
        raise RuntimeError('当前工程有未保存修改，请先保存，再运行本打开脚本。')
    if not iface.addProject(str(target)):
        raise RuntimeError('无法打开：' + str(target))
layout = project.layoutManager().layoutByName('Kunming_Study_Area')
if layout is None:
    raise RuntimeError('工程中未找到研究区域概况布局。')
for layer in project.mapLayers().values():
    if isinstance(layer, QgsVectorLayer) and Path(layer.source().split('|')[0]).stem in {
        'TSX1_Extent', 'TSX2_Extent', 'TSX_Total_Extent'
    }:
        layer.dataProvider().reloadData()
        layer.updateExtents(True)
        layer.triggerRepaint()
layout.refresh()
iface.mapCanvas().refreshAllLayers()
designer = iface.openLayoutDesigner(layout)
designer.view().zoomFull()
print('已打开昆明市研究区域概况布局：' + str(target))
