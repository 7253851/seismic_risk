"""Generate the manuscript-sized figure 4 plan and text-free vector chart assets.

The PyQGIS companion creates an editable A4 layout from this plan. Draft only.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import hashlib
import math
import os
import subprocess
os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/seismic_risk_mpl')
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.colors import to_hex
from matplotlib.backends.backend_agg import FigureCanvasAgg

WORKSPACE = next(p for p in Path(__file__).resolve().parents
                 if (p / 'plot/figure_index.json').is_file())
PAPER_WIDTH_MM = 139.91075904
SOURCE_WIDTH_MM = 307.848
SCALE = PAPER_WIDTH_MM / SOURCE_WIDTH_MM
MAP_SOURCE_SCALE = .9918463084999442 * SCALE
# Draft output; the adopted files in layout/ itself are never written.
LAYOUT_WORK = WORKSPACE / 'plot/04_seismic_hazard/layout/work'
CHART_FONTS_PT = {
    'axis_titles': 8., 'ticks': 7., 'ranking_labels': 6.5,
    'pie_percentages': 9., 'pie_legend': 6.5,
    'class_names': 6.5, 'thresholds': 8.,
    # Unspecified elements retain their current manuscript sizes.
    'statistics': 16 * SCALE, 'line_legend': 18 * SCALE,
}
MAP_FONTS_PT = {
    'districts': 7., 'lake': 7., 'faults': 6., 'events_gnss': 6.,
    'coordinates': 6.5, 'legend_title': 6., 'legend_classes': 6.,
    'north': 10.5 * MAP_SOURCE_SCALE,
    'scale_bar': 8 * MAP_SOURCE_SCALE,
    'symbol_legend': 8.5 * MAP_SOURCE_SCALE,
}


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def import_source():
    path = WORKSPACE / 'plot/04_seismic_hazard/code/build_pga_abcd.py'
    spec = importlib.util.spec_from_file_location('figure04_original', path)
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    for variable, role in {
        'AXIS_PT': 'axis_titles', 'TICK_PT': 'ticks',
        'FAULT_LABEL_PT': 'ranking_labels', 'PIE_PERCENT_PT': 'pie_percentages',
        'PIE_LEGEND_PT': 'pie_legend', 'CLASS_PT': 'class_names',
        'THRESHOLD_PT': 'thresholds', 'STATISTICS_PT': 'statistics',
        'LINE_LEGEND_PT': 'line_legend',
    }.items():
        setattr(source, variable, CHART_FONTS_PT[role] / SCALE)
    return source


def chart_texts(fig):
    result = []
    for ax in fig.axes:
        result.extend(ax.texts)
        if ax.axison:
            result.extend([ax.xaxis.label, ax.yaxis.label,
                           *ax.get_xticklabels(), *ax.get_yticklabels()])
        if ax.get_legend():
            result.extend(ax.get_legend().get_texts())
    return list(dict.fromkeys(t for t in result if t.get_visible() and t.get_text()))


def save_chart(fig, name, position_mm, output):
    FigureCanvasAgg(fig)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_pixel = 25.4 * SCALE / fig.dpi
    width_mm, height_mm = fig.get_size_inches() * (25.4 * SCALE)
    labels = []
    texts = chart_texts(fig)
    for index, text in enumerate(texts):
        bbox = text.get_window_extent(renderer)
        halo = max([getattr(effect, '_gc', {}).get('linewidth', 0)
                    for effect in text.get_path_effects()] or [0])
        labels.append({
            'id': f'{name}_text_{index:03d}', 'text': text.get_text(),
            'font_pt': float(text.get_fontsize() * SCALE),
            'bold': text.get_fontweight() in ['bold', 'heavy', 700],
            'italic': text.get_fontstyle() == 'italic',
            'color': to_hex(text.get_color()),
            'rotation': -float(text.get_rotation()),
            'horizontal_alignment': text.get_ha(),
            'line_spacing': 1.2 if text._linespacing == 'normal' else float(text._linespacing),
            'center_mm': [position_mm[0] + (bbox.x0 + bbox.x1) / 2 * mm_per_pixel,
                          position_mm[1] + height_mm - (bbox.y0 + bbox.y1) / 2 * mm_per_pixel],
            'matplotlib_bbox_mm': [bbox.width * mm_per_pixel, bbox.height * mm_per_pixel],
            'halo_mm': halo * SCALE * 25.4 / 72 / 2,
            'background': text.get_bbox_patch() is not None,
        })
    # The graphics retain their vector geometry, while every visible text item
    # is added as a native, independently editable QGIS layout label.
    for text in fig.findobj(matplotlib.text.Text):
        text.set_visible(False)
    path = output / 'assets' / f'{name}_graphics.svg'
    fig.savefig(path, format='svg', transparent=True)
    return {'id': name, 'svg': str(path), 'position_mm': position_mm,
            'size_mm': [float(width_mm), float(height_mm)], 'labels': labels}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=LAYOUT_WORK)
    parser.add_argument('--plan-only', action='store_true', help='Prepare charts and the plan without running PyQGIS')
    args = parser.parse_args()
    output = args.output.resolve()
    if not any(output.is_relative_to(root.resolve()) for root in (LAYOUT_WORK, WORKSPACE / 'drafts')):
        parser.error('Output must remain inside plot/04_seismic_hazard/layout/work or workspace/drafts.')
    (output / 'assets').mkdir(parents=True, exist_ok=True)
    source = import_source()
    source.set_style()
    meta = json.loads((source.WORK / 'layout_metadata.json').read_text())
    manifest = json.loads((source.DATA / 'manifest.json').read_text())
    for relative, rec in manifest['files'].items():
        assert digest(source.DATA / relative) == rec['sha256'], relative
    crop_meta = json.loads(source.SOURCE_LAYOUT.read_text())
    assert digest(source.MAP) == crop_meta['sources'][0]['sha256']
    ranking = source.read_csv(source.DATA / 'b_fault_contributions/top10_fault_ranking.csv')
    pie = source.read_csv(source.DATA / 'b_fault_contributions/dominant_fault_shares.csv')
    bins = source.read_csv(source.DATA / 'c_pga_histogram/histogram_bins.csv')
    stats = source.read_csv(source.DATA / 'c_pga_histogram/summary_statistics.csv')
    classes = source.read_csv(source.DATA / 'c_pga_histogram/pga_class_breaks.csv')
    assert int(bins.Building_Count.sum()) == int(pie.Building_Count.sum()) == 57228
    crop = crop_meta['content_crops']['a']
    height = source.MAP_WIDTH * (crop[3] - crop[1]) / (crop[2] - crop[0])
    right_x = source.OUTER + source.MAP_WIDTH + source.COLUMN_GAP
    right_width = source.WIDTH - right_x - source.OUTER
    d_y = source.TOP_Y + height + source.ROW_GAP
    origin = [(210 - PAPER_WIDTH_MM) / 2, 25.]
    figures = []
    original_save = Figure.savefig
    try:
        Figure.savefig = lambda fig, *a, **kw: figures.append(fig)
        source.render_fault_panels(output / 'unused_bc.png', right_width, height, 150,
                                   ranking, pie, source.map_frame_top(crop))
        source.render_d(output / 'unused_d.png', source.WIDTH - 2 * source.OUTER,
                        source.HISTOGRAM_HEIGHT, 150, bins, stats, classes)
    finally:
        Figure.savefig = original_save
    assert len(figures) == 2
    mm = lambda inches: inches * 25.4 * SCALE
    charts = [
        save_chart(figures[0], 'bc', [origin[0] + mm(right_x), origin[1] + mm(source.TOP_Y)], output),
        save_chart(figures[1], 'd', [origin[0] + mm(source.OUTER), origin[1] + mm(d_y)], output),
    ]
    native_origin = [origin[0] + mm(source.OUTER) - crop[0] / 1200 * 25.4 * MAP_SOURCE_SCALE,
                     origin[1] + mm(source.TOP_Y) - crop[1] / 1200 * 25.4 * MAP_SOURCE_SCALE]
    plan = {'workspace': str(WORKSPACE), 'output': str(output), 'page_mm': [210., 297.],
            'figure_origin_mm': origin, 'figure_width_mm': PAPER_WIDTH_MM,
            'figure_height_mm': PAPER_WIDTH_MM * meta['pixels'][1] / meta['pixels'][0],
            'composite_scale': SCALE, 'map_scale': MAP_SOURCE_SCALE,
            'map_origin_mm': native_origin, 'map_fonts_pt': MAP_FONTS_PT,
            'chart_fonts_pt': CHART_FONTS_PT, 'charts': charts,
            'panel_identifiers_removed': True,
            'source_data_sha256': {k: v['sha256'] for k, v in manifest['files'].items()},
            'source_map_sha256': digest(source.MAP), 'buildings': 57228,
            'histogram_bins': len(bins), 'ranking_bars': len(ranking)}
    (output / 'a4_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'plan': str(output / 'a4_plan.json'),
                      'native_chart_text_items': sum(len(x['labels']) for x in charts),
                      'map_fonts_pt': MAP_FONTS_PT, 'chart_fonts_pt': CHART_FONTS_PT}, indent=2), flush=True)
    if not args.plan_only:
        native = Path(__file__).with_name('build_a4_layout.py')
        if not native.exists():
            native = WORKSPACE / 'plot/04_seismic_hazard/qgis/layouts/hazard/build_a4_layout.py'
        subprocess.run([str(WORKSPACE / 'plot/shared/qgis/scripts/run_pyqgis.sh'),
                        str(native), '--plan', str(output / 'a4_plan.json')], check=True)


if __name__ == '__main__':
    main()
