"""Cartographic helpers for the current figure12 composite."""
from pathlib import Path
import hashlib
from qgis.core import *
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor,QFont
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'plot/12_insar_contribution/output'
WORK=OUT/'support'
QDIR=ROOT/'plot/12_insar_contribution/qgis'
PROJECT=QDIR/'projects/12_insar_contribution.qgz'
TEMPLATE=ROOT/'plot/12_insar_contribution/qgis/layouts/12_insar_contribution/12_insar_contribution.qpt'
FIGURE=OUT/'current/figure12'
RED='#C5433C';BLUE='#2875B5'


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def marker(color,size,opacity=1,shape='circle'):
    symbol=QgsMarkerSymbol.createSimple({'name':shape,'color':color,'size':str(size),
                                        'outline_style':'no','outline_width':'0'})
    if shape=='star':
        symbol.symbolLayer(0).setStrokeStyle(Qt.SolidLine)
        symbol.symbolLayer(0).setStrokeColor(QColor('white'))
        symbol.symbolLayer(0).setStrokeWidth(.15)
    symbol.setOpacity(opacity)
    return symbol

def text(layout,id_,value,x,y,width,size=7,bold=False):
    item=QgsLayoutItemLabel(layout);item.setId(id_);item.setText(value);item.setMargin(0)
    fmt=QgsTextFormat();font=QFont('Arial');font.setPointSizeF(size);font.setBold(bold)
    fmt.setFont(font);fmt.setSize(size);fmt.setColor(QColor('#24282B'))
    halo=QgsTextBufferSettings();halo.setEnabled(True);halo.setColor(QColor('white'));halo.setSize(.22)
    fmt.setBuffer(halo);item.setTextFormat(fmt);item.setVAlign(Qt.AlignVCenter)
    item.setBackgroundEnabled(False);item.setFrameEnabled(False)
    layout.addLayoutItem(item);item.attemptMove(QgsLayoutPoint(x,y),False)
    item.attemptResize(QgsLayoutSize(width,5.5));item.setZValue(60)
    return item

def save_and_export(project,layout):
    project.setFileName(str(PROJECT));assert project.write()
    context=QgsReadWriteContext();context.setPathResolver(QgsPathResolver(str(TEMPLATE)))
    assert layout.saveAsTemplate(str(TEMPLATE),context)
    exporter=QgsLayoutExporter(layout)
    png=QgsLayoutExporter.ImageExportSettings();png.dpi=600;png.exportMetadata=True
    assert exporter.exportToImage(str(FIGURE)+'.png',png)==QgsLayoutExporter.Success
    svg=QgsLayoutExporter.SvgExportSettings();svg.dpi=600;svg.forceVectorOutput=True
    svg.textRenderFormat=Qgis.TextRenderFormat.AlwaysText
    assert exporter.exportToSvg(str(FIGURE)+'.svg',svg)==QgsLayoutExporter.Success
