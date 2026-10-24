"""Local, label-free Esri World Hillshade cache with neutral gray shadows."""
from qgis.core import (
    QgsRasterLayer, QgsColorRampShader, QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor, QPainter
from qgis_paths import ROOT

HILLSHADE_FILE = ROOT/'../data/cartography/terrain/kunming_esri_hillshade.tif'
SERVICE = 'https://services.arcgisonline.com/arcgis/rest/services/Elevation/World_Hillshade/MapServer'
OPACITY = 0.80
# Deeper neutral-gray mountain shadows, with bright and flat terrain near white.
COLORS = [(0, '#808080'), (104, '#909090'), (160, '#B7B7B7'),
          (200, '#D7D7D7'), (230, '#EFEFEF'), (245, '#FFFFFF'), (255, '#FFFFFF')]


def style_hillshade(layer):
    ramp = QgsColorRampShader()
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    ramp.setMinimumValue(0)
    ramp.setMaximumValue(255)
    ramp.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), str(v)) for v,c in COLORS])
    shader = QgsRasterShader(0,255)
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(),1,shader)
    renderer.setClassificationMin(0)
    renderer.setClassificationMax(255)
    renderer.setOpacity(OPACITY)
    layer.setRenderer(renderer)
    layer.setBlendMode(QPainter.CompositionMode_SourceOver)


def ensure_hillshade(project):
    layer = next((l for l in project.mapLayers().values()
                  if l.customProperty('seismic_building/print_base','')=='hillshade'),None)
    if layer is None:
        layer = QgsRasterLayer(str(HILLSHADE_FILE),'灰色山体阴影 · Esri World Hillshade（底图缓存）','gdal')
        if not layer.isValid():
            raise RuntimeError('Local hillshade cache is unavailable: '+str(HILLSHADE_FILE))
        layer.setCustomProperty('seismic_building/print_base','hillshade')
        layer.setCustomProperty('seismic_building/hillshade_source',SERVICE)
        project.addMapLayer(layer,False)
        basic = project.layerTreeRoot().findGroup('基础要素') or project.layerTreeRoot()
        group = basic.findGroup('地形背景 · 底图缓存') or basic.addGroup('地形背景 · 底图缓存')
        node = group.addLayer(layer)
        node.setItemVisibilityChecked(False)
        group.setExpanded(False)
    layer.setName('灰色山体阴影 · Esri World Hillshade（底图缓存）')
    style_hillshade(layer)
    metadata = layer.metadata()
    metadata.setTitle('Esri World Hillshade - neutral gray local cartographic background')
    metadata.setAbstract('Label-free cartographic hillshade cached from '+SERVICE+
                         '. Used only as a neutral-gray map background; this is rendered basemap imagery, not a raw DEM or an input to the hazard model.')
    metadata.setRights(['Sources: Esri, Vantor, Airbus DS, USGS, NGA, NASA, CGIAR, N Robinson, NCEAS, NLS, OS, NMA, Geodatastyrelsen, Rijkswaterstaat, GSA, Geoland, FEMA, Intermap, and the GIS user community'])
    layer.setMetadata(metadata)
    return layer
