"""Run only the isolated drawing function, reusing saved profile statistics."""
from pathlib import Path
import json,importlib.util,sys,re

D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text())
R=Path(S['root']);B=Path(S['backup']);SCALE=180/248;F=S['font_targets_a4_pt']

def main():
    assert D.is_relative_to(R/'plot')
    source=D/'source/draw_risk_transects.py'
    text=(R/'plot/10_risk_transects/code/draw_risk_transects.py').read_text().split('\ndef main():')[0]
    changes={
        'handletextpad=.4,columnspacing=.9,labelspacing=.15,':'handletextpad=.4,columnspacing=.9,labelspacing=.04,',
        'PLOT_OUT = ROOT / "plot/10_risk_transects/output"':'PLOT_OUT = Path('+repr(str(D/'work'))+')',
        'labelsize=7.7':'labelsize='+repr(F['axis_ticks']/SCALE),
        'fontsize=6.5':'fontsize='+repr(F['bar_legend']/SCALE),
        'fontsize=7.5':'fontsize='+repr(F['peaks']/SCALE),
        'fontsize=7.3':'fontsize='+repr(F['sample_n']/SCALE),
        'fontsize=8,labelpad=3':'fontsize='+repr(F['axis_titles']/SCALE)+',labelpad=3',
        'fontsize=7.8':'fontsize='+repr(F['chart_titles']/SCALE),
        'fontsize=8.5':'fontsize='+repr(F['transect_tags']/SCALE),
        'fontsize=7,title_fontsize=7.1':'fontsize='+repr(F['map_legend_classes']/SCALE)+',title_fontsize='+repr(F['map_legend_title']/SCALE),
        'fontsize=6.7':'fontsize='+repr(F['map_symbols']/SCALE),
        "    with Image.open(map_report['png']) as image:\n        map_axis.imshow(np.asarray(image.convert('RGB')),interpolation='none',\n                        extent=(0,native_width,native_height,0),origin='upper')":"    # Map is exported separately from its editable QGIS layout.\n    map_axis.patch.set_alpha(0)",
        'fig.savefig(preview,dpi=220);fig.savefig(png,dpi=dpi)':'fig.savefig(preview,dpi=220,transparent=True);fig.savefig(png,dpi=dpi,transparent=True)',
        'fig.savefig(pdf,dpi=600,metadata=':'fig.savefig(pdf,dpi=600,transparent=True,metadata=',
        '    fig.canvas.draw();renderer=fig.canvas.get_renderer();page=fig.bbox':'''    # Freeze the original xlabel anchors before the changed tick font can
    # make Matplotlib automatically recalculate the label positions.
    saved=[]
    for axis in fig.axes[1:]:
        ticks=axis.get_xticklabels()
        saved.append((axis,axis.xaxis.label.get_fontsize(),[(t,t.get_fontsize()) for t in ticks]))
        axis.xaxis.label.set_fontsize(8)
        for t in ticks:t.set_fontsize(7.7)
    fig.canvas.draw()
    anchors=[]
    for axis,fontsize,ticks in saved:
        label=axis.xaxis.label
        point=fig.transFigure.inverted().transform(label.get_transform().transform(label.get_position()))
        label.set_fontsize(fontsize)
        for tick,size in ticks:tick.set_fontsize(size)
        axis.xaxis.set_label_coords(*point,transform=fig.transFigure)
        anchors.append({'text':label.get_text(),'native_figure_anchor':[float(v) for v in point]})
    # Paper-size fonts: lift any x-axis title that would fall below the chart page.
    fig.canvas.draw();_r=fig.canvas.get_renderer()
    for axis,_,_ in saved:
        label=axis.xaxis.label;box=label.get_window_extent(_r);margin=0.4/25.4*fig.dpi
        if box.y0<margin:
            x,y=label.get_position();axis.xaxis.set_label_coords(x,y+(margin-box.y0)/fig.bbox.height,transform=fig.transFigure)
            anchors.append({'text':label.get_text(),'lifted_mm':(margin-box.y0)/fig.dpi*25.4})
    (PLOT_OUT/'xlabel_anchor_audit.json').write_text(json.dumps(anchors,indent=2)+'\\n')
    fig.canvas.draw();renderer=fig.canvas.get_renderer();page=fig.bbox''',
        '    plt.close(fig)':'''    drawing=[]
    for axis in fig.axes[1:]:
        drawing.append({'box':list(axis.get_position().bounds),'xlim':list(axis.get_xlim()),'ylim':list(axis.get_ylim()),
            'xticks':list(axis.get_xticks()),'yticks':list(axis.get_yticks()),
            'bars':[{'x':p.get_x(),'y':p.get_y(),'width':p.get_width(),'height':p.get_height(),'color':list(p.get_facecolor())} for p in axis.patches],
            'lines':[{'x':list(l.get_xdata()),'y':list(l.get_ydata()),'color':l.get_color()} for l in axis.lines]})
    (PLOT_OUT/'drawing_state.json').write_text(json.dumps(drawing,indent=2,default=float)+'\\n')
    fig.savefig(PLOT_OUT/'chart_overlay_native.svg',transparent=True)
    plt.close(fig)'''
    }
    audit=[]
    for old,new in changes.items():
        pattern=re.escape(old)+r'(?![\d.])'
        text,count=re.subn(pattern,lambda m:new,text);assert count>0,old
        audit.append({'old':old,'new':new,'occurrences':count})
    text+='\n# The original analysis/publishing main() is deliberately omitted.\n'
    source.write_text(text)
    support=D/'source/transect_support.py'
    st=(R/'plot/10_risk_transects/code/transect_support.py').read_text()
    st=st.replace('ROOT = Path(__file__).resolve().parents[3]','ROOT = Path('+repr(str(R))+')')
    st=st.replace('FINAL_OUT = ROOT / "figures/10_risk_transects"','FINAL_OUT = Path('+repr(str(D/'work/not_published'))+')')
    support.write_text(st)
    sys.path.insert(0,str(D/'source'))
    spec=importlib.util.spec_from_file_location('draft_transect_plot',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    import pandas as pd
    from shapely.geometry import LineString
    manifest=json.loads((R/'plot/10_risk_transects/output/figure_manifest.json').read_text())
    profiles={}
    for code,p in manifest['profiles'].items():
        base=R/'result/statistics/Risk/transect';folder=base if code=='AB' else base/'CD'
        stats=pd.read_csv(folder/'segment_statistics.csv');sensitivity=pd.read_csv(folder/'buffer_width_sensitivity.csv')
        assert int(stats.building_count.sum())==p['buildings']
        assert stats.building_count.tolist()==p['segment_building_counts']
        profiles[code]={'line':LineString([(0,0),(p['length_km']*1000,0)]),
            'selected':range(p['buildings']),'stats':stats,'color':p['color'],
            'sensitivity':[g.reset_index(drop=True) for _,g in sensitivity.groupby('half_width_m',sort=True)]}
    report=module.draw(profiles,manifest['qgis_map'],600)
    assert report['panel_boxes_mm']==manifest['outputs']['panel_boxes_mm']
    assert report['map_frame_mm']==manifest['outputs']['map_frame_mm']
    report.update({'source_edits':audit,'font_targets_a4_pt':F,'a4_scale':SCALE,
        'original_panel_boxes_and_axes_preserved':True,'data_recomputed':True,
        'analysis_and_publish_main_removed':True})
    (D/'chart_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'pdf':report['pdf'],'local_legends_audited':len(report['legend_audit']),'no_formal_writes':True},ensure_ascii=False))

if __name__=='__main__':main()
