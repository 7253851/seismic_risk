#!/usr/bin/env python3
"""Read archived inputs/results and describe fields. Does not execute a model."""
from pathlib import Path
import hashlib
import json
import sqlite3
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
FIG = ROOT / "plot/07_ibsi/output"
OUT = FIG / "statistics"
SOURCE = ROOT / "result/vulnerability/scs_paper_method/01_building_vulnerability_metrics.gpkg"
PS_SOURCE = ROOT / "result/intermediate/vulnerability_inputs/building_ps_points.gpkg"
RESULT = SOURCE.parent

# Group, display, saved field, actual scale, definition, role.
FIELDS = [
 ("形变分量", "整体形变强度 RMS", "V_RMS", "mm/年（用户确认）", "同坐标PS记录速率取算术平均后，计算建筑关联PS速率的非加权均方根；不保留升降符号", "图中原值；入模前归一化"),
 ("形变分量", "倾斜指标 Tilt", "Tilt_Angle", "°/年（一年等效倾斜率）", "相干性加权速率平面梯度g（mm/(m·年)）先除以1000统一长度单位，再经degrees(atan(g/1000))转换；非实测瞬时倾角", "图中原值；入模前转为异常增强项"),
 ("形变分量", "局部差异形变 DGI", "DGI_Str", "mm/(m·年)", "建筑内点级DGI严格高于本建筑P90的点，取其均值与最大值各0.5加权", "图中原值；IBSI使用此字段"),
 ("归一化分量", "RMS归一化值", "V_RMS_n", "无量纲 [0,1]", "V_RMS按共同有效样本P1–P99截尾后进行min–max归一化", "IBSI基础分量"),
 ("归一化分量", "Tilt异常增强项", "T_anom_n", "无量纲 [0,1]", "Tilt_Angle不高于P75取0；P75–P99线性缩放；不低于P99取1", "IBSI倾斜增强分量"),
 ("归一化分量", "DGI异常增强项", "DGI_n", "无量纲 [0,1]", "DGI_Str不高于P75取0；P75–P99线性缩放；不低于P99取1", "IBSI局部差异增强分量"),
 ("观测质量", "综合观测质量", "Q_insar", "无量纲 [0,1]", "0.25 Count_n + 0.15 Dens_n + 0.35 Coh_n + 0.25 Cov_n", "IBSI质量权重"),
 ("综合状态", "综合建筑状态 IBSI", "IBSI", "无量纲 [0,1]", "clip(Q_insar × V_RMS_n × (1 + 0.15 T_anom_n + 0.25 DGI_n),0,1)", "最终IBSI；直接读取保存值"),
 ("观测质量原值", "建筑关联PS记录数", "PS_Count", "条建筑–PS关联记录", "建筑5 m外扩关联区内记录数；相同坐标合并前计数", "质量筛选及Count_n来源"),
 ("观测质量原值", "PS密度", "PS_Dens", "关联记录数/1000 m²", "PS_Count × 1000 / 建筑几何面积", "质量筛选及Dens_n来源"),
 ("观测质量原值", "平均相干性", "PS_CohMn", "无量纲", "建筑关联PS记录相干性的算术平均", "质量筛选及Coh_n来源"),
 ("观测质量原值", "PS覆盖率", "PS_Cov", "无量纲 [0,1]", "min(PS点凸包面积 / 建筑10 m外扩缓冲区面积,1)", "质量筛选及Cov_n来源"),
 ("观测质量中间量", "PS点凸包面积", "PS_HullA", "m²", "建筑关联PS点的平面凸包面积", "PS_Cov分子"),
 ("观测质量中间量", "质量缓冲区面积", "PS_BufA", "m²", "建筑几何外扩10 m后的面积", "PS_Cov分母"),
 ("观测质量归一化", "PS数量归一化值", "Count_n", "无量纲 [0,1]", "PS_Count按P1–P99截尾后min–max归一化", "Q_insar分量；权重0.25"),
 ("观测质量归一化", "PS密度归一化值", "Dens_n", "无量纲 [0,1]", "PS_Dens按P1–P99截尾后min–max归一化", "Q_insar分量；权重0.15"),
 ("观测质量归一化", "相干性归一化值", "Coh_n", "无量纲 [0,1]", "PS_CohMn按P1–P99截尾后min–max归一化", "Q_insar分量；权重0.35"),
 ("观测质量归一化", "覆盖率归一化值", "Cov_n", "无量纲 [0,1]", "PS_Cov按P1–P99截尾后min–max归一化", "Q_insar分量；权重0.25"),
 ("形变计算中间量", "合并后PS坐标数", "N_Pt_Deform", "个唯一坐标", "在单栋建筑内将同坐标记录速率及相干性取算术平均后的点数", "RMS、Tilt和DGI计算支持"),
 ("形变计算中间量", "速率平面坡度模", "Tilt_Grad", "mm/(m·年)", "相干性加权速率平面在两个平面坐标方向的坡度模sqrt(a0²+a1²)", "Tilt_Angle的变换输入"),
 ("DGI计算中间量", "有效邻接边数", "N_Edg_Tot", "条边", "Delaunay邻接边中距离>0且≤20 m的边数", "局部速率梯度计算支持"),
 ("DGI计算中间量", "具有有效邻居的PS点数", "N_Pt_DGI", "个点", "至少存在一条有效邻接边的合并后PS点数", "点级DGI样本数"),
 ("DGI计算中间量", "建筑内异常DGI点数", "N_Pt_Abn", "个点", "点级DGI严格高于同一建筑点级DGI分布P90的点数", "DGI_Str统计支持"),
 ("DGI计算中间量", "全部有效点DGI均值", "DGI", "mm/(m·年)", "建筑内全部有效点的相干性加权局部速率梯度算术平均", "不同于图中DGI_Str；不直接入模"),
 ("DGI计算中间量", "全部有效点DGI最大值", "DGI_Max", "mm/(m·年)", "建筑内全部有效点级DGI的最大值", "局部梯度峰值"),
 ("DGI计算中间量", "建筑内点级DGI的P90", "DGI_P90", "mm/(m·年)", "每栋建筑内部点级DGI分布的第90百分位数", "选择异常点的建筑内阈值"),
 ("DGI计算中间量", "异常点DGI均值", "DGI_AbnMn", "mm/(m·年)", "建筑内点级DGI严格高于本建筑P90的异常点均值", "DGI_Str的均值分量"),
 ("后续修正因子", "状态修正因子", "F_IBSI", "无量纲；非IBSI", "1 + 0.3 IBSI；用于最终归一化前的基准脆弱性乘法修正", "IBSI下游输出；单独标识"),
 ("有效性标识", "PS质量通过标识", "PS_Q_OK", "0/1", "PS数量、密度、平均相干性和覆盖率联合通过保存阈值取1", "质量筛选标识"),
 ("有效性标识", "Tilt拟合有效标识", "Tilt_OK", "0/1", "保存的相干性加权速率平面拟合有效标识", "形变计算有效性"),
 ("有效性标识", "最终入样标识", "Vul_Valid", "0/1", "保存的最终入样标识；本表共同样本取Vul_Valid=1", "与五面板图同一统计样本"),
]

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(2**20),b""):h.update(b)
    return h.hexdigest()

def describe(x, total):
    x=pd.to_numeric(x,errors="coerce").to_numpy(float)
    x=x[np.isfinite(x)]
    n=len(x)
    if n==0:
        return {"N":0,"missing":total,"zero":0,**{k:None for k in ["mean","sd","min","P25","median","P75","P90","max"]}}
    q=np.quantile(x,[0,.25,.5,.75,.9,1])
    return {"N":n,"missing":total-n,"zero":int((x==0).sum()),"mean":float(x.mean()),"sd":float(x.std(ddof=1)) if n>1 else None,
            **dict(zip(["min","P25","median","P75","P90","max"],map(float,q)))}

def main():
    paths={SOURCE,PS_SOURCE,RESULT/"run_manifest.json",RESULT/"normalization_parameters.csv",ROOT/"project/code/Vulnerability/config.json",ROOT/"project/code/Vulnerability/pipeline.py"}
    paths.update(p for base in [ROOT/"project",ROOT/"manuscript",*(ROOT/"plot").glob("*/qgis"),ROOT/"plot/shared/styles"] for p in base.rglob("*") if p.is_file())
    paths.update(FIG.glob("*.png"))
    before={str(p):sha(p) for p in sorted(paths)}
    fields=[f[2] for f in FIELDS]
    query='SELECT "Build_ID",'+','.join('"'+f+'"' for f in fields)+' FROM "building_vulnerability_metrics" ORDER BY "Build_ID"'
    with sqlite3.connect(SOURCE.as_uri()+"?mode=ro",uri=True) as con:
        all_b=pd.read_sql_query(query,con)
    b=all_b.loc[all_b.Vul_Valid.eq(1)]
    assert len(b)==41939 and len(all_b)==57228 and all_b.Build_ID.is_unique
    rows=[]; definitions=[]
    for group,label,field,scale,definition,role in FIELDS:
        s=describe(b[field],len(b));full=describe(all_b[field],len(all_b))
        assert s["N"]==41939 and s["missing"]==0
        rows.append({"group":group,"indicator":label,"field":field,**s})
        definitions.append({"group":group,"indicator":label,"field":field,"scale":scale,"definition":definition,"role":role,
                            "inventory_available_N":full["N"],"inventory_missing_N":full["missing"]})
    graph_stats=json.loads((FIG/"indicator_statistics.json").read_text())
    by_field={r["field"]:r for r in rows}
    for r in graph_stats:
        a=by_field[r["field"]]
        assert np.isclose(a["mean"],r["mean"],rtol=1e-12) and np.isclose(a["sd"],r["sd_ddof1"],rtol=1e-12)
        assert a["N"]==r["N"]
    with sqlite3.connect(PS_SOURCE.as_uri()+"?mode=ro",uri=True) as con:
        ps=pd.read_sql_query('SELECT "v_los","v_vertical","inc","coh" FROM "building_ps_points"',con)
    assert len(ps)==1183203
    ps_labels=[("v_los","视线向形变速率","mm/年（用户确认）"),
               ("v_vertical","垂向位移速率","mm/年；v_los/cos(inc)，inc为弧度"),
               ("inc","入射角","弧度"),
               ("coh","PS相干性","无量纲")]
    ps_rows=[{"field":f,"indicator":label,"scale":scale,**describe(ps[f],len(ps))} for f,label,scale in ps_labels]
    config=json.loads((ROOT/"project/code/Vulnerability/config.json").read_text())["model"]
    fixed=[
      ["PS关联","建筑外扩关联距离",config["building_buffer_m_for_ps_association"],"m","已归档关联范围"],
      ["PS质量","覆盖率分母缓冲距离",config["quality_buffer_m"],"m","建筑几何缓冲区面积"],
      ["PS质量","最小PS记录数",config["quality_thresholds"]["ps_count_min"],"条","≥"],
      ["PS质量","最小PS密度",config["quality_thresholds"]["ps_density_per_1000m2_min"],"记录数/1000 m²","≥"],
      ["PS质量","最低平均相干性",config["quality_thresholds"]["mean_coherence_min"],"无量纲","≥"],
      ["PS质量","最低覆盖率",config["quality_thresholds"]["coverage_min"],"无量纲","≥"],
      ["Tilt","拟合最少唯一坐标数",config["tilt_min_points"],"个","程序以合并后的点坐标计数"],
      ["DGI","Delaunay邻接边最大距离",config["dgi_max_edge_m"],"m","0 < 距离 ≤ 20 m"],
      ["DGI","建筑内异常点百分位",config["dgi_within_building_percentile"],"百分位","严格大于建筑内P90"],
      ["DGI","异常均值权重",.5,"无量纲","保存定义中的固定系数"],
      ["DGI","异常最大值权重",.5,"无量纲","保存定义中的固定系数"],
      ["归一化","截尾下百分位",config["normalization_lower_percentile"],"百分位","RMS及质量分量"],
      ["归一化","截尾上百分位",config["normalization_upper_percentile"],"百分位","RMS及质量分量"],
      ["异常增强","异常起始百分位",config["anomaly_lower_percentile"],"百分位","Tilt及DGI增强项"],
      ["Q_insar","Count_n权重",.25,"无量纲","保存公式"],
      ["Q_insar","Dens_n权重",.15,"无量纲","保存公式"],
      ["Q_insar","Coh_n权重",.35,"无量纲","保存公式"],
      ["Q_insar","Cov_n权重",.25,"无量纲","保存公式"],
      ["IBSI","Tilt增强系数 beta",config["beta_tilt"],"无量纲","乘T_anom_n"],
      ["IBSI","DGI增强系数 gamma",config["gamma_dgi"],"无量纲","乘DGI_n"],
      ["IBSI","下限",0,"无量纲","复合指标截限"],
      ["IBSI","上限",1,"无量纲","复合指标截限"],
      ["后续修正","状态修正系数 alpha",config["alpha_vulnerability"],"无量纲","F_IBSI = 1 + alpha × IBSI"],
    ]
    norm=pd.read_csv(RESULT/"normalization_parameters.csv")
    use=["V_RMS","Tilt_Angle","DGI_Str","PS_Count","PS_Dens","PS_CohMn","PS_Cov"]
    norm=norm.set_index("indicator").loc[use].reset_index()
    norm_rows=[]
    for _,r in norm.iterrows():
        norm_rows.append({"field":r.indicator,"normalized_field":r.normalized_field,"method":r.normalization,
                          "N":int(r["count"]),"P01":None if pd.isna(r.p01) else float(r.p01),
                          "P75":None if pd.isna(r.p75) else float(r.p75),"P99":float(r.p99)})
    after={str(p):sha(p) if p.exists() else None for p in sorted(paths)}
    changed=[p for p in before if before[p]!=after[p]]
    assert before[str(SOURCE)]==after[str(SOURCE)] and before[str(PS_SOURCE)]==after[str(PS_SOURCE)]
    payload={"valid_N":len(b),"inventory_N":len(all_b),"PS_association_N":len(ps),
             "PS_unique_source_point_N":1121990,"PS_multi_building_source_point_N":59648,
             "statistics":rows,"definitions":definitions,"raw_PS_statistics":ps_rows,
             "fixed_parameters":fixed,"normalization_thresholds":norm_rows,
             "metadata":{"source_result":"01_building_vulnerability_metrics.gpkg / building_vulnerability_metrics",
                         "source_PS":"building_ps_points.gpkg / building_ps_points",
                         "version":"2026-10-16 倾斜单位修正版；下游归一化、IBSI、脆弱性及风险已同步重算",
                         "cohort":"保存的Vul_Valid=1共同样本；与五面板图一致",
                         "SD":"样本标准差，ddof=1；分位数使用线性插值",
                         "units":"图中三个形变分量是IBSI入模归一化前字段；RMS为mm/年，Tilt为°/年，DGI为mm/(m·年)；速率单位由用户确认，入射角原始约定仍待核实",
                         "PS_note":"PS表以建筑–PS关联记录为统计单位；重叠缓冲区可重复关联同一源PS，不等同于独立PS点样本",
                         "eligibility_note":"原保存流程质量通过42833栋；最终41939栋；894栋质量通过但DGI_Str为0未进入最终样本。本统计不新增筛选",
                         "interpretation":"IBSI是相对建筑形变状态指标，不直接代表结构损伤或地震风险"},
             "protection":{"checked_files":len(paths),"all_unchanged":not changed,"changed_files":changed,
                           "before_sha256":before,"after_sha256":after},
             "analysis_scope":"SQLite mode=ro; only describe saved fields; no assessment model imports or execution"}
    (OUT/"IBSI_statistics_data.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    pd.DataFrame(rows).to_csv(FIG/"IBSI_intermediate_indicators_statistics.csv",index=False,encoding="utf-8-sig")
    print(json.dumps({"building_fields":len(rows),"valid_N":len(b),"raw_PS_fields":len(ps_rows),"PS_associations":len(ps),"fixed_parameters":len(fixed),"normalization_rows":len(norm_rows),"protected_files_unchanged":not changed,"changes":changed},ensure_ascii=False))

if __name__=="__main__":main()
