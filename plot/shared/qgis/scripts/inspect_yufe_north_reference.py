"""Render a georeferenced QGIS imagery reference for the north-campus screenshot."""
from pathlib import Path
from qgis_paths import ROOT,PROJECT
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from qgis.core import (QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsRectangle, QgsMapSettings, QgsMapRendererParallelJob)
from qgis.PyQt.QtCore import QSize

project = QgsProject.instance()
if Path(project.fileName()).resolve() != PROJECT:
    raise RuntimeError('请先打开04_seismic_hazard/projects/04_seismic_hazard.qgz')
out = ROOT/'../result/intermediate/campus_digitization/north'
out.mkdir(parents=True, exist_ok=True)
points = next(l for l in project.mapLayers().values() if l.name().startswith('验证地点 · 百度 POI'))
target = next(f for f in points.getFeatures() if f['loc_id'] == 'CF02')
geom = target.geometry()
crs = QgsCoordinateReferenceSystem('EPSG:4543')
geom.transform(QgsCoordinateTransform(points.crs(), crs, project))
center = geom.asPoint()
imagery = next(l for l in project.mapLayers().values() if l.name().startswith('Esri World Imagery'))
settings = QgsMapSettings()
settings.setLayers([imagery])
settings.setDestinationCrs(crs)
settings.setExtent(QgsRectangle(center.x()-600, center.y()-600, center.x()+600, center.y()+600))
settings.setOutputSize(QSize(2400, 2400))
settings.setOutputDpi(96)
job = QgsMapRendererParallelJob(settings)
job.start()
job.waitForFinished()
if not job.renderedImage().save(str(out/'qgis_reference_imagery.png')):
    raise RuntimeError('无法保存参考影像')
extent = settings.extent()
metadata = dict(created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                project=project.fileName(), crs=crs.authid(),
                extent=[extent.xMinimum(),extent.yMinimum(),extent.xMaximum(),extent.yMaximum()],
                image_width=2400,image_height=2400,layer=imagery.name(),reference_loc_id='CF02',
                errors=[str(e.message) for e in job.errors()])
(out/'qgis_reference_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
print('北院配准参考影像已导出：', out)
