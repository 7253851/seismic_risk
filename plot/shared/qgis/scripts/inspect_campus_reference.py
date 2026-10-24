"""Read-only QGIS reference render for screenshot georeferencing."""
from pathlib import Path
from qgis_paths import ROOT
import json
from qgis.core import QgsProject, QgsFeatureRequest, QgsCoordinateTransform, QgsRectangle, QgsMapSettings, QgsMapRendererParallelJob
from qgis.PyQt.QtCore import QSize

project=QgsProject.instance()
out=ROOT/'../result/intermediate/campus_digitization/south'
out.mkdir(parents=True,exist_ok=True)
risk=next(l for l in project.mapLayers().values() if l.name()=='建筑最终风险 R')
target=next(risk.getFeatures(QgsFeatureRequest().setFilterExpression('"Build_ID"=34318')))
geom=target.geometry()
geom.transform(QgsCoordinateTransform(risk.crs(),project.crs(),project))
center=geom.centroid().asPoint()
extent=QgsRectangle(center.x()-850,center.y()-850,center.x()+850,center.y()+850)
imagery=next(l for l in project.mapLayers().values() if l.name().startswith('Esri World Imagery'))
settings=QgsMapSettings()
settings.setLayers([imagery])
settings.setDestinationCrs(project.crs())
settings.setExtent(extent)
settings.setOutputSize(QSize(2400,2400))
settings.setOutputDpi(96)
job=QgsMapRendererParallelJob(settings)
job.start()
job.waitForFinished()
job.renderedImage().save(str(out/'qgis_reference_imagery.png'))
actual=settings.extent()
(out/'qgis_reference_metadata.json').write_text(json.dumps(dict(project=project.fileName(),project_dirty=project.isDirty(),crs=project.crs().authid(),
 extent=[actual.xMinimum(),actual.yMinimum(),actual.xMaximum(),actual.yMaximum()],image_width=2400,image_height=2400,
 layer=imagery.name(),target_build_id=34318,errors=[str(e.message) for e in job.errors()]),ensure_ascii=False,indent=2)+'\n')
print('QGIS参考影像已导出：',out)
