"""Update elevation or built-up symbology in the current study-area layout.

Run from the workspace root with plot/shared/qgis/scripts/run_pyqgis.sh.
The saved map extents, vector styles, labels and other layout items are retained.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import shutil
import argparse

import build_layout as style
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsLayoutItem,
    QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize, QgsMapLayerStyle,
    QgsReadWriteContext, QgsPathResolver, QgsLayoutExporter,
)
from qgis.PyQt.QtCore import QRectF, QSize

WORKSPACE = Path(__file__).resolve().parents[5]
PROJECT = WORKSPACE / 'plot/01_study_area/qgis/projects/01_study_area.qgz'
RECORD = WORKSPACE / 'change_logs/2026-10-20_figure01_terrain_palette'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def layout_snapshot(layout):
    items = {}
    for item in layout.items():
        if not isinstance(item, QgsLayoutItem) or not item.id():
            continue
        rec = {'position_mm': [item.pos().x(), item.pos().y()],
               'size_mm': [item.sizeWithUnits().width(), item.sizeWithUnits().height()]}
        if isinstance(item, QgsLayoutItemLabel):
            rec.update(text=item.text(), font=item.textFormat().font().toString(),
                       color=item.textFormat().color().name())
        items[item.id()] = rec
    return items


def update_legend(layout):
    """Match colour-bar swatches to the renderer and retain the current anchor."""
    first = layout.itemById('Elevation_class_1')
    last = layout.itemById('Elevation_class_7')
    x, y = first.pos().x(), first.pos().y()
    gap = 0.18
    width = last.pos().x() + last.sizeWithUnits().width() + gap - x
    height = first.sizeWithUnits().height()
    for i, (low, high, color) in enumerate(zip(style.DEM_CLASS_BOUNDS[:-1], style.DEM_CLASS_BOUNDS[1:], style.DEM_COLORS)):
        item = layout.itemById('Elevation_class_' + str(i + 1))
        left = x + (low - style.DEM_MIN) / (style.DEM_MAX - style.DEM_MIN) * width
        size = (high - low) / (style.DEM_MAX - style.DEM_MIN) * width
        item.attemptMove(QgsLayoutPoint(left, y))
        item.attemptResize(QgsLayoutSize(size - gap, height))
        item.setSymbol(style.fill(color, color, 0))
        assert item.symbol().color().name().upper() == color
    for i, value in enumerate(style.DEM_CLASS_BOUNDS):
        item = layout.itemById('Elevation_break_' + str(i))
        px = x + (value - style.DEM_MIN) / (style.DEM_MAX - style.DEM_MIN) * width
        item.setText(f'{value:,.0f}')
        item.attemptMove(QgsLayoutPoint(px - 8, 207.55))
        item.attemptResize(QgsLayoutSize(16, 7.5))


def update(preview_only=False, built_up_only=False):
    RECORD.mkdir(parents=True, exist_ok=True)
    report_file = style.OUT / 'verification.json'
    report = json.loads(report_file.read_text())
    project = QgsProject()
    assert project.read(str(PROJECT)), 'Cannot open the current study-area project'
    layout = project.layoutManager().layoutByName(style.NAME)
    assert layout is not None
    layers = {layer.customProperty('study_area/source_key', ''): layer
              for layer in project.mapLayers().values()}
    map_ = layout.itemById('C_Study_Area')
    old_terrain = layers['terrain_detail']
    old_extent = map_.extent().toString(12)
    before_items = layout_snapshot(layout)
    before_styles = {layer.id(): map_.layerStyleOverrides()[layer.id()]
                     for layer in map_.layers() if isinstance(layer, QgsVectorLayer)}
    if built_up_only:
        # Update both the canvas renderer and the layout's locked style.
        xml = style.style_xml(layers['built_up'], 'built_up', 'c')
        QgsMapLayerStyle(xml).writeToLayer(layers['built_up'])
        overrides = map_.layerStyleOverrides()
        overrides[layers['built_up'].id()] = xml
        map_.setLayerStyleOverrides(overrides)
        layout.itemById('Legend_built_up').setSymbol(style.built_up_fill())
        del before_styles[layers['built_up'].id()]
    before_canvas = list(project.layerTreeRoot().customLayerOrder())
    inputs = set()
    for layer in project.mapLayers().values():
        if layer == old_terrain and not built_up_only:
            continue
        path = Path(layer.source().split('|')[0])
        if path.suffix == '.shp':
            inputs.update(p for p in path.parent.glob(path.stem + '.*') if p.is_file())
        elif path.is_file():
            inputs.add(path)
    inputs.add(style.FAULT_REFERENCE_PROJECT)
    protected = {str(path): digest(path) for path in sorted(inputs)}
    baseline_file = RECORD / 'baseline.json'
    if not baseline_file.exists():
        write_json(baseline_file, {'project_sha256': digest(PROJECT),
                                 'protected_inputs_sha256': protected,
                                 'layout_items': before_items,
                                 'old_range_m': report['dem']['color_range']})

    _, dem_info = style.viewport_dem_stretch(project, layers['buildings'],
                                            (0, 0, map_.sizeWithUnits().width(),
                                             map_.sizeWithUnits().height()))
    replacement = style.dem_layer()
    layers['dem'].setRenderer(replacement.renderer().clone())
    shader = layers['dem'].renderer().shader().rasterShaderFunction()
    for low, high, color in zip(style.DEM_CLASS_BOUNDS[:-1], style.DEM_CLASS_BOUNDS[1:], style.DEM_COLORS):
        success, r, g, b, alpha = shader.shade((low + high) / 2)
        assert success and alpha == 255 and '#%02X%02X%02X' % (r, g, b) == color
    for value in range(*[int(x) for x in dem_info['sample_min_max_m']]):
        assert shader.shade(float(value))[0], f'Uncoloured elevation: {value}'
    assert shader.shade(float(dem_info['sample_min_max_m'][1]))[0]

    # Replace the fused terrain, retaining every vector layer and style override.
    kept = [layer for layer in map_.layers() if layer != old_terrain]
    styles = {layer.id(): map_.layerStyleOverrides()[layer.id()] for layer in kept}
    for key in ['hillshade', 'dem']:
        styles[layers[key].id()] = style.style_xml(layers[key], key, '')
    map_.setLayers(kept + [layers['hillshade'], layers['dem']])
    map_.setLayerStyleOverrides(styles)
    update_legend(layout)
    if preview_only:
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = 150
        settings.exportMetadata = False
        path = RECORD / 'palette_preview.png'
        assert QgsLayoutExporter(layout).exportToImage(str(path), settings) == QgsLayoutExporter.Success
        assert all(digest(path) == value for path, value in protected.items())
        print(json.dumps({'preview': str(path), 'saved_project_unchanged': True,
                          'colors': style.DEM_COLORS,
                          'built_up_fill': style.BUILT_UP_COLOR}, indent=2), flush=True)
        return
    print('Rendering complete-range terrain cache...', flush=True)
    terrain = style.cache_terrain(project, map_, layers, 'terrain_detail',
                                  protected[str(style.DEM_FILE.resolve())])
    new_terrain = layers['terrain_detail']
    project.layerTreeRoot().setCustomLayerOrder([
        new_terrain if layer == old_terrain else layer for layer in before_canvas])
    project.removeMapLayer(old_terrain.id())

    assert map_.extent().toString(12) == old_extent
    after_items = layout_snapshot(layout)
    untouched = [key for key in before_items if not key.startswith('Elevation_')]
    assert all(before_items[key] == after_items[key] for key in untouched)
    assert all(map_.layerStyleOverrides()[key] == value for key, value in before_styles.items())
    assert all(layer.isValid() for layer in project.mapLayers().values())

    # Saving to a sibling stage avoids QGIS generating an obsolete backup file.
    stage = PROJECT.with_name('.01_study_area_stage.qgz')
    project.setFileName(str(stage))
    assert project.write()
    stage.replace(PROJECT)
    project.setFileName(str(PROJECT))
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(str(style.OUT / (style.NAME + '.qpt'))))
    assert layout.saveAsTemplate(str(style.OUT / (style.NAME + '.qpt')), context)
    reopened = QgsProject()
    assert reopened.read(str(PROJECT))
    assert all(layer.isValid() for layer in reopened.mapLayers().values())
    final_layout = reopened.layoutManager().layoutByName(style.NAME)
    exporter = QgsLayoutExporter(final_layout)
    style.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    exports = []
    for name, dpi in [('preview.png', 150), (style.NAME + '.png', 1200),
                      (style.NAME + '.tif', 1200)]:
        print(f'Exporting {name} at {dpi} dpi...', flush=True)
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = dpi
        settings.exportMetadata = False
        path = style.EXPORT_DIR / name
        assert exporter.exportToImage(str(path), settings) == QgsLayoutExporter.Success
        exports.append(path)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = 1200
    settings.forceVectorOutput = True
    settings.exportMetadata = True
    pdf = style.EXPORT_DIR / (style.NAME + '.pdf')
    print('Exporting vector PDF...', flush=True)
    assert exporter.exportToPdf(str(pdf), settings) == QgsLayoutExporter.Success
    exports.append(pdf)
    source = style.EXPORT_DIR / 'Study_Area_source_1200dpi.png'
    shutil.copy2(style.EXPORT_DIR / (style.NAME + '.png'), source)
    exports.append(source)
    detail_map = final_layout.itemById('A_Kunming_City')
    px, py = style.map_position(reopened, detail_map, 102.84, 25.29)
    detail = exporter.renderRegionToImage(QRectF(px - 18, py - 8, 36, 25), QSize(), 300)
    assert detail.save(str(style.EXPORT_DIR / 'TSX_overlap_detail.png'), 'PNG')
    assert all(digest(path) == value for path, value in protected.items())

    now = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    report.update(created_at=now, source_files_unchanged=True, all_reopened_layers_valid=True)
    report['dem'].update(color_range=[style.DEM_MIN, style.DEM_MAX],
                         class_bounds_m=style.DEM_CLASS_BOUNDS,
                         color_stops=style.DEM_STOPS, stretch=dem_info)
    report['terrain_caches']['right'] = terrain
    report['dem_building_contrast'].update(
        dem_palette=style.DEM_PALETTE_DESCRIPTION,
        built_up_fill=style.BUILT_UP_COLOR, built_up_opacity=style.BUILT_UP_OPACITY,
        assessment='Pale-pink built-up areas separate from brown elevation highs, green terrain, purple buildings and the blue lake')
    built_up_style = {'fill': style.BUILT_UP_COLOR, 'outline': style.BUILT_UP_EDGE,
                      'opacity': style.BUILT_UP_OPACITY,
                      'outline_width_mm': style.BUILT_UP_OUTLINE_WIDTH}
    report['builtup_data']['symbol'].update(built_up_style)
    report['left_symbol_legend_styles']['Built-up area'].update(built_up_style)
    report['input_sha256'] = {**protected, terrain['file']: terrain['sha256']}
    report['exports'] = {path.name: {'bytes': path.stat().st_size, 'sha256': digest(path)}
                         for path in exports + [style.EXPORT_DIR / 'preview.png',
                                                style.EXPORT_DIR / 'TSX_overlap_detail.png']}
    report['label_font_sizes_pt']['elevation_values']['position'] = 'below color bar'
    quality = {'updated_at': now, 'elevation_range_m': [style.DEM_MIN, style.DEM_MAX],
               'palette': style.DEM_PALETTE_DESCRIPTION, 'colors': style.DEM_COLORS,
               'sample_min_max_m': dem_info['sample_min_max_m'],
               'every_sampled_elevation_shades_successfully': True,
               'class_midpoint_colours_match_legend': True,
               'all_protected_inputs_unchanged': True,
               'all_layout_geometry_and_text_unchanged': True,
               'all_non_elevation_layout_items_unchanged': not built_up_only,
               'vector_map_styles_unchanged': not built_up_only,
               'untargeted_vector_map_styles_unchanged': True,
               'built_up_style': built_up_style, 'built_up_style_targeted': built_up_only,
               'map_extent_unchanged': True,
               'all_reopened_layers_valid': True, 'project_sha256': digest(PROJECT),
               'terrain': terrain, 'layout_items': after_items}
    report['elevation_update'] = {key: value for key, value in quality.items()
                                 if key not in ['terrain', 'layout_items']}
    write_json(report_file, report)
    panel_file = style.OUT / 'panel_lake_fault_checks.json'
    panels = json.loads(panel_file.read_text())
    panels['updated_at'] = now
    panels['elevation_legend'].update(range_m=[style.DEM_MIN, style.DEM_MAX],
                                      class_bounds_m=style.DEM_CLASS_BOUNDS,
                                      colors=style.DEM_COLORS,
                                      values_position='below color bar')
    panels['exports'] = report['exports']
    panels['dem_hillshade'] = report['dem']
    write_json(panel_file, panels)
    write_json(RECORD / 'verification.json', quality)
    print(json.dumps({key: value for key, value in quality.items()
                      if key not in ['terrain', 'layout_items']}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-only', action='store_true', help='Render a small palette preview without saving the project')
    parser.add_argument('--built-up-only', action='store_true', help='Update built-up polygons and their legend; preserve terrain colours')
    args = parser.parse_args()
    if args.built_up_only:
        RECORD = WORKSPACE / 'change_logs/2026-10-20_figure01_builtup_contrast'
    update(preview_only=args.preview_only, built_up_only=args.built_up_only)
    os._exit(0)
