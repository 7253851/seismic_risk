"""Shared rendering helpers; no legacy layout entry point."""
from pathlib import Path
import csv
_CLASS_TABLE = Path(__file__).resolve().parents[3] / '../result/hazard/scs_pipeline/pga_class_breaks.csv'
with _CLASS_TABLE.open(encoding='utf-8-sig') as _stream:
    _rows = list(csv.DictReader(_stream))
_PALETTE = ['#FFF1A8', '#FFC247', '#F58A24', '#DB3B29', '#7A1018']
CLASSES = [(row['PGA_Class'], '\"PGA_Class\" = ' + repr(row['PGA_Class']), color)
           for row, color in zip(_rows, _PALETTE)]
EXPECTED_COUNTS = [int(row['Building_Count']) for row in _rows]
BACKGROUND = '#D1D5D7'
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import copy
import hashlib
import json
import shutil
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from qgis.core import (
    Qgis, QgsApplication, QgsProject, QgsLayoutItemMap, QgsLayoutItemPage,
    QgsLayoutItemLabel, QgsLayoutItemShape, QgsLayoutItemPicture,
    QgsLayoutItemScaleBar, QgsLayoutItemPolyline, QgsLayoutItemMapGrid,
    QgsLayoutSize, QgsLayoutPoint, QgsLayoutMeasurement, QgsLayoutExporter,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsPointXY,
    QgsRectangle, QgsReadWriteContext, QgsMapLayerStyle, QgsVectorLayer,
    QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer,
    QgsRuleBasedRenderer, QgsTextFormat, QgsTextBufferSettings, QgsVectorSimplifyMethod,
    QgsFeatureRequest, QgsGeometry,
)
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QPolygonF, QPainter
from qgis.utils import iface
def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def text_format(size=9, bold=False, color='#303434'):
    f = QFont('Arial'); f.setPointSizeF(size); f.setBold(bold)
    t = QgsTextFormat(); t.setFont(f); t.setSize(size); t.setColor(QColor(color))
    return t
def rectangle(layout, id_, box, color, stroke='#C8CBCC', width='0.15', dash='solid'):
    i = QgsLayoutItemShape(layout); i.setId(id_); i.setShapeType(QgsLayoutItemShape.Rectangle)
    i.setSymbol(QgsFillSymbol.createSimple({'color':color,'outline_color':stroke,
        'outline_width':width,'outline_style':'no' if width=='0' else dash,'joinstyle':'miter'}))
    layout.addLayoutItem(i); i.attemptMove(QgsLayoutPoint(*box[:2])); i.attemptResize(QgsLayoutSize(*box[2:]))
    return i
def xml_style(layer):
    s=QgsMapLayerStyle();s.readFromLayer(layer);return s.xmlData()
def source_layer(project, property_, value):
    l=next((l for l in project.mapLayers().values() if l.customProperty(property_,'')==value),None)
    if not l or not l.isValid(): raise RuntimeError(f'缺少有效图层：{value}')
    return l
def configure_map(map_,box,layers,styles,extent,crs):
    map_.attemptMove(QgsLayoutPoint(*box[:2]));map_.attemptResize(QgsLayoutSize(*box[2:]))
    map_.setCrs(crs);map_.setMapRotation(0);map_.zoomToExtent(extent)
    map_.setFollowVisibilityPreset(False);map_.setFollowVisibilityPresetName('')
    map_.setLayers(layers);map_.setKeepLayerSet(True)
    map_.setKeepLayerStyles(True);map_.setLayerStyleOverrides({l.id():styles[l.id()] for l in layers})
    map_.setBackgroundEnabled(True);map_.setBackgroundColor(QColor(BACKGROUND))
    map_.setFrameEnabled(True);map_.setFrameStrokeColor(QColor('#333638'));map_.setFrameStrokeWidth(QgsLayoutMeasurement(0.25))
def scale_bar(layout,map_,id_,xy,units,per_segment,unit_label):
    s=QgsLayoutItemScaleBar(layout);s.setId(id_);s.setStyle('Line Ticks Up');s.setLinkedMap(map_)
    s.setUnits(units);s.setUnitsPerSegment(per_segment);s.setNumberOfSegments(2);s.setNumberOfSegmentsLeft(0)
    s.setUnitLabel(unit_label);s.setHeight(1.1);s.setTextFormat(text_format(7.5))
    s.setBackgroundEnabled(True);s.setBackgroundColor(QColor('white'));layout.addLayoutItem(s);s.attemptMove(QgsLayoutPoint(*xy));return s
def preserve_gui_and_save(project,original_zip,backup):
    """离屏PyQGIS不写GUI专用节点，补回它们再原子保存。"""
    stage=PROJECT.parent/'.hazard_print_stage.qgz'
    if not project.write(str(stage)):raise RuntimeError('QGIS工程保存失败')
    with zipfile.ZipFile(backup) as old,zipfile.ZipFile(stage) as new:
        old_name=next(n for n in old.namelist() if n.endswith('.qgs'))
        new_name=next(n for n in new.namelist() if n.endswith('.qgs'))
        a=ET.fromstring(old.read(old_name));b=ET.fromstring(new.read(new_name))
        for tag in ['mapcanvas','mapViewDocks','mapViewDocks3D','projectModels','ProjectViewSettings','legend']:
            old_node=a.find(tag)
            if old_node is not None:
                for node in b.findall(tag):b.remove(node)
                b.append(copy.deepcopy(old_node))
        target=PROJECT.parent/'.hazard_print_atomic.qgz'
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as output:
            output.writestr('seismic_building.qgs',b'<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(b,encoding='utf-8'))
            for info in new.infolist():
                if not info.filename.endswith('.qgs'):output.writestr(info,new.read(info.filename))
        target.replace(PROJECT)
    stage.unlink();project.setFileName(str(PROJECT))
from qgis_paths import ROOT as BASE, PROJECT
