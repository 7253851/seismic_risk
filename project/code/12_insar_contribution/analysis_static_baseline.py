"""The established figure-led, numbered Chinese analysis-document format."""
from pathlib import Path
import pandas as pd

def table(headers,rows):
    return '\n'.join(['| '+' | '.join(map(str,headers))+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])

def build_analysis(d,selected,s,out,methods,links):
    methods=methods.replace('## 固定的计算口径','### 固定的计算口径')
    names=s['class_order'];matrix=pd.DataFrame(s['matrix'],index=names,columns=names)
    changed=d[d.class_steps.gt(0)];unchanged=d[d.class_steps.eq(0)]
    a,b=s['pair_ids'];lookup=d.set_index('Build_ID');t,c=lookup.loc[a],lookup.loc[b]
    pairs=pd.read_csv(out/'data/block_matched_pairs.csv',float_precision='round_trip')
    trans=table(['Static-only → 加入InSAR','建筑数','占40,000栋比例','占原Static-only等级比例'],[
        [old+' → '+new,f'{matrix.loc[old,new]:,}',f'{100*matrix.loc[old,new]/40000:.4f}%',f'{100*matrix.loc[old,new]/matrix.loc[old].sum():.4f}%']
        for old in names for new in names if old!=new and matrix.loc[old,new]])
    pair_table=table(['升档目标 / 未变级对照','所在地区','质心距离（m）','静态评分差','目标转移 / 对照转移'],[
        [f'{int(r.target_id)} / {int(r.control_id)}',f'{r.district}，{r.subdistrict}',f'{r.distance_m:.2f}',f'{r.static_risk_absdiff:.6f}',r.target_transition+' / '+r.control_transition]
        for _,r in pairs.iterrows()])
    criteria=table(['匹配项目','原条件','本次采用条件'],[
        ['对照关联PS数量','≥10','≥8'],['对照平均相干性','≥0.80','≥0.75'],
        ['对照空间覆盖指标','≥0.10','≥0.05'],['对照综合观测质量Q','≥0.50','≥0.40'],
        ['目标观测及增量条件','原可靠升档候选','保持原条件，258栋候选'],
        ['空间与基准等级','同街区、同街道/区、同Static-only等级，距离≤300 m','保持'],
        ['Static-only风险评分差','≤0.01','保持'],['V_static / H / E绝对差','≤0.05 / ≤0.03 / ≤0.05','保持'],
        ['对照/目标面积与高度比','0.5—2','保持'],['IBSI差 / RMS比 / 对照IBSI','≥0.1 / ≥1.5 / ≤0.15','保持']])
    metric_rows=[
        ['等级转移',t.transition,c.transition],
        ['经度 / 纬度（WGS84）',f'{t.longitude_wgs84:.6f} / {t.latitude_wgs84:.6f}',f'{c.longitude_wgs84:.6f} / {c.latitude_wgs84:.6f}'],
        ['建筑高度（m）',f'{t.Height_m:.2f}',f'{c.Height_m:.2f}'],['建筑面积（m²）',f'{t.Area_m2:.2f}',f'{c.Area_m2:.2f}']]
    for label,key,precision in [
        ('静态易损性V_static','V_static',6),('危险性H_Index','H_Index',6),('暴露性E_Index','E_Index',6),
        ('Static-only评分','R_static_baseline',6),('加入InSAR后评分','R_insar_static_baseline',6),('ΔR（固定静态尺度）','delta_R_static_baseline',6),
        ('IBSI','IBSI',6),('RMS（mm/年）','V_RMS',6),('Tilt（度/年）','Tilt_Angle',6),('DGI（mm/(m·年)）','DGI_Str',6),
        ('综合观测质量Q','Q_insar',6),('关联PS数量','PS_Count',0),('平均相干性','PS_CohMn',6),('空间覆盖指标','PS_Cov',6),
        ('RMS归一化项','V_RMS_n',6),('Tilt异常项','T_anom_n',6),('DGI异常项','DGI_n',6),
        ('IBSI基础项','IBSI_base',6),('IBSI的DGI增量项','IBSI_DGI',6),('IBSI的Tilt增量项','IBSI_tilt',6)]:
        metric_rows.append([label,f'{t[key]:.{precision}f}',f'{c[key]:.{precision}f}'])
    pair_metrics=table(['指标',a,b],metric_rows)
    groups=table(['指标（中位数）','升档建筑','未变级建筑'],[
        [label,f'{changed[key].median():.6f}',f'{unchanged[key].median():.6f}']
        for label,key in [('Static-only评分','R_static_baseline'),('同尺度评分增量ΔR','delta_R_static_baseline'),('距最近静态内部分界','nearest_static_break_distance'),
                          ('IBSI','IBSI'),('RMS（mm/年）','V_RMS'),('DGI（mm/(m·年)）','DGI_Str'),('Q','Q_insar')]])
    district=pd.read_csv(out/'data/district_upgrade_rates.csv')
    district_table=table(['行政区','完整风险样本数','升档建筑数','区内升档率'],[[r.district,f'{int(r.buildings):,}',f'{int(r.upgraded):,}',f'{r.upgraded_pct:.2f}%'] for _,r in district.iterrows()])
    r51263,r17654,r33210=lookup.loc[51263],lookup.loc[17654],lookup.loc[33210]
    early=lookup.loc[[46121,35358]]
    before_gap=t.R_static_baseline-c.R_static_baseline;after_gap=t.R_insar_static_baseline-c.R_insar_static_baseline
    next_margin=s['frozen_static_Jenks_breaks'][3]-c.R_insar_static_baseline
    doc=f'''# 图5.1对应的数值结果分析

![图5.1 固定Static-only基准下的全区变化、等级转移与配对建筑](figures/fig_5_1_static_baseline.png)

本页为当前综合图的数值依据与解释。按照“先以未加InSAR的分级为基准，再加入InSAR信息”的要求，全文采用同一组Static-only易损性归一化参数、风险归一化参数和Jenks等级分界。全部评分、增量、地图和转移标签均遵循这一口径，加入InSAR后不重新估计尺度或分界。观测和模型输入沿用当前正式结果，讨论实验的重算结果单独保存。

综合图仅保留三个面板：（a）全区升档建筑分布、（b）等级转移矩阵、（c）配对建筑的PS形变、拟合速度面与局部梯度案例对比。

## 1. 全部变化建筑与等级转移

40,000栋共同建筑中，2,391栋发生等级变化，占5.9775%；全部为升档，未出现降档；其余37,609栋（94.0225%，图中显示94.02%）维持原等级。所有变化均为相邻一级，没有跨两级及以上转移。Moderate→High为696栋，占原Static-only中风险建筑的{100*matrix.loc['Moderate','High']/matrix.loc['Moderate'].sum():.4f}%、全部升档建筑的{100*696/2391:.4f}%。

{trans}

High和Very High合计由{s['static_high_veryhigh_n']:,}栋（{100*s['static_high_veryhigh_n']/40000:.2f}%）增至{s['insar_high_veryhigh_n']:,}栋（{100*s['insar_high_veryhigh_n']/40000:.2f}%），净增加696栋。High→Very High只改变高风险组内部构成，不增加High与Very High的合计数量。

地图逐一绘制全部2,391个升档建筑质心，无抽样、偏移或插值。密集处点位重叠不改变数量；地图点密集不能直接解释为更高升档概率，应结合第5节以各区完整风险建筑数为分母的升档率。未变级也不等同于评分完全不变：未变级组的ΔR中位数为{unchanged.delta_R_static_baseline.median():.6f}。

## 2. 固定静态尺度、临界风险与指标差异

静态基准风险由原始Static-only信息建立，基准R0与既存Static-only评分逐栋重建一致，最大误差为{s['baseline_reconstruction_max_error']:.3g}，基准等级也与既存Class0_Jenks完全一致。基准易损性参数来自41,939栋有效易损性样本，风险范围及分级来自40,000栋完整风险样本。随后仅在易损性原始量中加入1 + 0.3 × IBSI修正。

{methods}

IBSI≥0，固定截尾归一化为单调映射，H与E也保持相同，因此加入InSAR后评分只能保持或提高，等级不会降低。零降档是当前模型与固定基准共同决定的结果，不是独立的预测准确性证据。本结果不能与两方案分别重估归一化及Jenks分界得到的1,181升档/361降档混用，也不同于以InSAR方案尺度为参照的2,463升档对照。

升档组与未变组距最近Static-only内部分界的距离中位数分别为{changed.nearest_static_break_distance.median():.6f}和{unchanged.nearest_static_break_distance.median():.6f}；距离≤0.01的占比分别为{100*changed.nearest_static_break_distance.le(.01).mean():.2f}%和{100*unchanged.nearest_static_break_distance.le(.01).mean():.2f}%。升档组更接近分界，也具有较高的IBSI和整体形变强度；这种组间差异同时受阈值机制及模型结构约束，不能单独解释为观测到实际结构损伤。

{groups}

## 3. 放宽后的同街区配对：升档、未变级与排序反转

### 3.1 放宽哪些条件

原条件下没有“可靠升档目标—未变级对照”组合。按用户要求逐级放宽，首个有结果的层级仅放宽对照的观测支撑门槛，目标仍来自258栋原可靠升档候选，静态及空间匹配容差保持原样。该层级得到3组配对，未启用更宽的静态容差或跨街区匹配。配对按静态评分差、距离、IBSI差及ID确定顺序；主案例优先选取Moderate→High。

{criteria}

{pair_table}

道路围合街区是邻里代理，不是权属或小区边界。三组建筑轮廓和质心连接线均经道路围合面核对通过；当前配对用于解释模型响应，不等同于因果控制试验。逐组实际差异及双方观测质量保存在[配对CSV](data/block_matched_pairs.csv)。

### 3.2 主配对{a}与{b}

两栋位于{t.district}{t.subdistrict}的同一道路围合街区{t.road_block_id}，质心相距{s['primary_pair_distance_m']:.2f} m。Static-only评分差为{s['primary_pair_static_risk_absdiff']:.6f}，V_static、H及E绝对差分别为{abs(t.V_static-c.V_static):.6f}、{abs(t.H_Index-c.H_Index):.6f}和{abs(t.E_Index-c.E_Index):.6f}，符合保留的静态容差。

{pair_metrics}

图5.1(c)沿用局部案例对比样式，两栋各用80×80 m窗口展示全部关联PS。每栋左图为观测垂向速率、相干性加权拟合速度面及速率增大方向的等长箭头；右图为观测速率减去拟合速度面的残差、20 m以内的Delaunay局部梯度邻接线及各建筑内部梯度超过自身P90的位置。两栋共用观测速率色标和残差色标，等值线限于PS凸包。残差和DGI不是同一个量，黑圈数量还受样本数量影响；箭头不代表实测结构位移或扭转方向。

加入InSAR前，{a}的评分比{b}低{abs(before_gap):.6f}；加入后高{after_gap:.6f}，相对排序反转。{a}由Moderate升至High，{b}保持Moderate，两者ΔR分别为{t.delta_R_static_baseline:.6f}和{c.delta_R_static_baseline:.6f}，前者约为对照的{t.delta_R_static_baseline/c.delta_R_static_baseline:.2f}倍。

目标建筑RMS为对照的{t.V_RMS/c.V_RMS:.2f}倍，但DGI较低；两栋Tilt异常项均为零。{a}的DGI异常归一化项也为零，IBSI基础项为{t.IBSI_base:.6f}，等于其IBSI；对照DGI项对IBSI的增量仅为{c.IBSI_DGI:.6f}。因此这一案例支持“整体形变强度经观测权重调节后，改变风险评分与排序”的解释，不支持“局部梯度主导升档”。

两栋关联PS为{int(t.PS_Count)}与{int(c.PS_Count)}个，平均相干性为{t.PS_CohMn:.3f}与{c.PS_CohMn:.3f}，覆盖指标为{t.PS_Cov:.3f}与{c.PS_Cov:.3f}，Q为{t.Q_insar:.3f}与{c.Q_insar:.3f}。对照通过放宽后的条件，观测支撑仍弱于目标；较低IBSI不能全部归因于较弱形变。覆盖指标沿用PS凸包与模型缓冲区面积的比值，不表示屋顶被观测面积比例，Q也不是结构安全的置信概率。

对照建筑完整评分{c.R_insar_static_baseline:.6f}距固定High下界{s['frozen_static_Jenks_breaks'][3]:.6f}仅{next_margin:.6f}。未变级标签具有分界依赖性，应同时报告连续评分和余量。主配对109与57个原始PS已重新核对，RMS、Tilt和DGI重建值与存量指标一致。

### 3.3 原46121/35358配对的重新定位

固定静态基准后，46121评分由{early.loc[46121,'R_static_baseline']:.6f}升至{early.loc[46121,'R_insar_static_baseline']:.6f}，35358由{early.loc[35358,'R_static_baseline']:.6f}升至{early.loc[35358,'R_insar_static_baseline']:.6f}，两栋均由Moderate升至High。原来的排序反转仍成立，但35358不再作为未变级对照，保留为补充状态差异案例。当前主配对改用{a}/{b}。

## 4. 整体形变、局部差异与组件作用

![图S5.1 当前候选、配对与复核建筑的评分及IBSI组成](figures/fig_S5_1_static_baseline_cases.png)

51263的RMS为{r51263.V_RMS:.6f} mm/年、IBSI为{r51263.IBSI:.6f}，同尺度评分由{r51263.R_static_baseline:.6f}升至{r51263.R_insar_static_baseline:.6f}，ΔR为{r51263.delta_R_static_baseline:.6f}；IBSI基础项占{100*r51263.IBSI_base/r51263.IBSI:.2f}%，主要体现整体形变强度与观测权重的作用。

17654的RMS为{r17654.V_RMS:.6f} mm/年、DGI为{r17654.DGI_Str:.6f} mm/(m·年)，同尺度ΔR为{r17654.delta_R_static_baseline:.6f}。其DGI异常项为1，DGI增量占IBSI的{100*r17654.IBSI_DGI/r17654.IBSI:.2f}%；去除DGI后评分从{r17654.R_insar_static_baseline:.6f}降至{r17654.without_DGI_risk:.6f}，仍为High。局部速度差异提供附加评分修正，但不是该案例升档的必要条件。

33210用于补充Tilt参与修正的情形，Tilt为{r33210.Tilt_Angle:.6f}度/年、Tilt异常归一化项为{r33210.T_anom_n:.6f}。去除Tilt后评分由{r33210.R_insar_static_baseline:.6f}降至{r33210.without_Tilt_risk:.6f}，仍为Moderate。因此“参与修正”与“决定升档”需要区分。

全区在保持静态尺度及分界的条件下，去除DGI或Tilt分别使41栋、22栋相对完整模型改变等级；同时只保留Q加权RMS基础项时为58栋。三者存在重叠及分界效应，不应简单相加。当前17栋候选及复核建筑的逐项指标、质量、组件去除评分与等级均见[案例CSV](data/candidate_building_cases.csv)。其中3栋蓝色未变级对照来自放宽后的同街区配对，不作为损伤已知的安全样本。

## 5. 行政区差异与城市筛查的解释范围

{district_table}

以各区完整风险样本为分母，西山区升档率最高，为8.78%，五华区和盘龙区分别为6.71%和6.47%，官渡区与呈贡区分别为4.07%和2.80%。嵩明县在完整风险样本中仅4栋，表内保留原数量。上述升档率描述本实验固定基准下的等级变化，不能用地图点数直接替代，也不是地震损伤发生率。

综合图支持在相近静态条件下，结合连续评分增量、形变指标与PS观测支撑细化调查次序。未变级对照可以有正的评分增量，较低IBSI也可能与较弱观测支撑有关。当前案例按照模型响应选择，真实震害结局未知；InSAR关联包含建筑邻近缓冲区，观测期为2017—2019年，仍需独立结构调查、震害资料和观测不确定性分析验证实际预测能力。

## 数据与复现

- [全部2,391栋变化建筑](data/all_risk_class_changes.csv)
- [全部40,000栋同尺度评分与指标](data/all_40000_buildings.csv)
- [等级转移汇总](data/risk_class_transition_summary.csv) · [行政区升档率](data/district_upgrade_rates.csv)
- [3组配对及双方实际差异](data/block_matched_pairs.csv) · [放宽条件](data/pair_selection_conditions.json)
- [17栋候选与复核建筑](data/candidate_building_cases.csv) · [变化与未变指标对比](data/changed_unchanged_indicator_comparison.csv)
- [精确统计与冻结参数](data/static_baseline_statistics.json) · [独立核验](data/verification.json)
- [600 dpi PNG](figures/fig_5_1_static_baseline.png) · [SVG](figures/fig_5_1_static_baseline.svg)
- [当前QGIS工程](../../../../plot/12_insar_contribution/qgis/support/static_baseline.qgz) · [计算脚本](../../../../project/code/12_insar_contribution/run_static_baseline.py)
- [返回5.1讨论正文](README.md)
'''
    return doc
