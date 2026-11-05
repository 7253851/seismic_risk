#!/usr/bin/env python3
"""Compose the original QGIS risk map with A-B and lake-to-event C-D profiles."""
from datetime import datetime
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from zoneinfo import ZoneInfo

from transect_support import (
    ROOT, CONFIG_PATH, SOURCE, SUMMARY, DATA_OUT, FINAL_OUT, CLASSES, COLORS,
    TEAL, INK, GREY, digest, segment_edges, calculate, save_geodata, format_axis,
)
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.legend_handler import HandlerBase
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Patch
from matplotlib.transforms import Bbox
import numpy as np
import pandas as pd
from PIL import Image
from shapely.geometry import LineString

PLOT_OUT = (Path(__file__).resolve().parents[3] / 'plot/10_risk_transects/layout/work')
STEM = "Kunming_Risk_Transects_AB_CD"
ANALYSIS_COLORS = COLORS
CURVE_COLOR = COLORS[-1]


class LeftLateralHandler(HandlerBase):
    """Retain the map's paired, opposing arrows in its inset symbol key."""
    def create_artists(self, legend, orig_handle, xdescent, ydescent, width, height, fontsize, trans):
        artists=[]
        for fraction, reverse in ((.72,False),(.28,True)):
            start,end=(0,width) if not reverse else (width,0)
            artists.append(FancyArrowPatch((start-xdescent,height*fraction-ydescent),
                                          (end-xdescent,height*fraction-ydescent),
                                          transform=trans,arrowstyle='->',mutation_scale=4.2,
                                          lw=.6,color='#a23d30',shrinkA=0,shrinkB=0))
        return artists


def validate_stats(selected, stats):
    assert selected.Build_ID.is_unique
    assert stats.building_count.sum() == len(selected)
    count_cols = [name.lower().replace(" ", "_") + "_count" for name in CLASSES]
    assert (stats[count_cols].sum(axis=1) == stats.building_count).all()
    pct_cols = [name.lower().replace(" ", "_") + "_pct" for name in CLASSES]
    np.testing.assert_allclose(stats.loc[stats.building_count.gt(0),pct_cols].sum(axis=1),100)
    for ident, group in selected.groupby("segment_id"):
        row=stats.loc[stats.segment_id.eq(ident)].iloc[0]
        assert len(group)==row.building_count
        assert group.Risk_Class.isin(["High","Very High"]).sum()==row.high_very_high_count


def write_analysis(profiles, overlap):
    summaries=[];segments=[];changes=[];phases=[]
    for code,profile in profiles.items():
        selected=profile['selected'];table=profile['stats'].copy()
        row={'transect':code,'length_km':profile['line'].length/1000,'building_count':len(selected),
             'risk_median':float(selected.Risk_Final.median())}
        for label in CLASSES:
            key=label.lower().replace(' ','_');n=int(selected.Risk_Class.eq(label).sum())
            row[key+'_count']=n;row[key+'_pct']=n/len(selected)*100
        row['high_very_high_count']=row['high_count']+row['very_high_count']
        row['high_very_high_pct']=row['high_very_high_count']/len(selected)*100
        summaries.append(row);table.insert(0,'transect',code);segments.append(table)
        for i in range(1,len(table)):
            previous,current=table.iloc[i-1],table.iloc[i]
            delta={'transect':code,'from_segment':int(previous.segment_id),'to_segment':int(current.segment_id),
                   'boundary_km':float(current.start_km)}
            for label in CLASSES:
                key=label.lower().replace(' ','_')+'_pct'
                delta[key.replace('_pct','_change_pp')]=float(current[key]-previous[key])
            delta['high_very_high_change_pp']=float(current.high_very_high_pct-previous.high_very_high_pct)
            changes.append(delta)
    ab=profiles['AB']['stats']
    for start,end in [(0,10),(10,24),(24,float(ab.end_km.iloc[-1]))]:
        subset=ab.loc[(ab.start_km>=start-1e-9)&(ab.end_km<=end+1e-9)]
        n=int(subset.building_count.sum());row={'transect':'AB','start_km':start,'end_km':end,'building_count':n}
        for label in CLASSES:
            key=label.lower().replace(' ','_');count=int(subset[key+'_count'].sum())
            row[key+'_count']=count;row[key+'_pct']=count/n*100
        row['high_very_high_pct']=(row['high_count']+row['very_high_count'])/n*100;phases.append(row)
    outputs={}
    for name,rows in [('grade_summary',summaries),('all_segment_grade_statistics',pd.concat(segments,ignore_index=True)),
                      ('adjacent_segment_changes',changes),('AB_descriptive_phases',phases)]:
        target=DATA_OUT/(name+'.csv');pd.DataFrame(rows).to_csv(target,index=False,encoding='utf-8-sig');outputs[name]=str(target)
    peak=ab.loc[ab.high_very_high_pct.idxmax()];cd=profiles['CD']['stats'];cd_peak=cd.loc[cd.high_very_high_pct.idxmax()]
    text=(f"双线路风险等级变化分析\n\n统计口径：两侧各1 km、质心筛选、按投影里程唯一归属，采用全域五级Jenks等级。常规分段2 km，末段A-B为2.12 km，C-D为2.61 km。\n\n"
          f"纵线A-B：{len(profiles['AB']['selected']):,}栋，34.12 km。高与极高风险总体占比{summaries[0]['high_very_high_pct']:.2f}%。整体呈现先下降、后回升的空间变化。"
          f"0-10 km为{phases[0]['high_very_high_pct']:.2f}%（n={phases[0]['building_count']:,}），10-24 km降至{phases[1]['high_very_high_pct']:.2f}%（n={phases[1]['building_count']:,}），"
          f"24-34.12 km回升至{phases[2]['high_very_high_pct']:.2f}%（n={phases[2]['building_count']:,}）。这些区间仅用于描述既有分段结果，并非另行分级。"
          f"单段最高值出现在{peak.start_km:g}-{peak.end_km:g} km，为{peak.high_very_high_pct:.2f}%（n={int(peak.building_count)}），应结合该段较小的建筑数量判断。\n\n"
          f"横线C-D：{len(profiles['CD']['selected']):,}栋，8.61 km，从滇池北岸向2026年震中附近。高与极高风险总体占比{summaries[1]['high_very_high_pct']:.2f}%。"
          f"四段高风险占比依次为{'、'.join(f'{v:.2f}%' for v in cd.high_very_high_pct)}，先升后降，峰值位于{cd_peak.start_km:g}-{cd_peak.end_km:g} km。"
          f"最后一段为{cd.high_very_high_pct.iloc[-1]:.2f}%，相较首段下降{cd.high_very_high_pct.iloc[0]-cd.high_very_high_pct.iloc[-1]:.2f}个百分点。\n\n"
          f"两条缓冲区共有{overlap:,}栋建筑，分别计入独立剖面；两线样本量不能直接相加为独立建筑总数。等级占比的分母为各段有效建筑数量，"
          "数量图为各等级原始建筑数，不代表面积标准化密度。图中浅色带为0.5、1.0和1.5 km半宽敏感性范围，不是置信区间。空间差异不代表时间变化，也不能据此认定震中距离导致综合风险差异。\n")
    target=DATA_OUT/'risk_grade_analysis_CN.txt';target.write_text(text);outputs['analysis_CN']=str(target)
    return {'summary':summaries,'AB_descriptive_phases':phases,'outputs':outputs}


def draw(profiles, map_report, dpi):
    # Match the supplied reference: compact columns, aligned boxed charts,
    # inside titles and local legends. The native map body is not restyled.
    width_mm,height_mm=248,150
    map_hash=digest(Path(map_report['png']))
    native_width,native_height=map_report['page_mm']
    native_left,native_right=0,190.279
    map_scale=135/native_width
    frame_left=63
    map_left=frame_left-10*map_scale
    map_width=(native_right-native_left)*map_scale
    frame_width=180.279*map_scale
    chart_gaps={'AB':4.8,'CD':2}
    assert map_report['risk_class_colors']==dict(zip(CLASSES,COLORS))
    view_height=201
    map_height=view_height*map_scale
    map_top=8+198.5*map_scale
    map_bottom=map_top-map_height
    plt.rcParams.update({'font.family':'Arial','font.weight':'bold','font.size':8,
                         'axes.labelweight':'bold','axes.titleweight':'bold','axes.linewidth':.75,
                         'text.color':INK,'axes.labelcolor':INK,'xtick.color':INK,'ytick.color':INK,
                         'pdf.fonttype':42,'ps.fonttype':42,'axes.unicode_minus':False,
                         'figure.facecolor':'white','axes.facecolor':'white','savefig.facecolor':'white'})
    fig=plt.figure(figsize=(width_mm/25.4,height_mm/25.4))
    def axes(rect):
        x,y,w,h=rect;return fig.add_axes([x/width_mm,y/height_mm,w/width_mm,h/height_mm])
    def boxed(axis):
        axis.tick_params(which='major',labelsize=8.288573333333334,length=2.4,width=.7,pad=2,direction='out',top=False,right=False)
        for spine in axis.spines.values():spine.set_visible(True);spine.set_linewidth(.75);spine.set_color('#252d33')
        axis.grid(False)
    map_axis=axes([map_left,map_bottom,map_width,map_height])
    # Map is exported separately from its editable QGIS layout.
    map_axis.patch.set_alpha(0)
    map_axis.set_xlim(native_left,native_right);map_axis.set_ylim(view_height,0)
    map_axis.set_axis_off()
    frame_top=map_top-8.5*map_scale
    frame_bottom=map_top-198.5*map_scale
    panel_height=38
    gap=(frame_top-frame_bottom-3*panel_height)/2
    bottoms=[frame_top-panel_height,frame_top-2*panel_height-gap,frame_bottom]
    panel_boxes={};legend_specs=[]
    risk_handles=[Patch(facecolor=fill,edgecolor='none',label=label) for label,fill in zip(CLASSES,COLORS)]
    def risk_key(axis, name):
        key=axis.legend(handles=risk_handles,loc='upper left',bbox_to_anchor=(.035,.84),
                        ncol=2,fontsize=8.288573333333334,frameon=False,handlelength=1.05,
                        handletextpad=.4,columnspacing=.9,labelspacing=.04,
                        borderpad=0,borderaxespad=0)
        legend_specs.append((name,key,axis))
    for index,(code,profile) in enumerate(profiles.items()):
        column_width=46
        left=(frame_left-chart_gaps[code]-column_width if index==0
              else frame_left+frame_width+chart_gaps[code])
        stats=profile['stats'];color=CURVE_COLOR;length=profile['line'].length/1000
        name=f'{code[0]}-{code[1]}';x=stats.mid_km.to_numpy();bin_widths=stats.length_km.to_numpy()
        boxes=[[left,y,column_width,panel_height] for y in bottoms];panel_boxes[code]=boxes
        top,mid,low=[axes(box) for box in boxes]
        bottom=np.zeros(len(stats))
        for label,fill in zip(CLASSES,ANALYSIS_COLORS):
            values=stats[label.lower().replace(' ','_')+'_pct'].to_numpy()
            top.bar(x,values,bottom=bottom,width=bin_widths*.965,color=fill,edgecolor='white',linewidth=.2)
            bottom+=np.nan_to_num(values)
        # Reserve a clear band for the five-class key above the 100% stacks.
        top.set_ylim(0,170);top.set_yticks([0,50,100])
        variants=np.stack([frame.high_very_high_pct.to_numpy() for frame in profile['sensitivity']])
        band=mid.fill_between(x,np.nanmin(variants,axis=0),np.nanmax(variants,axis=0),color=color,alpha=.14,
                             linewidth=0,label='Width sensitivity')
        curve,=mid.plot(x,stats.high_very_high_pct,color=color,lw=1.2,marker='o',ms=3,
                        markeredgecolor='white',markeredgewidth=.4,label='1 km each side')
        mid.set_ylim(-3,120);mid.set_yticks([0,50,100])
        peak=stats.loc[stats.high_very_high_pct.idxmax()]
        mid.annotate(f'{peak.high_very_high_pct:.1f}%',(peak.mid_km,peak.high_very_high_pct),
                     xytext=(0,6),textcoords='offset points',ha='right' if index==0 else 'center',
                     fontsize=9.795586666666669,color=color)
        bottom=np.zeros(len(stats))
        for label,fill in zip(CLASSES,ANALYSIS_COLORS):
            values=stats[label.lower().replace(' ','_')+'_count'].to_numpy()
            low.bar(x,values,bottom=bottom,width=bin_widths*.965,color=fill,edgecolor='white',linewidth=.2)
            bottom+=values
        low.set_ylim(0,3000);low.set_yticks([0,1000,2000],['0','1k','2k'])
        low.text(.80,.975,f"n = {len(profile['selected']):,}",transform=low.transAxes,ha='right',va='top',fontsize=8.288573333333334)
        for axis,title,rect in zip([top,mid,low],['Buildings (%)','High + very high (%)','Buildings (n)'],boxes):
            boxed(axis);axis.set_xlim(0,length)
            if index==1:
                axis.yaxis.tick_right()
                axis.tick_params(axis='y',labelleft=False,labelright=True,left=False,right=True)
            axis.set_xticks(np.arange(0,length+1e-6,10 if length>20 else 2))
            axis.get_xticklabels()[0].set_ha('left')
            axis.set_xlabel(f'Distance from {code[0]} (km)',fontsize=9.04208,labelpad=3)
            axis.text(.025,.975,title,transform=axis.transAxes,fontsize=9.04208,ha='left',va='top')
            axis.text(.975,.975,name,transform=axis.transAxes,fontsize=9.795586666666669,ha='right',va='top')
        risk_key(top,code+'_percent_classes')
        risk_key(low,code+'_count_classes')
        curve_key=mid.legend(handles=[curve,band],labels=['High + very high','Width sensitivity'],
                             loc='upper left',bbox_to_anchor=(.04,.83),fontsize=8.288573333333334,
                             frameon=False,borderpad=0,borderaxespad=0,
                             handlelength=1.8,handletextpad=.5,labelspacing=.35)
        legend_specs.append((code+'_curve_sensitivity',curve_key,mid))

    # Geographic keys stay within the map; statistical keys stay in their own axes.
    map_risk=fig.legend(handles=risk_handles,title='Risk level',loc='upper right',
                        bbox_to_anchor=((frame_left+frame_width-1.5)/width_mm,(frame_top-15)/height_mm),
                        fontsize=9.04208,title_fontsize=9.04208,frameon=True,facecolor='white',
                        edgecolor='#c4c4c4',framealpha=.95,borderpad=.35,
                        handlelength=1.25,handletextpad=.5,labelspacing=.15,borderaxespad=0)
    lateral_handle=object()
    map_handles=[Line2D([],[],color=profiles['AB']['color'],lw=1.2,label='A-B'),
                 Line2D([],[],color=profiles['CD']['color'],lw=1.2,label='C-D'),
                 Line2D([],[],color='#555555',lw=.75,ls='--',label='1 km / side'),
                 Line2D([],[],marker='^',color='#d32f36',markeredgecolor='#a82b30',
                        markersize=5,linestyle='none',label='Earthquakes'),
                 Line2D([],[],marker='*',color='#d32f36',markeredgecolor='#a82b30',
                        markersize=7,linestyle='none',label='GNSS station'),
                 Line2D([],[],color='#a23d30',lw=.85,label='Faults'),lateral_handle]
    map_symbols=fig.legend(handles=map_handles,
                           labels=['A-B','C-D','1 km / side','Earthquakes','GNSS station','Faults','Left-lateral'],
                           handler_map={lateral_handle:LeftLateralHandler()},loc='lower left',
                           bbox_to_anchor=((frame_left+1)/width_mm,(frame_bottom+10)/height_mm),
                           fontsize=9.04208,frameon=False,borderpad=.25,
                           handlelength=1.65,handletextpad=.5,labelspacing=.15,borderaxespad=0)
    legend_specs.extend([('map_risk_classes',map_risk,None),('map_symbols',map_symbols,None)])
    # Freeze the original xlabel anchors before the changed tick font can
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
    (PLOT_OUT/'xlabel_anchor_audit.json').write_text(json.dumps(anchors,indent=2)+'\n')
    fig.canvas.draw();renderer=fig.canvas.get_renderer();page=fig.bbox
    texts=list(fig.texts)
    for axis in fig.axes:
        if axis.axison:texts += list(axis.texts)+[axis.xaxis.label,axis.yaxis.label]+axis.get_xticklabels()+axis.get_yticklabels()
    for _,legend,_ in legend_specs:texts += [legend.get_title(),*legend.get_texts()]
    for text in texts:
        if not text.get_visible() or not text.get_text():continue
        box=text.get_window_extent(renderer)
        assert box.x0>=-1 and box.y0>=-1 and box.x1<=page.width+1 and box.y1<=page.height+1,text.get_text()
    map_frame=Bbox.from_bounds(frame_left/width_mm,frame_bottom/height_mm,
                               frame_width/width_mm,(frame_top-frame_bottom)/height_mm)
    map_frame=fig.transFigure.transform_bbox(map_frame)
    legend_audit={}
    for name,legend,parent in legend_specs:
        bounds=legend.get_window_extent(renderer)
        region=parent.bbox if parent is not None else map_frame
        assert region.contains(bounds.x0,bounds.y0) and region.contains(bounds.x1,bounds.y1),name
        if parent is not None:
            for text in parent.texts:
                assert not bounds.overlaps(text.get_window_extent(renderer)),(name,text.get_text())
            for bar in parent.patches:
                if bar.get_height()>0:assert not bounds.overlaps(bar.get_window_extent(renderer)),name
            for line in parent.lines:
                points=line.get_transform().transform(line.get_xydata())
                assert not any(bounds.contains(x,y) for x,y in points),name
        legend_audit[name]={'inside_parent':True,'bounds_mm':[float(v/fig.dpi*25.4) for v in bounds.bounds],
                            'labels':[t.get_text() for t in legend.get_texts()],
                            'title':legend.get_title().get_text(),'frame_visible':legend.get_frame_on(),
                            'font_size_pt':legend.get_texts()[0].get_fontsize()}
    preview=PLOT_OUT/f'{STEM}_preview.png';png=PLOT_OUT/f'{STEM}_{dpi}dpi.png';pdf=PLOT_OUT/f'{STEM}.pdf'
    fig.savefig(preview,dpi=220,transparent=True);fig.savefig(png,dpi=dpi,transparent=True)
    fig.savefig(pdf,dpi=600,transparent=True,metadata={'Title':'Kunming risk profiles: A-B left, original map center, C-D right','Author':'seismic_risk'})
    drawing=[]
    for axis in fig.axes[1:]:
        drawing.append({'box':list(axis.get_position().bounds),'xlim':list(axis.get_xlim()),'ylim':list(axis.get_ylim()),
            'xticks':list(axis.get_xticks()),'yticks':list(axis.get_yticks()),
            'bars':[{'x':p.get_x(),'y':p.get_y(),'width':p.get_width(),'height':p.get_height(),'color':list(p.get_facecolor())} for p in axis.patches],
            'lines':[{'x':list(l.get_xdata()),'y':list(l.get_ydata()),'color':l.get_color()} for l in axis.lines]})
    (PLOT_OUT/'drawing_state.json').write_text(json.dumps(drawing,indent=2,default=float)+'\n')
    fig.savefig(PLOT_OUT/'chart_overlay_native.svg',transparent=True)
    plt.close(fig)
    assert digest(Path(map_report['png']))==map_hash
    with Image.open(png) as im:pixels=list(im.size);actual_dpi=list(im.info.get('dpi',[]))
    return {'png':str(png),'pdf':str(pdf),'preview':str(preview),'pixels':pixels,'png_dpi':actual_dpi,
            'page_mm':[width_mm,height_mm],'layout':'A-B charts left; original QGIS map center; C-D charts right',
            'map_box_mm':[map_left,map_bottom,map_width,map_height],'panel_boxes_mm':panel_boxes,
            'map_native_view_mm':[native_left,0,native_right-native_left,view_height],
            'map_frame_mm':[frame_left,frame_bottom,frame_width,frame_top-frame_bottom],
            'chart_to_map_gap_mm':chart_gaps,'right_chart_y_ticks':'outside right',
            'analysis_colors':dict(zip(CLASSES,ANALYSIS_COLORS)),'map_colors':dict(zip(CLASSES,COLORS)),
            'curve_color':CURVE_COLOR,'legend_audit':legend_audit,
            'legend_position':'Map class and symbol keys inside map; class keys inside all four bar charts; curve/sensitivity keys inside both line charts',
            'map_asset_sha256':map_hash,'map_asset_unchanged_during_composition':True,
            'style_reference':'/var/folders/sc/p3glb7fj0hjfdwyxdxljch8h0000gn/T/codex-clipboard-fd1962db-22fd-4047-9347-ee7de0c0be2c.png',
            'font':'Arial Bold','axes_style':'boxed, 0.75 pt; inside titles; white bar separators; local inset legends'}


# The original analysis/publishing main() is deliberately omitted.
