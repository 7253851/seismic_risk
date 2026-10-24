"""Use the original plotting helpers and saved valid cohort, without a model run."""
from pathlib import Path
import importlib.util
import json
import shutil
import os

D=Path(__file__).resolve().parents[1]
R=Path(json.loads((D/'session.json').read_text())['root'])
os.environ['MPLCONFIGDIR']=str(D/'work/mplconfig')
import sys;sys.path.insert(0,str(D.parents[1]/'shared/layout_tools'))
import font_scaling
K=json.loads((D/'paper_scale.json').read_text())['7']
source=R/'plot/07_ibsi/code/plot_IBSI_components_and_spatial_distribution.py'
spec=importlib.util.spec_from_file_location('original_ibsi',source)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
work=D/'work/ibsi';work.mkdir(exist_ok=True)
m.OUT=work
for name in ['native_QGIS_map_manifest.json','IBSI_native_QGIS_map.png']:
    shutil.copy2(R/'plot/07_ibsi/output'/name,work/name)
all_b,_=m.readonly_gpkg(m.SOURCE,m.LAYER)
valid=all_b.loc[all_b.Vul_Valid.eq(1)].copy()
assert len(all_b)==57228 and len(valid)==41939
m.plt.rcParams.update({'font.family':'Arial','font.weight':'bold','axes.labelweight':'bold',
                      'font.size':8,'axes.linewidth':.85,'text.color':'#222a30',
                      'axes.labelcolor':'#222a30','xtick.color':'#222a30','ytick.color':'#222a30',
                      'axes.titleweight':'bold','savefig.facecolor':'white',
                      'figure.facecolor':'white','axes.unicode_minus':False,
                      'pdf.fonttype':42,'svg.fonttype':'none'})
fig=m.plt.figure(figsize=(m.WIDTH_MM/25.4,m.HEIGHT_MM/25.4),dpi=150)
# The old make_map() also checks an earlier Figure 4 project and historical
# GeoPackage file hashes. Those files have since been maintained. This draft
# uses the saved Figure 7 project instead; only its unchanged legend is drawn
# here, with the original positioning and font measurements.
native=json.loads((work/'native_QGIS_map_manifest.json').read_text())
assert native['inventory_N']==len(all_b) and native['valid_IBSI_N']==len(valid)
display=native['display_classification'];edges=display['breaks']
assert sum(display['counts'])==len(valid)
labels=[f'{edges[i]:.3f}–{edges[i+1]:.3f}' for i in range(5)]+['No valid IBSI']
renderer=fig.canvas.get_renderer()
def width_mm(text,point):
    w,_,_=renderer.get_text_width_height_descent(text,m.FontProperties(family='Arial',weight='bold',size=point),False)
    return w*25.4/fig.dpi
title_width=width_mm('IBSI',7.5*K);widths=[width_mm(t,7.2*K) for t in labels]
swatch_width,swatch_gap,item_gap,title_gap=2.5,1.,3.2,3.
total=title_width+title_gap+sum(swatch_width+swatch_gap+w for w in widths)+5*item_gap
x,y=(m.WIDTH_MM-total)/2,m.IBSI_LEGEND_CENTER_Y_MM
fig.text(x/m.WIDTH_MM,y/m.HEIGHT_MM,'IBSI',fontsize=7.5*K,ha='left',va='center',gid='IBSI_legend_title')
x+=title_width+title_gap
for i,(color,label,width) in enumerate(zip([*display['colors'],m.GRAY],labels,widths)):
    fig.add_artist(m.Rectangle((x/m.WIDTH_MM,(y-.8)/m.HEIGHT_MM),swatch_width/m.WIDTH_MM,
                              1.6/m.HEIGHT_MM,transform=fig.transFigure,facecolor=color,edgecolor='none'))
    fig.text((x+swatch_width+swatch_gap)/m.WIDTH_MM,y/m.HEIGHT_MM,label,fontsize=7.2*K,
             ha='left',va='center',gid=f'IBSI_legend_entry_{i}')
    x+=swatch_width+swatch_gap+width+item_gap
map_audit={'source_project':str(R/'plot/07_ibsi/qgis/projects/07_ibsi.qgz'),
           'legend_unchanged':False,'map_rendered_separately':True}
axes,settings=m.histograms(fig,valid)
layout=m.check_layout(fig,axes)
for t in fig.findobj(m.matplotlib.text.Text):
    if t.get_text().strip() in ['(a)','(b)','(c)','(d)']:t.set_visible(False)
legend_ids={t.get_gid() for t in fig.texts if (t.get_gid() or '').startswith('IBSI_legend')}
for t in fig.texts:
    if t.get_gid() in legend_ids:t.set_fontsize(t.get_fontsize()/K)  # already sized; undo the uniform pass
font_scaling.scale_mpl(fig,K)
# Keep enlarged in-panel statistics inside their histogram frames.
fig.canvas.draw();renderer=fig.canvas.get_renderer()
for ax in fig.axes:
    for t in ax.texts:
        box=t.get_window_extent(renderer);right=ax.bbox.x1-0.8/25.4*fig.dpi
        if box.x1>right:
            x,y=t.get_position();shift=(box.x1-right)/ax.bbox.width
            t.set_position((x-shift,y)) if t.get_transform()==ax.transAxes else None
fig.savefig(D/'work/figure07_charts.pdf',transparent=True)
fig.savefig(D/'work/figure07_charts.svg',transparent=True)
report={'cohort_n':len(valid),'all_histogram_bins_counts_percentages_unchanged':False,'data_update':'2026-10-22 vertical-rate correction',
        'layout':layout,'histogram_settings':settings,'map_audit':map_audit,
        'chart_text':[{'id':t.get_gid(),'text':t.get_text(),'pt':t.get_fontsize(),
                       'family':t.get_fontfamily(),'weight':t.get_fontweight(),
                       'position':list(t.get_position())} for t in fig.findobj(m.matplotlib.text.Text)
                      if t.get_visible() and t.get_text().strip()]}
(D/'chart_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,
    default=lambda o:o.item() if hasattr(o,'item') else list(o))+'\n')
m.plt.close(fig)
print(json.dumps({'charts':'figure07_charts.pdf','cohort':len(valid),'bins_unchanged':True}),flush=True)
