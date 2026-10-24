"""QGIS console: open the canonical organized project without restyling it."""
from pathlib import Path
from qgis.core import QgsProject
from qgis.utils import iface
from qgis_paths import PROJECT
project=QgsProject.instance()
if project.isDirty():
    raise RuntimeError('请先保存当前工程，再打开整理后的工程。')
if not project.read(str(PROJECT)):
    raise RuntimeError('无法打开：'+str(PROJECT))
iface.mapCanvas().refresh()
print('已打开整理后的工程：',PROJECT)
