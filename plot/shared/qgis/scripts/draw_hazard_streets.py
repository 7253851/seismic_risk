"""Draw a township/subdistrict hazard map using the saved Kunming style pack."""
from qgis_paths import export_path
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import copy
import hashlib
import json
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from qgis.core import *
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument
from qgis_paths import ROOT, PROJECT, EXPORTS
from save_indicator_framework_style import layer_key
from revise_hazard_layout import spatial_audit, previous, map_polygon
from map_series_support import export_layout

PACK = ROOT/'shared/styles/Kunming_Indicator_Framework_Distribution'
TARGET = ROOT/'04_seismic_hazard/qgis/projects/04_seismic_hazard_streets.qgz'
OUT = export_path('hazard_streets')
TEMPLATE = ROOT/'04_seismic_hazard/qgis/layouts/hazard_streets/Kunming_Hazard_PGA_Streets.qpt'
LAYOUT_NAME = 'Kunming_Hazard_PGA_Streets'
FIVE_DISTRICTS = ['五华区','盘龙区','西山区','官渡区','呈贡区']
COUNTY_BOUNDARY_PT = 2.0
COUNTY_BOUNDARY_COLOR = '#30363A'
STREET_BOUNDARY_PT = 0.6
STREET_BOUNDARY_COLOR = '#9CA4A9'
SHOW_BASEMAP_ROADS = False


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_project(project,target=TARGET,source=PROJECT):
    """Preserve the original GUI settings in the separate street-level project."""
    with tempfile.NamedTemporaryFile(prefix='.map_save_',suffix='.qgz',dir=target.parent,delete=False) as temporary:
        stage = Path(temporary.name)
    try:
        stage.unlink()
        assert project.write(str(stage))
        with zipfile.ZipFile(source) as old,zipfile.ZipFile(stage) as new:
            old_name = next(name for name in old.namelist() if name.endswith('.qgs'))
            new_name = next(name for name in new.namelist() if name.endswith('.qgs'))
            a,b = ET.fromstring(old.read(old_name)),ET.fromstring(new.read(new_name))
            for tag in ['mapcanvas','mapViewDocks','mapViewDocks3D','projectModels','ProjectViewSettings','legend']:
                original = a.find(tag)
                if original is not None:
                    for item in b.findall(tag):
                        b.remove(item)
                    b.append(copy.deepcopy(original))
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as result:
                result.writestr(target.stem+'.qgs',b'<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(b,encoding='utf-8'))
                for info in new.infolist():
                    if not info.filename.endswith('.qgs'):
                        result.writestr(info,new.read(info.filename))
    finally:
        stage.unlink(missing_ok=True)
    project.setFileName(str(target))


def draw():
    OUT.mkdir(parents=True,exist_ok=True)
    TEMPLATE.parent.mkdir(parents=True,exist_ok=True)
    protected = [PROJECT,export_path('Kunming_Building_Hazard_1200dpi.png'),PACK/'style_manifest.json']
    unchanged = {str(path):digest(path) for path in protected}
    style_manifest = json.loads((PACK/'style_manifest.json').read_text())
    for relative,sha in style_manifest['files_sha256'].items():
        assert digest(PACK/relative)==sha,'Saved style changed: '+relative
    project = QgsProject()
    assert project.read(str(PROJECT))
    baseline = project.layoutManager().layoutByName('Kunming_Hazard_PGA')
    old_main = baseline.itemById('Hazard_Main_Map')
    extent, crs = QgsRectangle(old_main.extent()),old_main.crs()
    pga_positions = {name:[baseline.itemById(name).pos().x(),baseline.itemById(name).pos().y()]
                     for name in ['Legend_title']+[f'Legend_{kind}_{n}' for kind in ['class','range'] for n in range(5)]}
    streets = previous.source_layer(project,'seismic_building/base_key','streets')
    assert streets.featureCount()==134
    source_layers = {layer_key(layer):layer for layer in old_main.layers()}
    source_layers['streets'] = streets
    districts = previous.source_layer(project,'seismic_building/base_key','districts')
    district_filter = '"name" IN ('+','.join("'"+name+"'" for name in FIVE_DISTRICTS)+')'
    assert districts.setSubsetString(district_filter)
    assert sorted(str(feature['name']) for feature in districts.getFeatures())==sorted(FIVE_DISTRICTS)
    districts.setName('五大区县级边界 · 五华/盘龙/西山/官渡/呈贡')
    hazard = source_layers['hazard']
    source_hashes = {}
    for layer in list(source_layers.values())+[districts]:
        source = Path(layer.source().split('|')[0])
        paths = [source]
        if source.suffix.lower()=='.shp':
            paths += [source.with_suffix(ext) for ext in ['.dbf','.shx','.prj','.cpg'] if source.with_suffix(ext).exists()]
        for path in paths:
            source_hashes[str(path)] = digest(path)

    layout = QgsPrintLayout(project)
    document = QDomDocument()
    assert document.setContent((ROOT/'04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt').read_text())[0]
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(ROOT/'04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt')))
    items,ok = layout.loadFromTemplate(document,context)
    assert ok
    project.layoutManager().removeLayout(baseline)
    layout.setName(LAYOUT_NAME)
    assert project.layoutManager().addLayout(layout)
    main = layout.itemById('Hazard_Main_Map')
    ordered, overrides = [],{}
    for entry in style_manifest['layers']:
        key = entry['key']
        if key == 'roads' and not SHOW_BASEMAP_ROADS:
            continue
        layer = source_layers[key]
        message,ok = layer.loadNamedStyle(str(PACK/entry['qml']))
        assert ok,message
        if key == 'streets':
            line = layer.renderer().symbol().symbolLayer(0)
            line.setStrokeWidth(STREET_BOUNDARY_PT)
            line.setStrokeWidthUnit(Qgis.RenderUnit.Points)
            line.setStrokeColor(QColor(STREET_BOUNDARY_COLOR))
            layer.setOpacity(1)
        style = QgsMapLayerStyle()
        style.readFromLayer(layer)
        overrides[layer.id()] = style.xmlData()
        ordered.append(layer)
    main.setLayers(ordered)
    main.setKeepLayerSet(True)
    main.setKeepLayerStyles(True)
    main.setFollowVisibilityPreset(False)
    main.setFollowVisibilityPresetName('')
    main.setLayerStyleOverrides(overrides)
    main.setCrs(crs)
    main.zoomToExtent(extent)
    project.setCrs(crs)
    project.setTitle('Kunming building seismic hazard - county and subdistrict boundaries')
    layout.setCustomProperty('seismic_building/administrative_level','five_counties_and_township_subdistrict')
    layout.setCustomProperty('seismic_building/style_pack',str(PACK))
    project.setCustomVariables(dict(project.customVariables(),hazard_administrative_level='five_counties_and_township_subdistrict'))
    root = project.layerTreeRoot()
    for node in root.findLayers():
        node.setItemVisibilityChecked(node.layerId() in overrides)
    for layer in ordered:
        node = root.findLayer(layer.id())
        while node and node is not root:
            node.setItemVisibilityChecked(True)
            node = node.parent()
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(ordered+[layer for layer in project.mapLayers().values() if layer.id() not in overrides])
    for name,position in pga_positions.items():
        item = layout.itemById(name)
        assert [item.pos().x(),item.pos().y()]==position
    assert main.layers()[4].id()==districts.id() and main.layers()[5].id()==streets.id()
    assert districts.featureCount()==5
    assert main.extent().toString(12)==extent.toString(12)
    assert main.grid().annotationTextFormat().size()==12
    assert not layout.itemById('Overview_scale').hasBackground()
    assert not layout.itemById('True_North_Arrow').hasBackground()
    audit,classes = spatial_audit(hazard,districts,extent,extent,crs,project)
    original_report = json.loads((export_path('hazard_print_report.json')).read_text())
    assert audit['new_total']==original_report['main_building_count']
    assert audit['chenggong_new']==audit['chenggong_source']
    assert classes==original_report['main_class_counts']
    clip = map_polygon(extent,crs,streets.crs(),project)
    visible = [feature for feature in streets.getFeatures() if feature.geometry().intersects(clip)]
    print(json.dumps({'administrative_source_count':streets.featureCount(),'administrative_visible_count':len(visible),
                      'building_audit':audit,'street_boundary_pt':STREET_BOUNDARY_PT,'county_boundary_pt':COUNTY_BOUNDARY_PT,
                      'county_names':FIVE_DISTRICTS},ensure_ascii=False),flush=True)
    export_layout(layout,OUT,'Kunming_Building_Hazard_Streets')
    context.setPathResolver(QgsPathResolver(str(TEMPLATE)))
    assert layout.saveAsTemplate(str(TEMPLATE),context)
    assert all(digest(path)==sha for path,sha in source_hashes.items())
    assert all(digest(path)==sha for path,sha in unchanged.items())
    save_project(project)
    check = QgsProject()
    assert check.read(str(TARGET))
    restored = check.layoutManager().layoutByName(LAYOUT_NAME)
    assert restored
    restored_main = restored.itemById('Hazard_Main_Map')
    assert len(restored_main.layers())==(10 if SHOW_BASEMAP_ROADS else 9) and all(layer.isValid() for layer in restored_main.layers())
    assert any(layer.customProperty('seismic_building/print_base','')=='roads' for layer in restored_main.layers())==SHOW_BASEMAP_ROADS
    assert restored_main.layers()[4].featureCount()==5
    assert Path(restored_main.layers()[5].source()).name=='kunming_streets.shp'
    assert restored_main.extent().toString(12)==extent.toString(12)
    assert all(digest(path)==sha for path,sha in unchanged.items())
    report = {'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'project':str(TARGET),'layout':LAYOUT_NAME,
              'png':str(OUT/'Kunming_Building_Hazard_Streets_1200dpi.png'),'export_format':'PNG','export_dpi':1200,'template':str(TEMPLATE),'style_pack':str(PACK),
              'administrative_level':'five county-level districts + township/subdistrict','administrative_source':streets.source(),
              'county_boundary_source':districts.source(),'county_names':FIVE_DISTRICTS,'county_count':5,'county_filter':district_filter,
              'county_boundary_pt':COUNTY_BOUNDARY_PT,'county_boundary_color':COUNTY_BOUNDARY_COLOR,
              'street_boundary_pt':STREET_BOUNDARY_PT,'street_boundary_color':STREET_BOUNDARY_COLOR,
              'county_above_streets':True,'lake_above_both_administrative_levels':True,
              'basemap_roads_visible':SHOW_BASEMAP_ROADS,
              'administrative_source_count':streets.featureCount(),'administrative_visible_count':len(visible),
              'visible_units':[{'county':str(feature['县']),'township_subdistrict':str(feature['乡'])} for feature in visible],
              'administrative_boundary_pt':streets.renderer().symbol().symbolLayer(0).strokeWidth(),
              'map_extent':extent.toString(12),'page_mm':[195,211],'building_audit':audit,'main_class_counts':classes,
              'layer_order':[layer.name() for layer in ordered],'source_sha256':source_hashes,
              'all_source_data_unchanged':True,'source_style_pack_unchanged':True,'original_map_unchanged':True,
              'saved_project_reload_success':True,'all_map_layers_valid':True,'pga_legend_position_unchanged':True,
              'transparent_lower_left_legend_and_scale':True,'map_annotations':original_report['map_annotation_entries'],
              'county_names_retained_as_geographic_context':True,'township_labels_added':False}
    (OUT/'hazard_streets_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Saved '+str(TARGET),flush=True)


if __name__ in ('__main__','__console__'):
    if not QgsApplication.instance():
        app = QgsApplication([],False)
        app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True)
        app.initQgis()
    draw()
    from qgis.utils import iface
    if not iface:
        os._exit(0)
