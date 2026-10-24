"""Save the Kunming Indicator Framework Distribution style without changing the working project."""
from qgis_paths import export_path
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import base64
import hashlib
import json
import os
import shutil

from qgis.core import *
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument
from qgis_paths import ROOT, PROJECT, EXPORTS

PACK = ROOT/'shared/styles/Kunming_Indicator_Framework_Distribution'
NAMES = {
    'event_2026':'2026 地震', 'earthquakes':'2023 地震', 'faults':'断层',
    'dianchi':'滇池', 'districts':'县级行政边界', 'streets':'乡镇／街道行政边界', 'hazard':'Indicator',
    'waterways':'河流', 'roads':'道路', 'hillshade':'灰色山体阴影',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def embed_svg(symbol):
    """Make SVG marker symbols self-contained in QML and style-library XML."""
    for layer in symbol.symbolLayers():
        if isinstance(layer, QgsSvgMarkerSymbolLayer):
            path = layer.path()
            if not path.startswith('base64:'):
                asset = Path(path)
                if not asset.is_file():
                    asset = ROOT/'04_seismic_hazard/qgis/layouts/hazard'/Path(path).name
                assert asset.is_file(), path
                layer.setPath('base64:'+base64.b64encode(asset.read_bytes()).decode('ascii'))
        child = layer.subSymbol()
        if child:
            embed_svg(child)


def layer_key(layer):
    for property_, key in [
        ('seismic_building/validation_role','epicenter'),
        ('seismic_building/base_key','earthquakes_local'),
        ('seismic_building/result_key','hazard'),
    ]:
        if layer.customProperty(property_,'') == key:
            return {'epicenter':'event_2026','earthquakes_local':'earthquakes','hazard':'hazard'}[key]
    key = layer.customProperty('seismic_building/base_key','')
    if key in ['faults','dianchi','districts','streets']:
        return key
    key = layer.customProperty('seismic_building/print_base','')
    assert key in ['roads','waterways','hillshade'], layer.name()
    return key


def save():
    protected = [PROJECT, ROOT/'04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt',
                 export_path('Kunming_Building_Hazard_1200dpi.png')]
    before = {str(p):digest(p) for p in protected}
    for sub in ['layer_styles','layout_templates','symbols']:
        (PACK/sub).mkdir(parents=True,exist_ok=True)
    for filename in ['north_arrow.svg','left_lateral_arrows.svg']:
        shutil.copy2(ROOT/'04_seismic_hazard/qgis/layouts/hazard'/filename, PACK/'symbols'/filename)
    project = QgsProject()
    assert project.read(str(PROJECT))
    layout = project.layoutManager().layoutByName('Kunming_Hazard_PGA')
    assert layout
    main = layout.itemById('Hazard_Main_Map')
    library = QgsStyle()
    clones, entries, portable_overrides = [], [], {}
    original_overrides = main.layerStyleOverrides()
    for order, source in enumerate(main.layers(),1):
        key = layer_key(source)
        layer = source.clone()
        clones.append(layer)
        if source.id() in original_overrides:
            QgsMapLayerStyle(original_overrides[source.id()]).writeToLayer(layer)
        if isinstance(layer,QgsVectorLayer):
            renderer = layer.renderer()
            for symbol in renderer.symbols(QgsRenderContext()):
                embed_svg(symbol)
            if isinstance(renderer,QgsRuleBasedRenderer):
                unnamed = [0]
                def collect(rule):
                    if rule.symbol():
                        name = rule.label()
                        if not name:
                            unnamed[0] += 1
                            name = (['主要道路','次要道路','其他道路'][unnamed[0]-1]
                                    if key == 'roads' else '默认 '+str(unnamed[0]))
                        symbol_name = NAMES[key]+' / '+name
                        assert symbol_name not in library.symbolNames()
                        assert library.addSymbol(symbol_name,rule.symbol().clone())
                    for child in rule.children():
                        collect(child)
                collect(renderer.rootRule())
            elif isinstance(renderer,QgsSingleSymbolRenderer):
                assert library.addSymbol(NAMES[key],renderer.symbol().clone())
        path = PACK/'layer_styles'/('indicator.qml' if key == 'hazard' else key+'.qml')
        categories = QgsMapLayer.Symbology | QgsMapLayer.Labeling | QgsMapLayer.Rendering | QgsMapLayer.Legend
        message, ok = layer.saveNamedStyle(str(path),categories)
        assert ok and path.exists(),message
        reloaded = source.clone()
        message, ok = reloaded.loadNamedStyle(str(path))
        assert ok,message
        assert reloaded.isValid()
        if isinstance(layer,QgsVectorLayer):
            assert reloaded.renderer().type() == layer.renderer().type()
            assert len(reloaded.renderer().symbols(QgsRenderContext())) == len(layer.renderer().symbols(QgsRenderContext()))
        else:
            assert reloaded.renderer().type() == layer.renderer().type()
            assert abs(reloaded.renderer().opacity()-layer.renderer().opacity())<1e-9
        style = QgsMapLayerStyle()
        style.readFromLayer(reloaded)
        portable_overrides[source.id()] = style.xmlData()
        entries.append({'order_top_to_bottom':order,'key':key,'name':NAMES[key],
                        'source_layer':source.name(),'qml':str(path.relative_to(PACK)),
                        'qml_reload_success':True})
    assert len(entries)==9
    assert [entry['key'] for entry in entries]==['event_2026','earthquakes','faults','dianchi','districts','streets','hazard','waterways','hillshade']
    # Roads are hidden in the authoritative street-level style.
    (PACK/'layer_styles/roads.qml').unlink(missing_ok=True)

    for id_, name in [('Earthquake_legend_symbol','图例 / 地震'),('GNSS_legend_symbol','图例 / GNSS station'),('GNSS_station_symbol','GNSS station'),
                      ('Fault_legend_symbol','图例 / 断层'),('Left_lateral_legend_symbol','图例 / 左旋断层')]:
        item = layout.itemById(id_)
        symbol = item.symbol().clone()
        embed_svg(symbol)
        item.setSymbol(symbol)
        assert library.addSymbol(name,item.symbol().clone())
    north = layout.itemById('True_North_Arrow')
    north.setPicturePath(str(PACK/'symbols/north_arrow.svg'))
    north_symbol = QgsMarkerSymbol()
    svg = QgsSvgMarkerSymbolLayer(str(PACK/'symbols/north_arrow.svg'))
    north_symbol.changeSymbolLayer(0,svg)
    embed_svg(north_symbol)
    assert library.addSymbol('指北针 / 黑色',north_symbol)
    for id_, name in [('Wuhua','行政区名 / Arial Bold 14 pt'),('Dian_Lake','滇池 / Arial Bold 18 pt'),
                      ('Fault_Puduhe','断层名 / Arial Bold 11.5 pt'),('Historical_event_0','2023 地震标注 / Arial Bold 12 pt'),
                      ('Event_2026_annotation','2026 地震标注 / Arial Bold 12 pt'),('North_text','指北针 N / Arial Bold 10.5 pt'),
                      ('Earthquake_legend_label','图内图例 / Arial Bold 8.5 pt'),('GNSS_station_label','GNSS 标注 / Arial Bold 12 pt')]:
        assert library.addTextFormat(name,layout.itemById(id_).textFormat())
    assert library.addTextFormat('经纬度 / Arial Bold 12 pt',main.grid().annotationTextFormat())
    assert library.addTextFormat('比例尺 / Arial Bold 8 pt',layout.itemById('Overview_scale').textFormat())
    report = json.loads((export_path('hazard_print_report.json')).read_text())
    gray = report['hillshade']['color_ramp']
    ramp = QgsGradientColorRamp(QColor(gray[0][1]),QColor(gray[-1][1]),False,
                               [QgsGradientStop(value/255,QColor(color)) for value,color in gray[1:-1]])
    assert library.addColorRamp('山体阴影 / 中性灰',ramp)
    palette = report['classes']
    ramp = QgsGradientColorRamp(QColor(palette[0]['color']),QColor(palette[-1]['color']),True,
                               [QgsGradientStop(index/5,QColor(palette[index]['color'])) for index in range(1,5)])
    assert library.addColorRamp('Indicator / Five-class warm palette',ramp)
    xml = PACK/'Kunming_Indicator_Framework_Distribution.xml'
    assert library.exportXml(str(xml))
    imported = QgsStyle()
    assert imported.importXml(str(xml))
    assert sorted(imported.symbolNames()) == sorted(library.symbolNames())
    assert sorted(imported.textFormatNames()) == sorted(library.textFormatNames())
    assert sorted(imported.colorRampNames()) == sorted(library.colorRampNames())

    # Remove the thematic PGA legend from the reusable framework template.
    removed_legend_ids = []
    for item in list(layout.items()):
        if hasattr(item, 'id') and item.id().startswith('Legend_'):
            removed_legend_ids.append(item.id())
            layout.removeLayoutItem(item)
    assert len(removed_legend_ids) == 11, removed_legend_ids
    layout.setName('Kunming_Indicator_Framework_Distribution')
    main.setId('Indicator_Main_Map')
    main.setLayerStyleOverrides(portable_overrides)
    (PACK/'layer_styles/hazard.qml').unlink(missing_ok=True)
    template = PACK/'layout_templates/Kunming_Indicator_Framework_Distribution.qpt'
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(template)))
    assert layout.saveAsTemplate(str(template),context)
    document = QDomDocument()
    assert document.setContent(template.read_text())[0]
    restored = QgsPrintLayout(project)
    items, ok = restored.loadFromTemplate(document,context)
    assert ok and restored.itemById('Indicator_Main_Map')
    assert Path(restored.itemById('True_North_Arrow').picturePath()).is_file()
    assert not restored.itemById('Overview_scale').hasBackground()
    assert not any(item.id().startswith('Legend_') for item in restored.items() if hasattr(item, 'id'))
    restored.refresh()
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = 180
    assert QgsLayoutExporter(restored).exportToImage(str(PACK/'style_preview.png'),settings) == QgsLayoutExporter.Success
    assert all(digest(path)==value for path,value in before.items()),'Working project or exports changed'
    manifest = {'saved_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                'source_project':str(PROJECT),'name':'Kunming Indicator Framework Distribution','layout':'Kunming_Indicator_Framework_Distribution','layers':entries,
                'pga_legend_included':False,'removed_legend_ids':removed_legend_ids,
                'administrative_level':'five county-level districts + township/subdistrict',
                'county_boundary_pt':2.0,'street_boundary_pt':.6,'basemap_roads_visible':False,
                'symbols':library.symbolNames(),'text_formats':library.textFormatNames(),'color_ramps':library.colorRampNames(),
                'style_library_reimport_success':True,'template_reload_success':True,
                'svg_markers_embedded':True,'working_project_and_exports_unchanged':True,
                'working_files_sha256':before,
                'layout_settings':{key:report[key] for key in ['page_mm','font_family','graticule_font_size_pt','graticule_tick_length_mm',
                    'graticule_tick_width_mm','building_outline_pt','district_boundary_pt','map_frame_width_mm','context_legend_entries',
                    'context_legend_position','context_legend_background','scale_bar_km','map_annotation_entries']}}
    manifest['files_sha256']={str(p.relative_to(PACK)):digest(p) for p in PACK.rglob('*') if p.is_file() and p.name not in ['style_manifest.json','README.md']}
    (PACK/'style_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'folder':str(PACK),'qml_count':len(entries),'symbol_count':len(library.symbolNames()),
                      'text_format_count':len(library.textFormatNames()),'color_ramp_count':len(library.colorRampNames()),
                      'template_reload_success':True,'working_project_and_exports_unchanged':True},ensure_ascii=False),flush=True)


if __name__ in ('__main__','__console__'):
    if not QgsApplication.instance():
        app = QgsApplication([],False)
        app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True)
        app.initQgis()
    save()
    from qgis.utils import iface
    if not iface:
        os._exit(0)
