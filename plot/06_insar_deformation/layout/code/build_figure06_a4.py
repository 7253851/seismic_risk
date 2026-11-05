#!/usr/bin/env python3
"""Replot Figure 6 from original QGIS/statistics sources; draft outputs only."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/seismic_risk_mpl')
sys.path.insert(0, str(ROOT/'project/code'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.text import Text
import pandas as pd

# User clarified that the figure need not keep the manuscript insertion width.
# Retain the original 180 x 163 mm composition on A4 with 15 mm side margins.
SCALE = 1.0
ORIGIN_MM = [15., 25.]
MAP_SCALE = 112. / 195.0861111111111 * SCALE
FONTS = {
    'districts': 7., 'lake': 7., 'faults': 6.5, 'events_gnss': 6.5,
    'coordinates': 6.5, 'map_legend': 6., 'colorbar_title': 7.,
    'colorbar_ticks': 5.5, 'histogram_titles': 7., 'histogram_ticks': 6.,
    'histogram_thresholds': 6., 'histogram_statistics': 6.,
    'pie_main_percentage': 8., 'pie_small_percentages': 7., 'pie_legend': 6.5,
    'gnss_ticks': 7., 'gnss_displacement_title': 6., 'gnss_legend': 6.5,
    'gnss_rate_distance': 6.5,
    # Not specified in this request: retain the existing physical paper sizes.
    'north': 4.9603976, 'scale_bar': 5.5143421, 'panel_labels': 10.,
}
# Figure 6 is inserted at full text width (468.3324 pt = 165.2178 mm) while the
# exported figure is 180.0437 mm wide. Enlarge every font so that the sizes seen
# in the paper equal the A4 targets above.
PAPER_TEXTWIDTH_MM = 466.5828/72*25.4  # measured printed width of the figure in the compiled paper
FIGURE_WIDTH_MM = 4270/600*25.4  # exported crop width including panel letters
PAPER_FACTOR = FIGURE_WIDTH_MM/PAPER_TEXTWIDTH_MM
PAPER_TARGETS = dict(FONTS)
FONTS = {k: v*PAPER_FACTOR for k, v in FONTS.items()}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    assert OUTPUT.is_relative_to(ROOT/'plot')
    path = ROOT/'plot/06_insar_deformation/code/build_deformation_figure.py'
    spec = importlib.util.spec_from_file_location('figure06_original', path)
    source = importlib.util.module_from_spec(spec); spec.loader.exec_module(source)
    # Only call the read-only plotting functions. Never call source.main(),
    # prepare_map() or any function which can publish formal outputs.
    source.STATISTICS_FONT_PT = FONTS['histogram_statistics']/SCALE
    source.PIE_SMALL_PERCENT_PT = FONTS['pie_small_percentages']/SCALE
    source.PIE_MAIN_PERCENT_PT = FONTS['pie_main_percentage']/SCALE
    source.PIE_LEGEND_FONT_PT = FONTS['pie_legend']/SCALE
    source.GNSS_Y_LABEL_FONT_PT = FONTS['gnss_displacement_title']/SCALE
    # InSAR rate values are displacement (terminology aligned with the revised manuscript).
    _text_mm = source.text_mm
    source.text_mm = lambda fig, x, y, text, **kw: _text_mm(
        fig, x, y, text.replace('Vertical deformation rate', 'Vertical displacement rate'), **kw)
    summary = json.loads((source.RATE/'run_manifest.json').read_text())['summary']
    table = pd.read_csv(source.RATE/'deformation_rate_histogram.csv')
    classes = pd.read_csv(source.RATE/'deformation_rate_classes.csv')
    assert int(table.ps_count.sum()) == int(classes.ps_count.sum()) == summary['valid_rate_points'] == 4911956
    map_export = json.loads((ROOT/'plot/06_insar_deformation/output/layout_manifest.json').read_text())['map_export']
    style = {'font.family': 'Arial', 'font.weight': 'bold', 'font.size': 8.,
             'axes.labelsize': FONTS['histogram_titles']/SCALE, 'axes.labelweight': 'bold',
             'axes.linewidth': .7, 'axes.spines.top': False, 'axes.spines.right': False,
             'xtick.labelsize': FONTS['histogram_ticks']/SCALE,
             'ytick.labelsize': FONTS['histogram_ticks']/SCALE,
             'xtick.major.width': .65, 'ytick.major.width': .65,
             'xtick.major.size': 2.4, 'ytick.major.size': 2.4, 'axes.labelpad': 3.,
             'pdf.fonttype': 42, 'svg.fonttype': 'path',
             'axes.unicode_minus': False, 'figure.facecolor': 'none'}
    with plt.rc_context(style):
        fig = plt.figure(figsize=(source.WIDTH/25.4, source.HEIGHT/25.4), dpi=160)
        source.map_details(fig)
        for text in fig.texts:
            role = 'colorbar_title' if text.get_text().startswith('Vertical displacement') else 'colorbar_ticks'
            text.set_fontsize(FONTS[role]/SCALE)
        source.map_legend(fig)
        legend_ax = fig.axes[-1]
        for text in legend_ax.texts:
            text.set_fontsize(FONTS['map_legend']/SCALE)
        source.map_scale(fig, map_export)  # unchanged size/physical ruler length
        for text in fig.axes[-1].texts:
            text.set_fontsize(FONTS['scale_bar']/SCALE)
        source.histogram(fig, summary, table)
        hist = fig.axes[-1]
        for text in hist.texts:
            role = 'histogram_thresholds' if text.get_text() in ['-4.5', '+4.5'] else 'histogram_statistics'
            text.set_fontsize(FONTS[role]/SCALE)
            if role == 'histogram_statistics':
                text.set_fontfamily('Arial'); text.set_fontweight('normal')
        source.pie(fig, summary)
        pie_ax = fig.axes[-1]
        source.gnss_panel(fig)
        gnss = fig.axes[-1]
        gnss.tick_params(axis='both', labelsize=FONTS['gnss_ticks']/SCALE)
        for text in gnss.texts:
            role = 'gnss_displacement_title' if text.get_text().startswith('Vertical displacement') else 'gnss_rate_distance'
            text.set_fontsize(FONTS[role]/SCALE)
            if role == 'gnss_displacement_title': text.set_fontweight('normal')
        # Change font sizes while retaining physical handles, padding and anchors.
        old = gnss.get_legend(); old.remove()
        handles, labels = gnss.get_legend_handles_labels()
        ratio = 7.8*SCALE/FONTS['gnss_legend']
        gnss.legend([handles[i] for i in [0,2,1,3]], [labels[i] for i in [0,2,1,3]],
                    loc='upper left', bbox_to_anchor=(0.,1.), ncol=4,
                    fontsize=FONTS['gnss_legend']/SCALE,
                    handlelength=2*ratio, handletextpad=.8*ratio,
                    columnspacing=1.3*ratio, borderaxespad=.35*ratio,
                    borderpad=.4*ratio, frameon=False)
        fig.canvas.draw()
        texts=[]; renderer=fig.canvas.get_renderer()
        for t in fig.findobj(Text):
            if t.get_visible() and t.get_text():
                b=t.get_window_extent(renderer)
                texts.append({'text':t.get_text(), 'actual_pt':t.get_fontsize()*SCALE,
                              'weight':str(t.get_fontweight()),
                              'bbox_mm':[b.x0*25.4/fig.dpi*SCALE,
                                         (fig.bbox.height-b.y1)*25.4/fig.dpi*SCALE,
                                         b.width*25.4/fig.dpi*SCALE,b.height*25.4/fig.dpi*SCALE]})
        source.audit_fonts(fig)
        # Record numerical artists for comparing against the adopted inventory.
        graphics = {
            'histogram_ps_count': int(table.ps_count.sum()),
            'histogram_xlim': list(hist.get_xlim()), 'histogram_ylim': list(hist.get_ylim()),
            'histogram_xticks': list(map(float,hist.get_xticks())), 'histogram_yticks': list(map(float,hist.get_yticks())),
            'gnss_xlim': list(gnss.get_xlim()), 'gnss_ylim': list(gnss.get_ylim()),
            'gnss_series': [{'label':line.get_label(), 'x':list(map(float,line.get_xdata(orig=False))),
                             'y':list(map(float,line.get_ydata())), 'color':line.get_color()}
                            for line in gnss.lines],
            'axes_positions': [list(ax.get_position().bounds) for ax in fig.axes],
            'pie_percentages': summary['class_percentages'], 'colors': source.COLORS,
        }
        overlay = OUTPUT/'chart_overlay.pdf'
        fig.savefig(overlay, transparent=True, bbox_inches=None)
        fig.savefig(OUTPUT/'assets/chart_overlay.svg', transparent=True, bbox_inches=None)
        plt.close(fig)
    plan = {
        'root':str(ROOT), 'output':str(OUTPUT), 'page_mm':[210.,297.],
        'figure_size_mm':[180.,163.],
        'figure_origin_mm':ORIGIN_MM, 'composite_scale':SCALE,
        'map_scale':MAP_SCALE,
        'map_origin_mm':[ORIGIN_MM[0]+.3*SCALE,ORIGIN_MM[1]-.5*SCALE],
        'fonts_pt':FONTS, 'overlay_pdf':str(overlay),
        'overlay_svg':str(OUTPUT/'assets/chart_overlay.svg'),
        'source_texts':texts,'graphics':graphics,'statistics':summary,
        'position_adjustments':[],
    }
    write_json(OUTPUT/'a4_plan.json',plan)
    print(json.dumps({'plan':str(OUTPUT/'a4_plan.json'),'chart_text_count':len(texts)},indent=2),flush=True)
    subprocess.run([str(ROOT/'plot/shared/qgis/scripts/run_pyqgis.sh'),
                    str(Path(__file__).with_name('build_map_a4.py'))],check=True)
    subprocess.run([sys.executable,
                    '-B',str(Path(__file__).with_name('merge_and_verify.py'))],check=True)


if __name__=='__main__': main()
