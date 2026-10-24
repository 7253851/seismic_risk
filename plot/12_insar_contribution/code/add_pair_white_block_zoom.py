"""Native map geometry helpers shared by the current composite."""
from qgis.core import *
from qgis.PyQt.QtCore import QPointF
from qgis.PyQt.QtGui import QPolygonF
PREFIX="Pair_zoom_"

def fill(color,outline,width):
    return QgsFillSymbol.createSimple({'color':color,'outline_color':outline,
             'outline_style':'solid','outline_width':str(width),'joinstyle':'round'})

def page_xy(map_,pt):
    e=map_.extent();s=map_.sizeWithUnits()
    return QPointF(map_.pos().x()+(pt.x()-e.xMinimum())/e.width()*s.width(),
                   map_.pos().y()+(e.yMaximum()-pt.y())/e.height()*s.height())

def gpkg_geometry(blob):
    envelope=(blob[3]>>1)&7
    offset=8+{0:0,1:32,2:48,3:48,4:64}[envelope]
    geom=QgsGeometry();geom.fromWkb(bytes(blob[offset:]));assert not geom.isNull()
    return geom

def add_guide(layout,points,color,width,z,id_):
    x=min(p.x() for p in points);y=min(p.y() for p in points)
    line=QgsLayoutItemPolyline(layout);line.setId(PREFIX+id_)
    line.setNodes(QPolygonF([QPointF(p.x()-x,p.y()-y) for p in points]))
    line.setSymbol(QgsLineSymbol.createSimple({'line_color':color,'line_width':str(width),
                    'line_style':'solid','capstyle':'round','joinstyle':'round'}))
    layout.addLayoutItem(line);line.attemptMove(QgsLayoutPoint(x,y),False);line.setZValue(z)
    return line
