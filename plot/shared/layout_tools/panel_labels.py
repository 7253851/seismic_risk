"""Panel letters as native QGIS layout labels, following the JPEG figure style.

Each label is Arial Regular, black, placed outside the upper-left corner of its
panel. Positions are page millimetres of the label's top-right corner (`right`)
or top-left corner (`left`) and are kept in each figure's panel_labels.json.
"""
import json
from pathlib import Path

from qgis.core import Qgis, QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize, QgsTextBufferSettings, QgsTextFormat
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

FONT_PT = 10.0
BOX_MM = (6.0, 4.2)


def load(folder):
    path = Path(folder)/'panel_labels.json'
    return json.loads(path.read_text()) if path.exists() else []


def add(layout, labels, font_pt=FONT_PT):
    added = []
    for spec in labels:
        item = QgsLayoutItemLabel(layout)
        item.setId('Panel_label_' + spec['text'].strip('()'))
        item.setText(spec['text'])
        fmt = QgsTextFormat()
        font = QFont('Arial')
        font.setWeight(QFont.Normal)
        fmt.setFont(font)
        fmt.setSize(font_pt)
        fmt.setColor(QColor('#000000'))
        if spec.get('halo'):
            # Letters placed inside a map get a white halo, like the map's own labels.
            buffer = QgsTextBufferSettings()
            buffer.setEnabled(True)
            buffer.setSize(0.6)
            buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
            buffer.setColor(QColor('#ffffff'))
            fmt.setBuffer(buffer)
        item.setTextFormat(fmt)
        right = spec.get('anchor', 'right') == 'right'
        item.setHAlign(Qt.AlignRight if right else Qt.AlignLeft)
        item.setVAlign(Qt.AlignTop)
        item.setMarginX(0)
        item.setMarginY(0)
        layout.addLayoutItem(item)
        item.attemptResize(QgsLayoutSize(*BOX_MM))
        x = spec['x_mm'] - (BOX_MM[0] if right else 0)
        item.attemptMove(QgsLayoutPoint(x, spec['y_mm']))
        item.setZValue(1000)
        added.append({'id': item.id(), **spec, 'font': 'Arial Regular', 'font_pt': font_pt})
    return added


def export_top_layer(layout, pdf, dpi=1440):
    """Export only the panel letters, for stacking above Python chart overlays."""
    items = [i for i in layout.items() if hasattr(i, 'id') and callable(i.id) and hasattr(i, 'setVisibility')]
    visible = {i: i.isVisible() for i in items}
    for item in items:
        item.setVisibility(item.id().startswith('Panel_label_'))
    page = layout.pageCollection().page(0)
    page_visible = page.isVisible()
    page.setVisible(False)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = dpi
    settings.forceVectorOutput = True
    settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    settings.appendGeoreference = False
    try:
        result = QgsLayoutExporter(layout).exportToPdf(str(pdf), settings)
    finally:
        for item, was in visible.items():
            item.setVisibility(was)
        page.setVisible(page_visible)
    assert result == QgsLayoutExporter.Success
    return str(pdf)
