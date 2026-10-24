# -*- coding: utf-8 -*-
"""在 QGIS Python 控制台运行：打开已保存的危险性布局，不重新制图。"""
from qgis.core import QgsProject
from qgis.utils import iface

layout = QgsProject.instance().layoutManager().layoutByName("Kunming_Hazard_PGA")
if layout is None:
    raise RuntimeError("当前工程没有危险性布局，请先打开 /04_seismic_hazard.qgz 或运行 create_hazard_layout.py。")
iface.openLayoutDesigner(layout)
print("已打开可编辑危险性布局 Kunming_Hazard_PGA。")
