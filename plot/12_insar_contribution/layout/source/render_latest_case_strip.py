"""Render the current frozen-baseline paired PS diagnostics without rewriting inputs.

Four panels retain every saved PS node. Scientific definitions follow
case_panel_static_baseline.py; this renderer deliberately never calls diagnostics().
"""
import os
from pathlib import Path
FONT_PT = 9.540511276312778
BASE = Path('/Users/bin/Projects/seismic_risk')
OUT = Path('/Users/bin/Projects/seismic_risk/plot/12_insar_contribution/layout/work')
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(OUT / 'matplotlib_cache'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import hashlib
import json
import sqlite3
import numpy as np
import pandas as pd
from shapely import affinity, wkb
from shapely.geometry import LineString, MultiPoint
from scipy.spatial import Delaunay
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager, patheffects as pe
from matplotlib.colors import Normalize
from matplotlib.collections import LineCollection
from matplotlib.patches import Polygon as MplPolygon

SOURCE = Path('/Users/bin/Projects/seismic_risk/result/discussion/12_insar_contribution/static_baseline')
FILES = [SOURCE / 'data/case_panel_PS_nodes.csv',
         SOURCE / 'data/case_panel_PS_edges.csv',
         SOURCE / 'data/case_panel_diagnostics.json',
         SOURCE / 'data/primary_pair_reassessment.csv',
         SOURCE / 'QGIS/data/static_baseline_5_1.gpkg']
FRAME_GRID_WIDTH_MM, FRAME_GAP_MM = 266.279, 4.0
FRAME_GRID_LEFT_MM, FRAME_GRID_TOP_MM = 8.0, 1.5
WIDTH_MM = FRAME_GRID_LEFT_MM + FRAME_GRID_WIDTH_MM + 1.0
MM = 1 / 25.4
FRAME_PT = 0.45 * 72 / 25.4
AXES_WIDTH_MM = (FRAME_GRID_WIDTH_MM - 3 * FRAME_GAP_MM) / 4
AXES_X = [FRAME_GRID_LEFT_MM + i * (AXES_WIDTH_MM + FRAME_GAP_MM) for i in range(4)]
AXES_BOTTOM_MM = 5.0
VIEW_X, VIEW_Y = [-45.0, 45.0], [-50.0, 57.0]
AXES_HEIGHT_MM = AXES_WIDTH_MM * (VIEW_Y[1]-VIEW_Y[0]) / (VIEW_X[1]-VIEW_X[0])
HEIGHT_MM = FRAME_GRID_TOP_MM + AXES_HEIGHT_MM + AXES_BOTTOM_MM
COLORS = ['#C5433C', '#2875B5']
SHORT = {'Moderate': 'M', 'High': 'H'}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(2 ** 20), b''):
            h.update(chunk)
    return h.hexdigest()


def geom_from_gpkg(blob):
    envelope_code = (blob[3] >> 1) & 7
    offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope_code]
    return wkb.loads(bytes(blob[offset:]))


def draw_outline(ax, geometry, center, color, width, linestyle='-'):
    local = affinity.translate(geometry, xoff=-center[0], yoff=-center[1])
    for poly in getattr(local, 'geoms', [local]):
        ax.plot(*poly.exterior.xy, color=color, lw=width, ls=linestyle, zorder=8)


def put_text(fig, x_mm, top_mm, text, **kwargs):
    return fig.text(x_mm / WIDTH_MM, 1 - top_mm / HEIGHT_MM, text,
                    va='top', fontweight='bold', **kwargs)


def scale_north(ax):
    ax.plot([-40, -30], [-24, -24], color='#20272D', lw=1.8, zorder=12)
    ax.text(-35, -21.0, '10 m', ha='center', fontsize=FONT_PT, weight='bold', zorder=12)
    ax.annotate('N', xy=(.94, .31), xytext=(.94, .18), xycoords='axes fraction',
                ha='center', va='center', fontsize=FONT_PT, weight='bold', color='#20272D',
                arrowprops={'arrowstyle': '-|>', 'lw': 1.3, 'color': '#20272D'}, zorder=12)


def main():
    before = {str(path): digest(path) for path in FILES}
    font_path = font_manager.findfont(font_manager.FontProperties(family='Arial', weight='bold'),
                                      fallback_to_default=False)
    assert 'arial' in font_path.lower(), font_path
    plt.rcParams.update({'font.family': 'Arial', 'font.weight': 'bold',
                         'font.size': FONT_PT, 'axes.labelweight': 'bold', 'axes.titleweight': 'bold',
                         'axes.linewidth': FRAME_PT, 'xtick.major.width': .8,
                         'ytick.major.width': .8, 'svg.fonttype': 'path',
                         'pdf.fonttype': 42, 'figure.facecolor': 'white', 'savefig.facecolor': 'white',
                         'axes.facecolor': 'white', 'text.color': '#161B1F',
                         'axes.labelcolor': '#161B1F', 'xtick.color': '#161B1F', 'ytick.color': '#161B1F'})
    nodes = pd.read_csv(FILES[0]); edges = pd.read_csv(FILES[1])
    stored = json.loads(FILES[2].read_text())
    cases = pd.read_csv(FILES[3], encoding='utf-8-sig').set_index('Build_ID')
    pair_ids = list(stored['building_ids'])
    assert pair_ids == [39899, 39929]
    details = {d['Build_ID']: d for d in stored['diagnostics']}
    db = sqlite3.connect(FILES[4].as_uri() + '?mode=ro&immutable=1', uri=True)
    footprints = {bid: geom_from_gpkg(blob) for bid, blob in db.execute(
        'SELECT Build_ID, geom FROM primary_pair_footprints WHERE Build_ID IN (39899,39929)')}
    db.close()
    assert set(footprints) == set(pair_ids)
    fig = plt.figure(figsize=(WIDTH_MM * MM, HEIGHT_MM * MM))
    rate_norm = Normalize(-9, 1); residual_norm = Normalize(-3, 3)
    panel_checks = []
    axes_manifest = []
    for col, (bid, color) in enumerate(zip(pair_ids, COLORS)):
        case = cases.loc[bid]; diag = details[bid]
        node = nodes[nodes.Build_ID.eq(bid)].sort_values('node')
        edge = edges[edges.Build_ID.eq(bid)]
        assert node.node.to_list() == list(range(len(node)))
        assert len(node) == int(case.PS_Count) == int(diag['unique_PS_locations'])
        geometry = footprints[bid]
        center = np.array([geometry.centroid.x, geometry.centroid.y])
        assert np.linalg.norm(center - case[['centroid_x_utm48n_m', 'centroid_y_utm48n_m']].to_numpy(dtype=float)) < 1e-6
        xy = node[['x', 'y']].to_numpy() - center
        assert (abs(xy) <= 40).all()
        flags = node.gradient_abnormal.to_numpy(dtype=bool)
        assert int(flags.sum()) == diag['gradient_abnormal_n']
        assert np.array_equal(flags, node.point_gradient.to_numpy() > diag['point_gradient_P90'])
        case_x = AXES_X[2 * col]
        transition = SHORT[case.static_class] + ' → ' + SHORT[case.insar_class]
        for j in range(2):
            x = AXES_X[col * 2 + j]
            rect = [x / WIDTH_MM, AXES_BOTTOM_MM / HEIGHT_MM,
                    AXES_WIDTH_MM / WIDTH_MM, AXES_HEIGHT_MM / HEIGHT_MM]
            ax = fig.add_axes(rect)
            local = affinity.translate(geometry, xoff=-center[0], yoff=-center[1])
            for poly in getattr(local, 'geoms', [local]):
                ax.add_patch(MplPolygon(np.array(poly.exterior.coords)[:, :2], facecolor='#F0F2F3',
                                        edgecolor='none', zorder=0))
            draw_outline(ax, geometry.buffer(5), center, '#8F989E', .65, '--')
            draw_outline(ax, geometry, center, color, FRAME_PT)
            if j == 0:
                ax.scatter(xy[:, 0], xy[:, 1], c=node.observed_rate, cmap='viridis', norm=rate_norm,
                           s=14, edgecolors='white', linewidths=.28, zorder=5)
                gx, gy = np.meshgrid(np.linspace(-40, 40, 161), np.linspace(-40, 40, 161))
                world = np.c_[gx.ravel() + center[0], gy.ravel() + center[1]]
                inside = Delaunay(node[['x', 'y']].to_numpy()).find_simplex(world) >= 0
                slopes = np.array([diag['slope_x'], diag['slope_y']])
                plane = diag['mean_fitted_rate'] + (world - np.array([
                    diag['weighted_center_x'], diag['weighted_center_y']])) @ slopes
                field = np.ma.masked_where(~inside.reshape(gx.shape), plane.reshape(gx.shape))
                # A fitted plane has straight level sets. Draw exact analytic
                # contours clipped to the saved PS convex hull, avoiding a new
                # numerical fit or interpolation of the observed rates.
                hull = MultiPoint(xy).convex_hull
                normal = slopes / np.linalg.norm(slopes)
                tangent = np.array([-normal[1], normal[0]])
                weighted_local = np.array([diag['weighted_center_x'], diag['weighted_center_y']]) - center
                angle = float(np.degrees(np.arctan2(tangent[1], tangent[0])))
                if angle > 90: angle -= 180
                if angle < -90: angle += 180
                for level in np.arange(-9, 1.25, .5):
                    anchor = weighted_local + normal * ((level - diag['mean_fitted_rate']) / np.linalg.norm(slopes))
                    clipped = LineString([anchor - tangent * 200, anchor + tangent * 200]).intersection(hull)
                    for line in getattr(clipped, 'geoms', [clipped]):
                        if line.geom_type != 'LineString' or line.length < 1:
                            continue
                        ax.plot(*line.xy, color='#34454F', lw=.65, zorder=4)
                        if line.length >= 18:
                            midpoint = line.interpolate(.55, normalized=True)
                            text = ax.text(midpoint.x, midpoint.y, f'{level:.1f}',
                                           rotation=angle, ha='center', va='center',
                                           fontsize=FONT_PT, fontweight='bold', color='#34454F', zorder=7)
                            text.set_path_effects([pe.withStroke(linewidth=2.2, foreground='white')])
                direction = slopes / np.linalg.norm(slopes)
                start = np.array([diag['weighted_center_x'], diag['weighted_center_y']]) - center - direction * 10
                arrow = ax.annotate('', xy=start + direction * 20, xytext=start,
                                    arrowprops={'arrowstyle': '-|>', 'lw': 1.6, 'color': '#20272D'}, zorder=11)
                arrow.arrow_patch.set_path_effects([pe.Stroke(linewidth=3, foreground='white'), pe.Normal()])
                title = 'Observed rate + fitted plane'
            else:
                segments = xy[edge[['left_node', 'right_node']].to_numpy(dtype=int)]
                ax.add_collection(LineCollection(segments, colors='#C4C9CD', linewidths=.35, alpha=.7, zorder=1))
                ax.scatter(xy[:, 0], xy[:, 1], c=node.residual_rate, cmap='RdBu_r', norm=residual_norm,
                           s=16, edgecolors='white', linewidths=.25, zorder=4)
                ring = ax.scatter(xy[flags, 0], xy[flags, 1], s=38, facecolors='none', edgecolors='#222222',
                                  linewidths=.9, zorder=6)
                ring.set_path_effects([pe.Stroke(linewidth=1.8, foreground='white'), pe.Normal()])
                title = 'Plane residual + local gradient'
            ax.set(xlim=VIEW_X, ylim=VIEW_Y, aspect='equal', xticks=[-30, 0, 30], yticks=[-30, 0, 30])
            information = ([f'{bid}  {transition}', 'Observed rate + fitted plane',
                            f'IBSI {case.IBSI:.3f} | RMS {case.V_RMS:.3f} mm/yr',
                            f'Tilt {case.Tilt_Angle:.6f}°/yr'] if j == 0 else
                           [f'{bid}  {transition}', 'Plane residual + local gradient',
                            f'DGI {case.DGI_Str:.3f} mm/(m yr)',
                            f'PS {int(case.PS_Count)} | Q {case.Q_insar:.3f}',
                            f'Coh {case.PS_CohMn:.3f} | Coverage {case.PS_Cov:.3f}'])
            for row, value in enumerate(information):
                ax.text(.035, 1-(1.4+row*3.65)/AXES_HEIGHT_MM, value,
                        transform=ax.transAxes, ha='left', va='top',
                        fontsize=FONT_PT, fontweight='bold',
                        color=color if row == 0 else '#161B1F', zorder=15,
                        path_effects=[pe.withStroke(linewidth=1.2, foreground='white')])
            ax.tick_params(labelsize=FONT_PT, length=2, pad=2)
            ax.text(.5, .018, 'Local easting (m)', transform=ax.transAxes,
                    fontsize=FONT_PT, fontweight='bold', ha='center', va='bottom', zorder=15)
            if j == 0:
                ax.text(.095, .51, 'Local northing (m)', transform=ax.transAxes,
                        rotation=90, fontsize=FONT_PT, fontweight='bold', ha='left', va='center',
                        zorder=15, path_effects=[pe.withStroke(linewidth=1.2, foreground='white')])
                ax.tick_params(axis='y', direction='in', pad=-14)
            else:
                ax.tick_params(labelleft=False)
            for spine in ax.spines.values():
                spine.set_visible(True); spine.set_linewidth(FRAME_PT)
            for text in ax.get_xticklabels() + ax.get_yticklabels():
                text.set_fontfamily('Arial'); text.set_fontweight('bold')
            scale_north(ax)
            color_norm, color_map, color_title, ticks = (
                (rate_norm, 'viridis', 'Vertical rate (mm/yr)', [-9, -4, 1]) if j == 0 else
                (residual_norm, 'RdBu_r', 'Plane residual (mm/yr)', [-3, 0, 3]))
            cbax = ax.inset_axes([.15, .11, .70, .025])
            cb = fig.colorbar(plt.cm.ScalarMappable(norm=color_norm, cmap=color_map),
                              cax=cbax, orientation='horizontal', ticks=ticks)
            cb.ax.set_title(color_title, fontsize=FONT_PT, pad=2, fontweight='bold')
            cb.ax.tick_params(labelsize=FONT_PT, length=1.5, pad=1)
            cb.ax.patch.set_alpha(0)
            for tick in cb.ax.get_xticklabels():
                tick.set_fontfamily('Arial'); tick.set_fontweight('bold')
            cb.outline.set_linewidth(.6); cb.solids.set_rasterized(False)
            axes_manifest.append({'Build_ID': int(bid), 'type': 'observed_plane' if j == 0 else 'residual_gradient',
                                  'rect_mm_from_bottom_left': [x, AXES_BOTTOM_MM, AXES_WIDTH_MM, AXES_HEIGHT_MM],
                                  'metric_labels_inside_frame':True,'colorbar_inside_frame':True})
        panel_checks.append({'Build_ID': int(bid), 'transition': transition, 'IBSI': float(case.IBSI),
                             'PS_count': len(node), 'all_PS_inside_window': True, 'black_P90_rings': int(flags.sum()),
                             'DGI': float(case.DGI_Str), 'Q': float(case.Q_insar),
                             'center_utm48n_m': center.tolist()})
    svg = OUT / 'latest_case_strip.svg'
    png = OUT / 'latest_case_strip.png'
    preview = OUT / 'latest_case_strip_preview.png'
    # Keep halo paths, then add the identical normal text as an embedded-font
    # artist. This retains the visible halo and makes all PDF text measurable.
    from matplotlib.text import Text
    import copy
    outlined=set()
    for original in list(fig.findobj(Text)):
        if not original.get_visible() or not original.get_text() or not original.get_path_effects():continue
        effects=original.get_path_effects()
        original.set_path_effects([pe.Stroke(**e._gc) for e in effects])
        normal=copy.copy(original);normal.set_path_effects([]);normal.set_zorder(original.get_zorder()+.001)
        original.axes.add_artist(normal);outlined.add(id(original))
    fig.canvas.draw()
    inventory=[]
    for t in fig.findobj(Text):
        if not t.get_visible() or not t.get_text() or id(t) in outlined:continue
        assert abs(t.get_fontsize()-FONT_PT)<1e-10
        inventory.append({'text':t.get_text(),'native_pt':t.get_fontsize(),'family':t.get_fontfamily(),
            'weight':t.get_fontweight(),'target_a4_pt':5.5})
    (OUT/'strip_text_inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    fig.savefig(OUT/'latest_case_strip.pdf',dpi=600)
    fig.savefig(svg, dpi=600)
    fig.savefig(png, dpi=600)
    fig.savefig(preview, dpi=180)
    plt.close(fig)
    after = {str(path): digest(path) for path in FILES}
    assert before == after, 'Source data changed unexpectedly.'
    record = {'width_mm': WIDTH_MM, 'height_mm': HEIGHT_MM, 'dpi': 600,
              'frame_grid_width_mm':FRAME_GRID_WIDTH_MM,'frame_grid_left_mm':FRAME_GRID_LEFT_MM,
              'frame_grid_top_mm':FRAME_GRID_TOP_MM,'frame_gap_mm':FRAME_GAP_MM,
              'subplot_width_mm':AXES_WIDTH_MM,'subplot_height_mm':AXES_HEIGHT_MM,
              'font': 'Arial Bold', 'font_file': font_path, 'font_minimum_pt': 7.5,
              'frame_width_mm': .45, 'frame_width_pt': FRAME_PT,
              'building_ids': pair_ids, 'window_m': [-40, 40, -40, 40],
              'display_extent_m':[VIEW_X[0],VIEW_X[1],VIEW_Y[0],VIEW_Y[1]],
              'annotation_margins_only':True,'metrics_and_colorbars_inside_frames':True,
              'annotation_background':'transparent','outside_frame_text':'coordinate tick values only',
              'rate_bounds': [-9, 1], 'residual_bounds': [-3, 3],
              'PS_checks': panel_checks, 'axes': axes_manifest,
              'fitted_plane_arrow_length_m': 20,
              'fitted_plane_arrow_meaning': stored['arrow_meaning'],
              'plane_contours_limited_to_PS_convex_hull': True,
              'black_rings': stored['black_circles'],
              'observation_period': stored['observation_period'],
              'scientific_interpretation': stored['scientific_interpretation'],
              'source_hashes_before_and_after_equal': True, 'source_hashes': before,
              'outputs': [str(svg), str(png), str(preview)]}
    (OUT / 'case_strip_manifest.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
