"""Current discussion experiment: add InSAR on a frozen Static-only baseline.

Run with the seismic Python environment. Formal observations/models/manuscript are
read-only. Default derivatives live in result/discussion/12_insar_contribution/static_baseline/.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
from decimal import Decimal, ROUND_HALF_UP

os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/seismic-static-baseline-mpl')
os.environ.setdefault('XDG_CACHE_HOME', '/private/tmp/seismic-static-baseline-cache')
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D
from match_static_baseline_cases import search as relaxed_pair_search, RELAXED_TIERS
from analysis_static_baseline import build_analysis
from case_panel_static_baseline import draw_case_panel

ROOT = Path(__file__).resolve().parents[3]
EXP = Path(__file__).resolve().parent
CLASSES = ['Very Low', 'Low', 'Moderate', 'High', 'Very High']
SHORT = dict(zip(CLASSES, ['VL','L','M','H','VH']))
RED, BLUE, GREY = '#C5433C', '#2875B5', '#75828B'
PROTOCOL = 'static_only_frozen_normalization_and_jenks'
PAIR = [39899, 39929]


def digest(p):
    with Path(p).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pct(n, total=40000):
    return str((Decimal(int(n))*100/Decimal(int(total))).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def markdown(frame, index=False):
    frame=frame.reset_index() if index else frame
    def cell(value):
        if isinstance(value,(float,np.floating)): return f'{value:.6g}'
        return str(value).replace('|','/').replace('\n',' ')
    rows=['| '+' | '.join(map(str,frame.columns))+' |','| '+' | '.join(['---']*len(frame.columns))+' |']
    rows+=['| '+' | '.join(cell(v) for v in row)+' |' for row in frame.itertuples(index=False,name=None)]
    return '\n'.join(rows)


def classify(values, breaks):
    # Upper-inclusive internal boundaries; endpoints extend to finite scores.
    return pd.Series(np.array(CLASSES)[np.searchsorted(breaks[1:-1], values, side='left')], index=values.index)


def prepare(out):
    global PAIR
    source = ROOT/'result/intermediate/12_insar_contribution/strict_ablation_full_40000.csv'
    vpath = ROOT/'result/vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg'
    audit = json.loads((ROOT/'result/intermediate/12_insar_contribution/analysis_audit.json').read_text())
    d = pd.read_csv(source, float_precision='round_trip', low_memory=False).sort_values('Build_ID').reset_index(drop=True).copy()
    assert len(d)==40000 and d.Build_ID.is_unique
    spatial = pd.read_json(ROOT/'result/intermediate/12_insar_contribution/spatial_context.json')
    d = d.merge(spatial, on='Build_ID', validate='one_to_one').copy()
    with sqlite3.connect(f'file:{vpath}?mode=ro', uri=True) as connection:
        v = pd.read_sql_query('SELECT Build_ID,V_static FROM building_comprehensive_vulnerability', connection)
    assert len(v)==41939 and v.Build_ID.is_unique
    low, high = map(float, audit['normalization_static'])
    assert np.allclose(v.V_static.quantile([.01,.99]), [low,high], rtol=0, atol=1e-14)
    breaks = list(audit['static_breaks'])
    config = json.loads((ROOT/'project/code/Vulnerability/config.json').read_text())
    alpha = float(config['model']['alpha_vulnerability'])
    assert alpha==.3
    def norm_v(raw):
        return (raw.clip(low,high)-low)/(high-low)
    v0 = norm_v(d.V_static)
    v1 = norm_v(d.V_static*(1+alpha*d.IBSI))
    p0 = d.H_Index*v0*d.E_Index
    pmin,pmax = float(p0.min()),float(p0.max())
    def risk(ibsi):
        return (d.H_Index*norm_v(d.V_static*(1+alpha*ibsi))*d.E_Index-pmin)/(pmax-pmin)
    r0,r1 = risk(pd.Series(0., index=d.index)),risk(d.IBSI)
    baseline_error = float((r0-d.R0).abs().max())
    assert baseline_error<1e-14
    c0,c1 = classify(r0,breaks),classify(r1,breaks)
    assert c0.eq(d.Class0_Jenks).all(), 'Frozen baseline classes must equal original Static-only classes'
    assert np.isfinite(r0).all() and np.isfinite(r1).all()
    order = dict(zip(CLASSES,range(5)))
    steps = c1.map(order)-c0.map(order)
    assert (r1>=r0-1e-14).all() and steps.ge(0).all()
    fields = {'R_static_baseline':r0,'R_insar_static_baseline':r1,'delta_R_static_baseline':r1-r0,
              'V_static_normalized_baseline':v0,'V_insar_normalized_baseline':v1,
              'static_class':c0,'insar_class':c1,'class_steps':steps,
              'transition':c0+' → '+c1,
              'change':pd.Series(np.where(steps.gt(0),'Upgraded','Unchanged'),index=d.index),
              'risk_rank_change_pp':100*(r1.rank(pct=True)-r0.rank(pct=True))}
    d = d.assign(**fields).copy()
    d['nearest_static_break_distance'] = np.min(abs(r0.to_numpy()[:,None]-np.array(breaks[1:-1])),axis=1)
    d['insar_class_lower_margin'] = [r-breaks[order[c]] for r,c in zip(r1,c1)]
    d['reliable_ps'] = (d.PS_Q_OK.eq(1)&d.Tilt_OK.eq(1)&d.N_Pt_Deform.ge(10)&d.PS_Count.ge(10)&d.PS_CohMn.ge(.8)&d.PS_Cov.ge(.1)&d.Q_insar.ge(.5))
    quantiles = d[['V_RMS','Tilt_Angle','DGI_Str','IBSI']].quantile(.75)
    d['deformation_p75_count'] = sum(d[k].ge(quantiles[k]).astype(int) for k in ['V_RMS','Tilt_Angle','DGI_Str'])
    d['screen_eligible'] = (d.reliable_ps & d.class_steps.gt(0) & d.delta_R_static_baseline.ge(.01)
                            & d.insar_class_lower_margin.ge(.005) & d.IBSI.ge(quantiles.IBSI)
                            & d.deformation_p75_count.ge(1))
    # Re-run exactly the original strict pair criteria, without forcing a match.
    helper_spec = importlib.util.spec_from_file_location('legacy_selection_helpers', EXP/'analyze_cases.py')
    helper = importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
    probe = d.assign(R0=r0,Risk_Final=r1,risk_delta=r1-r0)
    strict_pairs = helper.pair_search(probe)
    relaxed_pairs = pd.DataFrame()
    tier_results = [{'name':'A_original_strict','pairs_n':len(strict_pairs)}]
    accepted_tier = None
    for tier in RELAXED_TIERS:
        candidate_pairs = relaxed_pair_search(d,tier)
        tier_results.append({'name':tier['name'],'pairs_n':len(candidate_pairs),'conditions':tier})
        if len(candidate_pairs):
            relaxed_pairs=candidate_pairs.sort_values(['static_risk_absdiff','distance_m','IBSI_gap','target_id','control_id'],ascending=[True,True,False,True,True])
            accepted_tier=tier
            break
    assert len(relaxed_pairs)>0, 'No acceptable relaxed pair; do not invent a control.'
    primary_pool=relaxed_pairs[relaxed_pairs.target_transition.eq('Moderate → High')]
    primary=(primary_pool if len(primary_pool) else relaxed_pairs).iloc[0]
    PAIR=[int(primary.target_id),int(primary.control_id)]
    for prefix in ['target','control']:
        ids=relaxed_pairs[prefix+'_id']
        lookup0=d.set_index('Build_ID').loc[ids]
        for key in ['R_static_baseline','R_insar_static_baseline','PS_Count','PS_CohMn','PS_Cov','Q_insar','IBSI','V_RMS','DGI_Str']:
            relaxed_pairs[prefix+'_'+key]=lookup0[key].to_numpy()
    variants = {'without_DGI':(d.IBSI_base+d.IBSI_tilt).clip(0,1),
                'without_Tilt':(d.IBSI_base+d.IBSI_DGI).clip(0,1),
                'RMS_Q_only':d.IBSI_base.clip(0,1)}
    ablation = {}
    for name, ibsi in variants.items():
        d[name+'_risk'] = risk(ibsi)
        d[name+'_class'] = classify(d[name+'_risk'],breaks)
        ablation[name] = int(d[name+'_class'].ne(c1).sum())
    for field in ['V_RMS','Tilt_Angle','DGI_Str','IBSI','Q_insar']:
        d[field+'_percentile'] = 100*(d[field].rank(method='average')-.5)/len(d)
    matrix = pd.crosstab(c0,c1).reindex(index=CLASSES,columns=CLASSES,fill_value=0)
    chosen = {};used_blocks = set()
    def add(row, role):
        bid = int(row.Build_ID)
        if bid not in chosen:
            chosen[bid] = role
            if pd.notna(row.road_block_id): used_blocks.add(row.road_block_id)
    mh = d[d.screen_eligible & d.static_class.eq('Moderate') & d.insar_class.eq('High')]
    for _,row in mh.sort_values(['delta_R_static_baseline','Build_ID'],ascending=[False,True]).iterrows():
        if row.road_block_id in used_blocks: continue
        add(row,'Moderate→High评分增量典型')
        if len(chosen)>=4: break
    extras = 0
    for _,row in mh.sort_values(['DGI_Str','delta_R_static_baseline','Build_ID'],ascending=[False,False,True]).iterrows():
        if int(row.Build_ID) in chosen or row.road_block_id in used_blocks: continue
        add(row,'局部差异形变典型');extras+=1
        if extras==2: break
    for transition, mask, metric in [
        ('High→Very High补充',d.screen_eligible&d.static_class.eq('High')&d.insar_class.eq('Very High'),'delta_R_static_baseline'),
        ('Tilt参与修正补充',d.screen_eligible&d.T_anom_n.gt(0),'T_anom_n')]:
        pool=d[mask]
        if len(pool): add(pool.sort_values([metric,'Build_ID'],ascending=[False,True]).iloc[0],transition)
    lookup=d.set_index('Build_ID')
    for bid,role in [(51263,'整体形变强度复核'),(17654,'局部速度梯度复核'),
                     (46121,'同街区较大评分增量：双方均升档'),(35358,'同街区较小评分增量：双方均升档')]:
        add(d[d.Build_ID.eq(bid)].iloc[0],role)
    for _,pair_row in relaxed_pairs.iterrows():
        add(d[d.Build_ID.eq(int(pair_row.target_id))].iloc[0],'放宽观测条件后的同街区升档目标')
        add(d[d.Build_ID.eq(int(pair_row.control_id))].iloc[0],'放宽观测条件后的同街区未变级对照')
    selected=d.set_index('Build_ID').loc[list(chosen)].reset_index()
    selected.insert(0,'case_order',range(1,len(selected)+1));selected.insert(2,'case_role',[chosen[int(i)] for i in selected.Build_ID])
    columns=['Build_ID','district','subdistrict','road_block_id','longitude_wgs84','latitude_wgs84',
             'centroid_x_utm48n_m','centroid_y_utm48n_m','R_static_baseline','R_insar_static_baseline',
             'delta_R_static_baseline','static_class','insar_class','class_steps','transition','change',
             'risk_rank_change_pp','nearest_static_break_distance','insar_class_lower_margin',
             'IBSI','V_RMS','Tilt_Angle','DGI_Str','Q_insar','PS_Count','PS_CohMn','PS_Cov',
             'V_RMS_n','T_anom_n','DGI_n','IBSI_base','IBSI_DGI','IBSI_tilt',
             'V_static','V_static_normalized_baseline','V_insar_normalized_baseline','H_Index','E_Index',
             'Height_m','Area_m2','reliable_ps','screen_eligible',
             'without_DGI_risk','without_DGI_class','without_Tilt_risk','without_Tilt_class','RMS_Q_only_risk','RMS_Q_only_class']
    out.mkdir(parents=True,exist_ok=True);(out/'data').mkdir(exist_ok=True);(out/'figures').mkdir(exist_ok=True)
    def save(frame,name): frame.to_csv(out/'data'/name,index=False,encoding='utf-8-sig',float_format='%.17g')
    save(d[columns],'all_40000_buildings.csv')
    save(d.loc[d.class_steps.ne(0),columns].sort_values(['delta_R_static_baseline','Build_ID'],ascending=[False,True]),'all_risk_class_changes.csv')
    save(selected[['case_order','case_role',*columns]],'candidate_building_cases.csv')
    save(d[d.screen_eligible][columns],'reliable_upgrade_candidates.csv')
    transition_rows=[{'static_class':old,'insar_class':new,'building_count':int(matrix.loc[old,new]),
                      'share_of_40000_pct':100*matrix.loc[old,new]/len(d),
                      'share_within_static_class_pct':100*matrix.loc[old,new]/matrix.loc[old].sum()}
                     for old in CLASSES for new in CLASSES]
    save(pd.DataFrame(transition_rows),'risk_class_transition_summary.csv')
    district=d.groupby('district',dropna=False).agg(buildings=('Build_ID','size'),upgraded=('class_steps',lambda s:int(s.gt(0).sum())),
                    median_delta=('delta_R_static_baseline','median'),mean_delta=('delta_R_static_baseline','mean')).reset_index()
    district['upgraded_pct']=100*district.upgraded/district.buildings;save(district,'district_upgrade_rates.csv')
    summaries=[]
    for group,subset in d.groupby('change'):
        row={'group':group,'n':len(subset),'reliable_ps_n':int(subset.reliable_ps.sum())}
        for key in ['delta_R_static_baseline','R_static_baseline','nearest_static_break_distance','IBSI','V_RMS','Tilt_Angle','DGI_Str','Q_insar']:
            row[key+'_median']=float(subset[key].median());row[key+'_p90']=float(subset[key].quantile(.9))
        summaries.append(row)
    save(pd.DataFrame(summaries),'changed_unchanged_indicator_comparison.csv')
    pair=d.set_index('Build_ID').loc[PAIR].reset_index();save(pair[columns],'primary_pair_reassessment.csv')
    save(d[d.Build_ID.isin([46121,35358])][columns],'previous_pair_reassessment.csv')
    save(strict_pairs if len(strict_pairs) else pd.DataFrame(columns=['target_id','control_id','target_transition','control_transition']),'strict_block_matched_pairs.csv')
    save(relaxed_pairs,'block_matched_pairs.csv')
    write_json(out/'data/pair_selection_conditions.json',{'original_strict_pairs_n':len(strict_pairs),'tier_search_results':tier_results,'accepted_tier':accepted_tier,'accepted_pairs_n':len(relaxed_pairs),'primary_pair':PAIR,'selection_rule':'First nonempty relaxation tier; prefer Moderate→High for the main case, then smaller static-risk difference, shorter distance, larger IBSI gap, and deterministic IDs.'})
    stats={'protocol':PROTOCOL,'sample_n':len(d),'vulnerability_reference_n':len(v),
           'unchanged_n':int(steps.eq(0).sum()),'upgrade_n':int(steps.gt(0).sum()),'downgrade_n':int(steps.lt(0).sum()),
           'unchanged_pct':float(100*steps.eq(0).mean()),'upgrade_pct':float(100*steps.gt(0).mean()),
           'moderate_to_high_n':int(matrix.loc['Moderate','High']),'max_class_steps':int(steps.max()),
           'static_high_veryhigh_n':int(c0.isin(['High','Very High']).sum()),
           'insar_high_veryhigh_n':int(c1.isin(['High','Very High']).sum()),
           'class_order':CLASSES,'matrix':matrix.to_numpy().tolist(),'alpha':alpha,
           'static_vulnerability_P1_P99':[low,high],'static_risk_product_min_max':[pmin,pmax],
           'frozen_static_Jenks_breaks':breaks,'risk_score_min_max_after_insar':[float(r1.min()),float(r1.max())],
           'above_baseline_maximum_n':int(r1.gt(1).sum()),'baseline_reconstruction_max_error':baseline_error,
           'baseline_classes_identical_to_original_Static_only':True,'normalization_or_Jenks_refitted_after_InSAR':False,
           'negative_delta_beyond_1e_14_n':int((r1-r0).lt(-1e-14).sum()),
           'reliable_upgrade_candidates_n':int(d.screen_eligible.sum()),'strict_changed_vs_unchanged_pairs_n':len(strict_pairs),
           'relaxed_changed_vs_unchanged_pairs_n':len(relaxed_pairs),'accepted_pair_tier':accepted_tier,
           'primary_pair_distance_m':float(primary.distance_m),'primary_pair_static_risk_absdiff':float(primary.static_risk_absdiff),
           'selected_cases_n':len(selected),'selected_case_ids':list(chosen),
           'component_removal_class_change_counts':ablation,'pair_ids':PAIR,
           'pair_role':'Same-block upgraded target versus unchanged-class control; observation-support conditions explicitly relaxed; original static matching tolerances retained.',
           'pair_rows':pair[columns].to_dict(orient='records'),
           'source_files':{str(p.relative_to(ROOT)):digest(p) for p in [source,vpath,ROOT/'result/risk/scs_paper_method/building_risk.gpkg',ROOT/'project/code/Vulnerability/config.json',ROOT/'project/code/Risk/config.json']},
           'group_summaries':summaries}
    write_json(out/'data/static_baseline_statistics.json',stats)
    return d,selected,stats


def save_figure(fig,out,name):
    fig.savefig(out/'figures'/f'{name}.png',dpi=600,facecolor='white')
    fig.savefig(out/'figures'/f'{name}.svg',facecolor='white')
    fig.savefig(out/'figures'/f'{name}_preview.png',dpi=160,facecolor='white')
    plt.close(fig)


def plot(d,selected,s,out,composite_only=False):
    global PAIR
    PAIR=list(s['pair_ids'])
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10.5,
                         'axes.labelsize':9,'xtick.labelsize':8,'ytick.labelsize':8,
                         'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False})
    fig=plt.figure(figsize=(10.6,9.3))
    ax=fig.add_axes([.055,.565,.415,.355])
    districts=gpd.read_file(ROOT/'data/administrative/kunming_districts.shp').to_crs(32648)
    districts=districts[districts.name.isin(['五华区','盘龙区','西山区','官渡区','呈贡区'])].copy()
    districts.geometry=districts.geometry.scale(.001,.001,origin=(0,0))
    districts.plot(ax=ax,color='#FAFAFA',edgecolor='#A6AFB5',lw=.6)
    changed=d[d.class_steps.gt(0)]
    x,y=changed.centroid_x_utm48n_m/1000,changed.centroid_y_utm48n_m/1000
    ax.scatter(x,y,s=6,c=RED,alpha=.65,lw=0)
    ax.set(xlim=(x.min()-2,x.max()+2),ylim=(y.min()-2,y.max()+2),aspect='equal',xlabel='UTM easting (km)',ylabel='UTM northing (km)')
    pair=d[d.Build_ID.isin(PAIR)]
    px,py=pair.centroid_x_utm48n_m.mean()/1000,pair.centroid_y_utm48n_m.mean()/1000
    ax.scatter([px],[py],marker='*',s=70,c='#1F2930',edgecolor='white',lw=.5,zorder=6)
    ax.annotate('Selected pair',(px,py),xytext=(px+4,py+1),fontsize=8,arrowprops={'arrowstyle':'-','lw':.6})
    ax.set_title(f'(a) All {s["upgrade_n"]:,} upgraded buildings',loc='left',pad=10)
    ax.text(.02,.025,'No sampling or point displacement',transform=ax.transAxes,fontsize=7.5,color=GREY)
    ax=fig.add_axes([.58,.565,.35,.355]);matrix=np.array(s['matrix']);edges=np.arange(-.5,5,1)
    cmap=plt.get_cmap('Blues').copy();cmap.set_bad('#F3F4F5')
    ax.pcolormesh(edges,edges,np.ma.masked_equal(matrix,0),norm=LogNorm(1,matrix.max()),cmap=cmap,edgecolors='white',lw=.6)
    for i in range(5):
        for j in range(5):
            n=matrix[i,j];label=f'{n:,}\n{pct(n,int(matrix[i].sum()))}%' if n else '0'
            ax.text(j,i,label,ha='center',va='center',fontsize=8,color='white' if n>2500 else '#24333F')
    ax.set(xlim=(-.5,4.5),ylim=(4.5,-.5),aspect='equal',xticks=range(5),yticks=range(5),
           xticklabels=list(SHORT.values()),yticklabels=list(SHORT.values()),xlabel='After adding InSAR: fixed static boundaries',ylabel='Static-only baseline class')
    ax.set_title('(b) Frozen Static-only class transitions',loc='left',pad=10)
    fig.text(.755,.495,f'Unchanged {s["unchanged_n"]:,} ({pct(s["unchanged_n"])}%)   |   Upgraded {s["upgrade_n"]:,} ({pct(s["upgrade_n"])}%)',ha='center',fontsize=8.1)
    fig.text(.755,.478,f'Downgraded 0   |   Moderate → High {s["moderate_to_high_n"]:,}',ha='center',fontsize=8.1)
    draw_case_panel(fig,ROOT,d,s,out)
    fig.suptitle('InSAR increment on a frozen Static-only baseline',fontsize=12,y=.975)
    save_figure(fig,out,'fig_5_1_static_baseline')
    if composite_only:
        return
    c=selected.sort_values('case_order');n=len(c)
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(10,max(4.5,n*.33+1.0)),gridspec_kw={'width_ratios':[1.3,1]})
    fig.subplots_adjust(left=.24,right=.97,top=.92,bottom=.12,wspace=.30)
    y=np.arange(n)
    for k,(_,row) in enumerate(c.iterrows()):
        ax1.plot([row.R_static_baseline,row.R_insar_static_baseline],[k,k],color='#A5ADB2',lw=1.1)
        ax1.scatter(row.R_static_baseline,k,facecolors='white',edgecolors='#4B555B',s=26)
        ax1.scatter(row.R_insar_static_baseline,k,color=BLUE if '未变级对照' in row.case_role else RED,s=28)
    ax1.set(yticks=y,yticklabels=[f'{int(r.Build_ID)}  {SHORT[r.static_class]} → {SHORT[r.insar_class]}' for _,r in c.iterrows()],xlabel='Risk score: identical Static-only normalization',ylim=(n-.5,-.5))
    ax1.set_title('(a) Selected buildings: score changes',loc='left')
    ax2.barh(y,c.IBSI_base,color='#7299B2',label='Q × RMS base')
    ax2.barh(y,c.IBSI_DGI,left=c.IBSI_base,color='#DD9835',label='DGI term')
    ax2.barh(y,c.IBSI_tilt,left=c.IBSI_base+c.IBSI_DGI,color='#8956A2',label='Tilt term')
    ax2.set(ylim=(n-.5,-.5),yticks=[],xlabel='IBSI components',xlim=(0,1))
    ax2.set_title('(b) Stored deformation-state components',loc='left');ax2.legend(frameon=False,fontsize=8,loc='lower right')
    save_figure(fig,out,'fig_S5_1_static_baseline_cases')


def write_docs(d,selected,s,out):
    pair_ids=s['pair_ids']
    pair=d.set_index('Build_ID').loc[pair_ids];t,c=pair.loc[pair_ids[0]],pair.loc[pair_ids[1]]
    paragraphs=['传统地震风险评估主要依赖地震危险性、建筑易损性和暴露性等指标表征城市地震风险。然而，静态特征相近的建筑可能表现出不同的形变行为，而这些差异通常未在传统评估中得到充分体现。引入InSAR形变观测，为细化建筑尺度风险评估提供了额外的观测信息。为评估InSAR的增量贡献，本研究在静态基准与InSAR修正方案之间采用一致的归一化参数和风险等级阈值，确保风险评价结果的差异来源于InSAR信息的引入，而非评价尺度的变化。', '在40,000栋建筑中，引入InSAR后共有2,391栋（5.98%）发生风险等级调整，其余94.02%的建筑保持原有等级（图5.1）。其中，696栋建筑由中风险升至高风险，使高风险与极高风险建筑的合计比例由16.31%增加至18.05%。从空间分布来看，升档建筑并非均匀分布，而是在中心城区及西部城区表现出一定的集聚特征。这表明，引入形变观测并未显著改变城市整体风险格局，而是对部分建筑的风险等级产生了差异化调整。从城市风险管理角度来看，这种调整有助于识别传统静态评估中未被归入高风险类别，但在考虑其形变特征后可能需要重点关注的建筑，为优化建筑风险筛查优先级提供了补充依据。', '同街区配对建筑进一步展示了InSAR对静态风险相近建筑的差异化识别能力（图5.1）。西山区同一道路围合街区内的两栋建筑相距约202 m，其静态风险评分分别为0.25159和0.25641。引入InSAR后，两栋建筑的风险评分分别增加至0.28102和0.26085，原有风险排序发生反转。其中，39899号建筑由中风险升至高风险，而39929号建筑仍保持中风险。这种差异与两栋建筑不同的形变特征及观测支撑条件有关。39899号建筑的RMS形变速率为4.45 mm/年，约为39929号建筑（1.31 mm/年）的3.39倍，其InSAR状态指标也明显更高（0.339与0.050）。这表明，即使建筑具有相近的静态风险特征，InSAR观测仍能够通过反映不同的形变状态，进一步细化建筑之间的风险差异。', '进一步结合PS观测结果，可以更直观地解释两栋建筑的形变差异（图5.1）。39899号建筑表现出更宽的形变速率变化范围，其拟合速度面呈现更明显的空间变化，而39929号建筑的整体形变强度相对较低。然而，39899号建筑的局部形变梯度（0.313 mm/(m·年)）反而低于39929号建筑（0.392 mm/(m·年)），说明整体形变强度与局部非均匀形变并不一定具有一致的变化趋势。此外，两栋建筑的PS观测支撑条件也存在差异，关联PS数量分别为109和57个，综合观测质量分别为0.635和0.411。因此，39899号建筑较高的InSAR风险修正主要与其更强的整体形变及更充分的观测支撑有关，而非更大的局部形变梯度。这一对比说明，在解释建筑尺度风险调整时，需要综合考虑形变特征及观测可靠性，而不能仅依赖单一形变指标。', 'InSAR的主要贡献并非显著改变城市整体地震风险格局，而是在传统静态风险评估的基础上，引入观测驱动的形变信息，进一步细化建筑之间的风险差异。通过识别静态风险相近但形变特征不同的建筑，该框架能够为建筑风险排序和针对性结构调查提供补充依据。']
    caption=f'**图5.1 以Static-only为固定基准加入InSAR后的建筑风险变化。**（a）全部升档建筑质心，无抽样或位移，星号为主配对位置；点密集不等同于经建筑总量校正的升档率。（b）等级转移数量及Static-only对应等级内占比；VL、L、M、H、VH依次为Very Low、Low、Moderate、High、Very High，使用固定静态归一化及Jenks分界。（c）主配对{pair_ids[0]}与{pair_ids[1]}的80×80 m局部PS形变对比，保留全部{int(t.PS_Count)}和{int(c.PS_Count)}个关联PS。每栋左图为观测垂向速率、相干性加权拟合速度面等值线及拟合速率增大方向的等长箭头，右图为速度面残差和局部梯度邻接线；黑圈为各建筑内部梯度超过自身P90的位置，虚线为5 m关联缓冲区。两类地图分别共用色标，等值线仅绘于PS凸包内。N为UTM格网北向，观测期为2017—2019年；速度面梯度及残差不等同于结构倾斜或扭转实测。'
    links='[全部变化建筑](data/all_risk_class_changes.csv) · [40,000栋完整比较](data/all_40000_buildings.csv) · [等级转移汇总](data/risk_class_transition_summary.csv) · [候选案例](data/candidate_building_cases.csv) · [行政区升档率](data/district_upgrade_rates.csv) · [同街区配对](data/block_matched_pairs.csv) · [放宽条件](data/pair_selection_conditions.json)'
    methods=f'''## 固定的计算口径

- 静态易损性归一化：在原41,939栋有效易损性样本的V_static上确定P1/P99 = {s['static_vulnerability_P1_P99']}。
- 基准风险：用40,000栋共同样本计算 H × N_static(V_static) × E；风险原始乘积固定min/max = {s['static_risk_product_min_max']}。
- 加入InSAR：V1 = N_static[V_static × (1 + 0.3 × IBSI)]，R1沿用基准风险min/max。N_static始终使用同一组静态P1/P99及截尾规则。
- 五级分界固定为 {s['frozen_static_Jenks_breaks']}，内部端点上包；没有再次执行Jenks。
- 基准R0与既存Static-only评分最大误差为{s['baseline_reconstruction_max_error']:.3g}；基准等级与既存Class0_Jenks逐栋相同。
- 观测质量和IBSI构成使用正式结果；不更改原始PS、H/E模型、静态权重、IBSI权重或正式论文结果。
- 固定尺度下最高级对超出原最大值的有限评分延伸开放；本次超出基准最大值建筑为{s['above_baseline_maximum_n']}栋。
'''
    main='# 5.1 在固定Static-only分级基准上引入InSAR信息\n\n'+paragraphs[0]+'\n\n![图5.1](figures/fig_5_1_static_baseline.png)\n\n'+caption+'\n\n'+'\n\n'.join(paragraphs[1:])+'\n\n'+links+'\n\n'+methods
    (out/'README.md').write_text(main)
    matrix=pd.DataFrame(s['matrix'],index=CLASSES,columns=CLASSES)
    table='| Static-only → +InSAR | 建筑数 | 占40,000栋比例 |\n| --- | ---: | ---: |\n'
    for old in CLASSES:
        for new in CLASSES:
            if old!=new and matrix.loc[old,new]:table+=f'| {old} → {new} | {matrix.loc[old,new]:,} | {pct(int(matrix.loc[old,new]))}% |\n'
    casecols=['Build_ID','R_static_baseline','R_insar_static_baseline','delta_R_static_baseline','static_class','insar_class','IBSI','V_RMS','Tilt_Angle','DGI_Str','Q_insar','without_DGI_risk','without_DGI_class','without_Tilt_risk','without_Tilt_class']
    oldpair=d.set_index('Build_ID').loc[[46121,35358]]
    analysis=build_analysis(d,selected,s,out,methods,links)
    (out/'数值结果分析.md').write_text(analysis)
    supplement='# 5.1 固定静态基准补充材料\n\n![图S5.1](figures/fig_S5_1_static_baseline_cases.png)\n\n图S5.1展示按本轮规则筛选的案例、放宽条件后的升档与未变级配对及指定复核建筑；空心点为Static-only，实心点为加入InSAR后的共同尺度评分，未变级对照以蓝色表示，右侧为既存IBSI组成。全部案例物理指标、质量、组件去除评分及等级见CSV。35358在当前口径下同样升档，不是不变级对照。\n\n'+markdown(selected[casecols])+'\n\n'+methods+'\n\n'+links+'\n'
    (out/'补充材料.md').write_text(supplement)
    (out/'图件汇总.md').write_text('# 5.1 当前固定静态基准图件\n\n![图5.1](figures/fig_5_1_static_baseline.png)\n\n'+caption+'\n\n![图S5.1](figures/fig_S5_1_static_baseline_cases.png)\n\n[完整说明](README.md)\n')


def spatial_outputs(d,selected,out):
    qdir=out/'QGIS';(qdir/'data').mkdir(parents=True,exist_ok=True)
    gpkg=qdir/'data/static_baseline_5_1.gpkg'
    if gpkg.exists(): gpkg.unlink()
    fields=['Build_ID','R_static_baseline','R_insar_static_baseline','delta_R_static_baseline','static_class','insar_class','class_steps','IBSI','Q_insar','PS_Count']
    points=gpd.GeoDataFrame(d[fields],geometry=gpd.points_from_xy(d.centroid_x_utm48n_m,d.centroid_y_utm48n_m),crs=32648)
    points[points.class_steps.gt(0)].to_file(gpkg,layer='upgraded_building_points',driver='GPKG')
    points.to_file(gpkg,layer='all_40000_buildings',driver='GPKG')
    shapes=gpd.read_file(ROOT/'result/risk/scs_paper_method/building_risk.gpkg',layer='building_risk_scs',columns=['Build_ID','geometry'])
    shapes[shapes.Build_ID.isin(selected.Build_ID)].merge(selected[fields],on='Build_ID',validate='one_to_one').to_file(gpkg,layer='selected_building_footprints',driver='GPKG')
    pair_shapes=shapes[shapes.Build_ID.isin(PAIR)].merge(d[d.Build_ID.isin(PAIR)][fields],on='Build_ID',validate='one_to_one')
    pair_shapes['pair_role']=np.where(pair_shapes.Build_ID.eq(PAIR[0]),'Upgraded target','Unchanged-class control')
    pair_shapes.to_file(gpkg,layer='primary_pair_footprints',driver='GPKG')
    districts=gpd.read_file(ROOT/'data/administrative/kunming_districts.shp').to_crs(32648)
    districts[districts.name.isin(['五华区','盘龙区','西山区','官渡区','呈贡区'])][['name','geometry']].to_file(gpkg,layer='district_boundaries',driver='GPKG')


def current_discussion_pages(out):
    names={'5.1_InSAR状态修正的增量作用.md':'README.md',
           '5.1_综合图数值结果分析.md':'数值结果分析.md',
           '5.1_补充材料.md':'补充材料.md','5.1_图件汇总.md':'图件汇总.md'}
    return {name:(out/source).read_text().replace('(figures/','(../static_baseline/figures/').replace('(data/','(../static_baseline/data/').replace('(QGIS/','(../static_baseline/QGIS/').replace('(README.md)','(../static_baseline/README.md)')
            for name,source in names.items()}


def sync_current_pages(out,exp=EXP):
    for name,text in current_discussion_pages(out).items():
        notes = ROOT/'result/discussion/12_insar_contribution/notes'
        notes.mkdir(parents=True, exist_ok=True)
        (notes/name).write_text(text)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,default=ROOT/'result/discussion/12_insar_contribution/static_baseline')
    args=parser.parse_args();out=args.output_dir.resolve()
    protected=[ROOT/'manuscript/tex/manuscript.tex',ROOT/'manuscript/pdf/manuscript.pdf',ROOT/'manuscript/figures/jpg/Figure12.jpg',ROOT/'project/code/classification.py']
    before={str(p):digest(p) for p in protected}
    d,selected,s=prepare(out);plot(d,selected,s,out);write_docs(d,selected,s,out);spatial_outputs(d,selected,out)
    if out==(ROOT/'result/discussion/12_insar_contribution/static_baseline').resolve():sync_current_pages(out)
    assert all(digest(p)==h for p,h in before.items())
    write_json(out/'data/preservation.json',{'protected_manuscript_and_code':before,'formal_source_files':s['source_files'],'unchanged':True})
    print(json.dumps({k:s[k] for k in ['protocol','sample_n','unchanged_n','upgrade_n','downgrade_n','moderate_to_high_n','reliable_upgrade_candidates_n','strict_changed_vs_unchanged_pairs_n','relaxed_changed_vs_unchanged_pairs_n','pair_ids','selected_cases_n','component_removal_class_change_counts']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
