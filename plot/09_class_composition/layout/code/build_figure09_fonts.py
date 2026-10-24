"""Redraw from isolated source helpers and saved statistics, without publishing."""
from pathlib import Path
import importlib.util
import json
import os

D=Path(__file__).resolve().parents[1]
S=json.loads((D/'session.json').read_text());R=Path(S['root'])
os.environ['MPLCONFIGDIR']=str(D/'work/mplconfig')
os.environ['XDG_CACHE_HOME']=str(D/'work/cache')
spec=importlib.util.spec_from_file_location('isolated_figure09',D/'source/draw_charts.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SCALE=180/m.COMPOSITE_MM[0]
F=S['fonts_pt']


def geometry(ax):
    return {'axes_fraction':list(ax.get_position().bounds),'xlim':list(ax.get_xlim()),
            'ylim':list(ax.get_ylim()),'xticks':list(ax.get_xticks()),'yticks':list(ax.get_yticks()),
            'bars':[{'x':p.get_x(),'y':p.get_y(),'width':p.get_width(),'height':p.get_height(),
                     'facecolor':list(p.get_facecolor()),'edgecolor':list(p.get_edgecolor()),
                     'linewidth':p.get_linewidth()} for p in ax.patches]}


def main():
    assert D.is_relative_to(R/'plot')
    m.style()
    frames=[m.load(p) for p in m.PANELS]
    fig=m.plt.figure(figsize=tuple(mm/25.4 for mm in m.COMPOSITE_MM),dpi=600)
    axes=[fig.add_axes(bounds) for bounds in m.COMPOSITE_AXES]
    for index,(ax,panel,frame) in enumerate(zip(axes,m.PANELS,frames)):
        # Build with the original identifier so the original tick limit is kept.
        m.draw_panel(ax,panel,frame,identifier=f'({chr(97+index)})')
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    before=[geometry(ax) for ax in axes]
    anchors=[]
    for ax in axes:
        for label,role in [(ax.xaxis.label,'x_axis_title'),(ax.yaxis.label,'y_axis_title')]:
            # Freeze the original alignment anchor before tick text gets smaller.
            point=label.get_transform().transform(label.get_position())
            position=fig.transFigure.inverted().transform(point)
            label.set_transform(fig.transFigure);label.set_position(position)
            label.set_fontsize(F[role]/SCALE);label.set_gid(role)
            anchors.append({'role':role,'figure_fraction':position.tolist()})
        ax.xaxis._autolabelpos=False;ax.yaxis._autolabelpos=False
        for text in ax.get_xticklabels():
            text.set_fontsize(F['x_class_labels']/SCALE);text.set_gid('x_class_labels')
        for text in ax.get_yticklabels():
            text.set_fontsize(F['y_tick_labels']/SCALE);text.set_gid('y_tick_labels')
    labels=[]
    for panel_index,ax in enumerate(axes):
        for text in list(ax.texts):
            value=text.get_text()
            if value in ['(a)','(b)','(c)','(d)']:
                text.set_visible(False)
            elif value.startswith('N ='):
                text.set_fontsize(F['sample_size']/SCALE);text.set_gid('sample_size')
            elif '\n' in value and '%' in value:
                count,percentage=value.split('\n')
                text.set_text(percentage);text.set_fontsize(F['percentages']/SCALE)
                text.set_gid('percentages')
                labels.append((ax,text,count,percentage,panel_index))
            else:raise ValueError('Unexpected panel annotation: '+repr(value))
    fig.canvas.draw();renderer=fig.canvas.get_renderer()
    count_anchors=[]
    for ax,percentage_text,count,percentage,index in labels:
        # Retain the original 3.5 pt source offset from the bar for the lower
        # percentage line, and place the count 0.5 A4 pt above its text box.
        height=percentage_text.get_window_extent(renderer).height*72/fig.dpi
        offset=3.5+height+.5/SCALE
        text=ax.annotate(count,percentage_text.xy,xytext=(0,offset),textcoords='offset points',
                         ha='center',va='bottom',fontsize=F['counts']/SCALE,
                         fontfamily='Arial',fontweight='bold',color='black',gid='counts')
        count_anchors.append({'panel':index+1,'count':count,'percentage':percentage,
                              'bar_anchor_data':list(percentage_text.xy),
                              'percentage_bottom_offset_a4_pt':3.5*SCALE,
                              'count_bottom_offset_a4_pt':offset*SCALE,
                              'interline_gap_a4_pt':.5})
    fig.canvas.draw();renderer=fig.canvas.get_renderer()
    after=[geometry(ax) for ax in axes]
    assert before==after,'Axes, bars, counts, colors or limits changed'
    visible=[t for t in fig.findobj(m.Text) if t.get_visible() and t.get_text().strip()]
    boxes=[(t,t.get_window_extent(renderer)) for t in visible]
    clipped=[t.get_text() for t,b in boxes if b.x0<0 or b.y0<0 or b.x1>fig.bbox.width or b.y1>fig.bbox.height]
    overlaps=[(a.get_text(),b.get_text()) for i,(a,aa) in enumerate(boxes)
              for b,bb in boxes[:i] if aa.overlaps(bb)]
    assert not clipped,clipped
    assert not overlaps,overlaps
    assert all(t.get_text() not in ['(a)','(b)','(c)','(d)'] for t in visible)
    assert all(t.get_fontweight() in ['bold',700] for t in visible)
    for t in visible:
        font=m.findfont(t.get_fontproperties(),fallback_to_default=False)
        assert m.FontProperties(fname=font).get_name()=='Arial'
    fig.savefig(D/'work/figure09_native_fonts.pdf')
    fig.savefig(D/'work/figure09_native_fonts.svg')
    report={'source_native_size_mm':list(m.COMPOSITE_MM),'a4_scale':SCALE,
        'target_fonts_a4_pt':F,'geometry_before':before,'geometry_after':after,
        'axes_bars_colors_limits_ticks_unchanged':True,'axis_title_anchors':anchors,
        'value_annotation_anchors':count_anchors,'panel_ids_removed':True,
        'text_clipping':clipped,'text_overlaps':overlaps,
        'text_font_inventory':[{'role':t.get_gid(),'text':t.get_text(),
            'source_pt':t.get_fontsize(),'a4_pt':t.get_fontsize()*SCALE} for t in visible],
        'saved_data':[{'panel':p['slug'],'N':int(f.building_count.sum()),
                      'counts':[int(v) for v in f.building_count],
                      'percentages':[float(v) for v in f.percentage]}
                     for p,f in zip(m.PANELS,frames)]}
    (D/'drawing_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,
        default=lambda o:o.item() if hasattr(o,'item') else list(o))+'\n')
    m.plt.close(fig)
    print(json.dumps({'native_pdf':'figure09_native_fonts.pdf','visible_text':len(visible),
                      'counts_percentages':len(labels),'all_data_graphics_unchanged':True,
                      'text_overlaps':overlaps,'text_clipping':clipped}),flush=True)


if __name__=='__main__':main()
