"""Shared export and magnitude notation for the H/V/E/R map series."""
from pathlib import Path
import re
import shutil
from qgis.core import *
from qgis.PyQt.QtCore import Qt,QPointF
from qgis.PyQt.QtGui import QColor,QFont,QPolygonF

EXPORT_DPI=1200
POINT_COLOR='#E22D32'
GNSS_LONGITUDE,GNSS_LATITUDE=102.8,25.03
FIVE_DISTRICTS=['五华区','盘龙区','西山区','官渡区','呈贡区']


def apply_street_boundaries(project,layout):
    """Keep all thematic maps on the county + township/subdistrict standard."""
    main=layout.referenceMap();assert main
    extent=main.extent().toString(12)
    boundaries={key:next(layer for layer in project.mapLayers().values()
                        if layer.customProperty('seismic_building/base_key','')==key)
                for key in ['districts','streets']}
    county,street=boundaries['districts'],boundaries['streets']
    assert county.setSubsetString('"name" IN ('+','.join("'"+name+"'" for name in FIVE_DISTRICTS)+')')
    assert county.featureCount()==5 and street.featureCount()==134
    overrides=main.layerStyleOverrides()
    for layer,width,color in [(county,2.0,'#30363A'),(street,.6,'#9CA4A9')]:
        if layer.id() in overrides:QgsMapLayerStyle(overrides[layer.id()]).writeToLayer(layer)
        symbol=layer.renderer().symbol().clone()
        fill=symbol.symbolLayer(0)
        fill.setBrushStyle(Qt.NoBrush);fill.setStrokeStyle(Qt.SolidLine)
        fill.setStrokeWidth(width);fill.setStrokeWidthUnit(Qgis.RenderUnit.Points)
        fill.setStrokeColor(QColor(color))
        layer.setRenderer(QgsSingleSymbolRenderer(symbol));layer.setOpacity(1)
        layer.setLabelsEnabled(False);layer.setScaleBasedVisibility(False)
        style=QgsMapLayerStyle();style.readFromLayer(layer);overrides[layer.id()]=style.xmlData()
    ordered=[layer for layer in main.layers() if layer.id() not in [county.id(),street.id()]
             and layer.customProperty('seismic_building/print_base','')!='roads']
    building=next(layer for layer in ordered if layer.customProperty('seismic_building/result_key','') in ['hazard','risk','vulnerability','exposure'])
    position=ordered.index(building);ordered[position:position]=[county,street]
    assert len(ordered)==9 and ordered[4]==county and ordered[5]==street
    main.setLayers(ordered);main.setKeepLayerSet(True);main.setKeepLayerStyles(True)
    main.setFollowVisibilityPreset(False);main.setFollowVisibilityPresetName('')
    main.setLayerStyleOverrides({layer.id():overrides[layer.id()] for layer in ordered})
    root=project.layerTreeRoot()
    for node in root.findLayers():node.setItemVisibilityChecked(node.layerId() in {layer.id() for layer in ordered})
    for layer in ordered:
        node=root.findLayer(layer.id())
        while node and node is not root:node.setItemVisibilityChecked(True);node=node.parent()
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(ordered+[layer for layer in project.mapLayers().values() if layer not in ordered])
    layout.setCustomProperty('seismic_building/administrative_level','five_counties_and_township_subdistrict')
    project.setCustomVariables(dict(project.customVariables(),hazard_administrative_level='five_counties_and_township_subdistrict'))
    assert main.extent().toString(12)==extent
    return dict(administrative_level='five county-level districts + township/subdistrict',county_count=5,
                county_boundary_pt=2.0,county_boundary_color='#30363A',street_boundary_pt=.6,
                street_boundary_color='#9CA4A9',administrative_source_count=134,
                county_above_streets=True,basemap_roads_visible=False)


def reference_point_symbol(gnss=False,legend=False):
    factor=.68 if legend else 1
    size=6.0 if gnss else 3.8
    shape='star' if gnss else 'triangle'
    symbol=QgsMarkerSymbol.createSimple({'name':shape,'size':str((size+1)*factor),'size_unit':'MM',
                                        'color':'#FFFFFF','outline_style':'no','angle':'0'})
    symbol.appendSymbolLayer(QgsSimpleMarkerSymbolLayer.create({'name':shape,'size':str(size*factor),'size_unit':'MM',
        'color':POINT_COLOR,'outline_color':'#951C22','outline_width':str(.25*factor),'outline_width_unit':'MM','angle':'0','joinstyle':'round'}))
    return symbol


def apply_reference_point_symbols(project,layout,main=None):
    """Use earthquake triangles and a separate GNSS star from the study-area map."""
    main=main or layout.referenceMap();assert main
    overrides=main.layerStyleOverrides()
    events=[]
    for layer in main.layers():
        if layer.customProperty('seismic_building/base_key','')=='earthquakes_local' or layer.customProperty('seismic_building/validation_role','')=='epicenter':
            if layer.id() in overrides:QgsMapLayerStyle(overrides[layer.id()]).writeToLayer(layer)
            layer.setRenderer(QgsSingleSymbolRenderer(reference_point_symbol()))
            layer.setLabelsEnabled(False)
            style=QgsMapLayerStyle();style.readFromLayer(layer);overrides[layer.id()]=style.xmlData()
            events.append(layer)
    assert len(events)==2
    main.setLayerStyleOverrides(overrides)
    for item in layout.items():
        if isinstance(item,QgsLayoutItemLabel) and (item.id().startswith('Historical_event_') or item.id()=='Event_2026_annotation'):
            format_=item.textFormat();font=format_.font();font.setItalic(True);format_.setFont(font);format_.setColor(QColor(POINT_COLOR));item.setTextFormat(format_)
        if isinstance(item,QgsLayoutItemPolyline) and item.id() in ['Leader_Historical_event_0','Leader_Event_2026_annotation']:
            symbol=item.symbol().clone()
            for sl in symbol.symbolLayers():
                if sl.color()!=QColor('white'):sl.setColor(QColor(POINT_COLOR))
            item.setSymbol(symbol)

    def xy(lon,lat):
        point=QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'),main.crs(),project).transform(QgsPointXY(lon,lat))
        extent=main.extent()
        return (main.pos().x()+(point.x()-extent.xMinimum())/extent.width()*main.sizeWithUnits().width(),
                main.pos().y()+(extent.yMaximum()-point.y())/extent.height()*main.sizeWithUnits().height())

    recent=next(layer for layer in events if layer.customProperty('seismic_building/validation_role','')=='epicenter')
    feature=next(recent.getFeatures())
    anchor=xy(float(feature['longitude']),float(feature['latitude']))
    leader=layout.itemById('Leader_Event_2026_annotation')
    if leader:
        box=layout.itemById('Event_2026_annotation').sceneBoundingRect();center=box.center()
        dx,dy=center.x()-anchor[0],center.y()-anchor[1];distance=(dx*dx+dy*dy)**.5
        edge=min(box.width()/2/abs(dx) if dx else float('inf'),box.height()/2/abs(dy) if dy else float('inf'))
        end=QPointF(center.x()-dx*edge,center.y()-dy*edge)
        start=(anchor[0]+dx/distance*2.8,anchor[1]+dy/distance*2.8)
        left,top=min(start[0],end.x()),min(start[1],end.y())
        symbol=leader.symbol().clone();z=leader.zValue();layout.removeLayoutItem(leader)
        leader=QgsLayoutItemPolyline(QPolygonF([QPointF(start[0]-left,start[1]-top),QPointF(end.x()-left,end.y()-top)]),layout)
        leader.setId('Leader_Event_2026_annotation');leader.setSymbol(symbol);layout.addLayoutItem(leader)
        leader.attemptMove(QgsLayoutPoint(left,top));leader.setZValue(z)
        polygon=leader.nodes()
        actual=leader.mapToScene(QPointF(polygon[0]))
        actual_end=leader.mapToScene(QPointF(polygon[len(polygon)-1]))
        assert abs(actual.x()-start[0])<1e-7 and abs(actual.y()-start[1])<1e-7
        assert abs(actual_end.x()-end.x())<1e-7 and abs(actual_end.y()-end.y())<1e-7

    for name in ['GNSS_station_symbol','GNSS_station_label','Earthquake_legend_symbol','Earthquake_legend_label',
                 'GNSS_legend_symbol','GNSS_legend_label','Historical_eq_legend_symbol','Historical_eq_legend_label',
                 'Event_2026_legend_symbol','Event_2026_legend_label']:
        item=layout.itemById(name)
        if item:layout.removeLayoutItem(item)

    def marker(id_,x,y,gnss=False,legend=False):
        item=QgsLayoutItemMarker(layout);item.setId(id_);item.setSymbol(reference_point_symbol(gnss,legend))
        layout.addLayoutItem(item);item.setReferencePoint(QgsLayoutItem.Middle);item.setBackgroundEnabled(False)
        item.attemptMove(QgsLayoutPoint(x,y));item.setZValue(8)
        center=item.sceneBoundingRect().center()
        assert abs(center.x()-x)<1e-5 and abs(center.y()-y)<1e-5,(id_,center,x,y)
        return item

    def label(id_,text,box,size=8.5,italic=False,color='#24282B',halo=.35):
        item=QgsLayoutItemLabel(layout);item.setId(id_);item.setText(text);item.setMargin(0)
        format_=QgsTextFormat();font=QFont('Arial');font.setPointSizeF(size);font.setBold(True);font.setItalic(italic)
        format_.setFont(font);format_.setSize(size);format_.setColor(QColor(color))
        buffer=QgsTextBufferSettings();buffer.setEnabled(True);buffer.setSize(halo);buffer.setColor(QColor('white'));format_.setBuffer(buffer)
        item.setTextFormat(format_);item.setVAlign(Qt.AlignVCenter);item.setHAlign(Qt.AlignLeft)
        item.setBackgroundEnabled(False);layout.addLayoutItem(item);item.attemptMove(QgsLayoutPoint(*box[:2]));item.attemptResize(QgsLayoutSize(*box[2:]));item.setZValue(9)
        return item

    x,y=xy(GNSS_LONGITUDE,GNSS_LATITUDE)
    marker('GNSS_station_symbol',x,y,True)
    label('GNSS_station_label','GNSS station',(x+4.5,y-3.5,38,7),12,True,POINT_COLOR,.55)
    left=main.pos().x()+2.5;bottom=main.pos().y()+main.sizeWithUnits().height()
    for id_,text,offset,gnss in [('Earthquake','Earthquakes',28.5,False),('GNSS','GNSS station',23,True)]:
        marker(id_+'_legend_symbol',left+2.5,bottom-offset,gnss,True)
        label(id_+'_legend_label',text,(left+7,bottom-offset-2.5,28.5,5))
    record={'earthquake_symbol':'red triangle with white casing','earthquake_size_mm':3.8,'earthquake_color':POINT_COLOR,
            'gnss_symbol':'red five-point star with white casing','gnss_longitude':GNSS_LONGITUDE,'gnss_latitude':GNSS_LATITUDE,
            'gnss_size_mm':6.0,'gnss_label':'GNSS station','gnss_label_font_pt':12,'gnss_label_leader':False,
            'gnss_reference':'01_study_area/qgis/layouts/study_area/build_layout.py and verification.json',
            'legend_entries':['Earthquakes','GNSS station','Faults','Left-lateral'],'background':'transparent'}
    layout.setCustomProperty('seismic_building/reference_point_symbols',str(record))
    return record


def magnitude_notation(layout):
    changed=[]
    for item in layout.items():
        if isinstance(item,QgsLayoutItemLabel) and (item.id().startswith('Historical_event_') or item.id()=='Event_2026_annotation'):
            text=re.sub(r'(?m)^M\s+(\d)',r'Mw \1',item.text())
            item.setText(text)
            changed.append({'id':item.id(),'text':text})
    assert changed and all('\nMw ' in item['text'] for item in changed)
    return changed


def export_layout(layout,out,stem):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    apply_street_boundaries(layout.project(),layout)
    point_symbols=apply_reference_point_symbols(layout.project(),layout)
    layout.renderContext().setDpi(EXPORT_DPI)
    layout.refresh();exporter=QgsLayoutExporter(layout)
    settings=QgsLayoutExporter.ImageExportSettings();settings.dpi=EXPORT_DPI
    stage=out/('.'+stem+'_1200dpi_stage.png')
    assert exporter.exportToImage(str(stage),settings)==QgsLayoutExporter.Success
    stage.replace(out/(stem+'_1200dpi.png'))
    from qgis_paths import map_source_path
    delivery_stem='Kunming_Building_Hazard_Streets' if stem=='Kunming_Building_Hazard' else stem
    delivery=map_source_path(delivery_stem+'_1200dpi.png');delivery.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(out/(stem+'_1200dpi.png'),delivery)
    return point_symbols


def save_template(layout,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    context=QgsReadWriteContext();context.setPathResolver(QgsPathResolver(str(path)))
    assert layout.saveAsTemplate(str(path),context)
