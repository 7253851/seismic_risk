#!/usr/bin/env python3
"""Explore fixed damage-presence regions without inventing building damage labels."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.affinity import translate

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "result/validation/13_event_validation"
PATHS = {
    "config": ROOT / "project/code/13_event_validation/config.json",
    "candidates": ROOT / "data/validation/cases/candidate_building_parameters.csv",
    "regions": ROOT / "data/validation/cases/case_candidates.gpkg",
    "risk": ROOT / "result/risk/scs_paper_method/building_risk.gpkg",
    "metrics": ROOT / "result/vulnerability/scs_paper_method/01_building_vulnerability_metrics.gpkg",
    "study_area": ROOT / "data/study_area/TSX_Total_Extent.shp",
    "south_boundary": ROOT / "data/validation/campuses/yufe_south/yufe_longquan_campus_boundary_wgs84.geojson",
    "north_boundary": ROOT / "data/validation/campuses/yufe_north/yufe_longquan_north_campus_boundary_wgs84.geojson",
}
METRICS = ["risk_median", "risk_high_share_pct", "risk_top10_share_pct",
           "risk_rank_shift_median_pp", "vulnerability_rank_shift_median_pp"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def percentile(values: pd.Series) -> pd.Series:
    """Empirical midpoint percentile, with exact-value ties assigned their midpoint."""
    return (values.rank(method="average") - 0.5) / values.notna().sum() * 100


def summarize(frame: pd.DataFrame) -> dict:
    out = {"risk_n": len(frame)}
    if frame.empty:
        return out
    out.update({
        "risk_median": frame.Risk_Final.median(),
        "risk_p90": frame.Risk_Final.quantile(0.9),
        "risk_max": frame.Risk_Final.max(),
        "risk_global_percentile_median": frame.risk_percentile.median(),
        "risk_high_n": int(frame.risk_high.sum()),
        "risk_high_share_pct": frame.risk_high.mean() * 100,
        "risk_top10_n": int(frame.risk_top10.sum()),
        "risk_top10_share_pct": frame.risk_top10.mean() * 100,
        "static_risk_top10_share_pct": frame.static_risk_top10.mean() * 100,
        "risk_top10_change_pp": (frame.risk_top10.mean() - frame.static_risk_top10.mean()) * 100,
        "risk_rank_shift_median_pp": frame.risk_rank_shift_pp.median(),
        "vulnerability_rank_shift_median_pp": frame.vulnerability_rank_shift_pp.median(),
        "static_vulnerability_percentile_median": frame.static_vulnerability_percentile.median(),
        "corrected_vulnerability_percentile_median": frame.corrected_vulnerability_percentile.median(),
        "IBSI_median": frame.IBSI.median(),
        "H_Index_median": frame.H_Index.median(),
        "E_Index_median": frame.E_Index.median(),
    })
    return out


def select(points: gpd.GeoSeries, area) -> np.ndarray:
    return np.asarray(points.sindex.query(area, predicate="intersects"), dtype=int)


def fmt(value, digits=2):
    return "—" if pd.isna(value) else f"{value:.{digits}f}"


def main():
    cfg = json.loads(PATHS["config"].read_text())
    for key, value in cfg.get("inputs", {}).items():
        PATHS[key] = ROOT / value
    # Include SHP sidecars and code in the read-only fingerprint audit.
    protected = dict(PATHS)
    for ext in (".dbf", ".shx", ".prj", ".cpg"):
        p = PATHS["study_area"].with_suffix(ext)
        if p.exists():
            protected[f"study_area{ext}"] = p
    protected["code"] = Path(__file__).resolve()
    before = {k: {"path": str(p), "sha256": sha(p)} for k, p in protected.items()}
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    out = BASE / "results" / f"{stamp}_regional_presence"
    out.mkdir(parents=True, exist_ok=False)
    print(f"Output: {out}", flush=True)
    candidates = pd.read_csv(PATHS["candidates"], encoding="utf-8-sig")
    assert candidates.damage_status.eq("unknown").all()
    assert not candidates.Build_ID.duplicated().any()
    areas = gpd.read_file(PATHS["regions"], layer="selection_areas").to_crs(32648)
    epicenter = gpd.read_file(PATHS["regions"], layer="epicenter").to_crs(32648).geometry.iloc[0]
    study = gpd.read_file(PATHS["study_area"]).to_crs(32648).geometry.union_all()
    risk = gpd.read_file(PATHS["risk"], layer="building_risk_scs").to_crs(32648)
    inventory = gpd.read_file(PATHS["metrics"], layer="building_vulnerability_metrics").to_crs(32648)
    assert not risk.Build_ID.duplicated().any() and not inventory.Build_ID.duplicated().any()
    risk = risk.merge(inventory[["Build_ID", "V_static", "IBSI"]], on="Build_ID", validate="one_to_one")
    assert risk[["Risk_Final", "Vul_Index", "V_static", "IBSI", "H_Index", "E_Index"]].notna().all().all()
    # Strict no-InSAR baseline: same final-sample P1-P99 processing as current V.
    final_v = inventory.loc[inventory.Vul_Valid.eq(1), ['Build_ID','V_static']].copy()
    assert len(final_v) == 41939
    low, high = final_v.V_static.quantile([.01,.99])
    final_v['V0'] = ((final_v.V_static.clip(low,high)-low)/(high-low)).clip(0,1)
    risk = risk.merge(final_v[['Build_ID','V0']],on='Build_ID',validate='one_to_one')
    risk["static_risk_raw"] = risk.H_Index * risk.V0 * risk.E_Index
    risk["risk_percentile"] = percentile(risk.Risk_Final)
    risk["static_risk_percentile"] = percentile(risk.static_risk_raw)
    risk["risk_rank_shift_pp"] = risk.risk_percentile - risk.static_risk_percentile
    risk["static_vulnerability_percentile"] = percentile(risk.V_static)
    risk["corrected_vulnerability_percentile"] = percentile(risk.Vul_Index)
    risk["vulnerability_rank_shift_pp"] = risk.corrected_vulnerability_percentile - risk.static_vulnerability_percentile
    risk["risk_high"] = risk.Risk_Class.isin(["High", "Very High"])
    threshold = risk.Risk_Final.quantile(1 - cfg["top_fraction"])
    static_threshold = risk.static_risk_raw.quantile(1 - cfg["top_fraction"])
    risk["risk_top10"] = risk.Risk_Final.ge(threshold)
    risk["static_risk_top10"] = risk.static_risk_raw.ge(static_threshold)
    points = risk.geometry.representative_point()
    inventory_points = inventory.geometry.representative_point()
    excluded = areas.geometry.union_all()
    case_ids = set(candidates.Build_ID)
    groups = []
    for _, a in areas.iterrows():
        groups.append(("location", a.location_id, a.location_name, a.geometry,
                       set(candidates.loc[candidates.location_id.eq(a.location_id), "Build_ID"])))
    case_geometries = {}
    for cid, aa in areas.groupby("case_id", sort=True):
        geom = aa.geometry.union_all()
        case_geometries[cid] = geom
        groups.append(("case", cid, aa.case_name.iloc[0], geom,
                       set(candidates.loc[candidates.case_id.eq(cid), "Build_ID"])))
    group_rows = []
    observed = {}
    for level, gid, name, geom, ids in groups:
        frame = risk.loc[risk.Build_ID.isin(ids)]
        recomputed_ids = set(risk.iloc[select(points, geom)].Build_ID)
        assert recomputed_ids == set(frame.Build_ID), f"Candidate selection mismatch: {gid}"
        row = {"level": level, "group_id": gid, "name": name,
               "region_damage_presence": "assumed_present" if level == "case" else "unknown",
               "case_damage_presence": "assumed_present", "building_damage_status": "unknown",
               "candidate_n": len(ids), "missing_risk_n": len(ids) - len(frame),
               "risk_coverage_pct": len(frame) / len(ids) * 100 if ids else np.nan,
               "selection_area_ha": geom.area / 10000, **summarize(frame)}
        group_rows.append(row)
        if level == "case":
            observed[gid] = row
    background = risk.loc[~risk.Build_ID.isin(case_ids)]
    group_rows.append({"level": "background", "group_id": "BACKGROUND", "name": "全区背景（震害未知）",
                       "region_damage_presence": "unknown", "building_damage_status": "unknown", **summarize(background)})
    group_rows.append({"level": "pooled_descriptive", "group_id": "ALL", "name": "全部候选（仅描述）",
                       "region_damage_presence": "assumed_present", "building_damage_status": "unknown",
                       "candidate_n": len(case_ids), **summarize(risk.loc[risk.Build_ID.isin(case_ids)])})
    group_table = pd.DataFrame(group_rows)
    group_table.to_csv(out / "regional_statistics.csv", index=False, encoding="utf-8-sig")
    case_buildings = candidates[["Build_ID", "case_id", "case_name", "location_id", "damage_status"]].merge(
        pd.DataFrame(risk.drop(columns="geometry")), on="Build_ID", how="left", validate="one_to_one")
    case_buildings["case_damage_presence"] = "assumed_present"
    case_buildings.to_csv(out / "case_buildings_latest.csv", index=False, encoding="utf-8-sig")
    # Fixed-shape regional simulations preserve within-window spatial dependence.
    rng = np.random.default_rng(cfg["seed"])
    windows, comparisons, sampling_audit = [], [], []
    for cid, geom in case_geometries.items():
        obs = observed[cid]
        if not obs["risk_n"]:
            sampling_audit.append({"case_id": cid, "status": "no_model_coverage", "accepted": 0})
            continue
        n_inventory = len(select(inventory_points, geom))
        assert n_inventory == obs["candidate_n"]
        centroid = geom.centroid
        original_distance = centroid.distance(epicenter)
        distance_tol = max(cfg["epicentral_distance_minimum_tolerance_m"],
                           original_distance * cfg["epicentral_distance_relative_tolerance"])
        count_tol = cfg["building_count_relative_tolerance"]
        coverage = obs["risk_n"] / n_inventory
        accepted, attempts = [], 0
        while len(accepted) < cfg["reference_windows_per_case"] and attempts < cfg["maximum_attempts_per_case"]:
            attempts += 1
            radius = cfg["translation_radius_m"] * np.sqrt(rng.random())
            angle = rng.uniform(0, 2 * np.pi)
            dx, dy = radius * np.cos(angle), radius * np.sin(angle)
            area = translate(geom, xoff=dx, yoff=dy)
            if abs(area.centroid.distance(epicenter) - original_distance) > distance_tol:
                continue
            if area.intersects(excluded) or not study.covers(area):
                continue
            ni = len(select(inventory_points, area))
            if not n_inventory * (1 - count_tol) <= ni <= n_inventory * (1 + count_tol):
                continue
            indices = select(points, area)
            if not obs["risk_n"] * (1 - count_tol) <= len(indices) <= obs["risk_n"] * (1 + count_tol):
                continue
            if abs(len(indices) / ni - coverage) > cfg["risk_coverage_absolute_tolerance"]:
                continue
            row = {"case_id": cid, "sample_id": len(accepted) + 1, "inventory_n": ni,
                   "translation_x_m": dx, "translation_y_m": dy,
                   "epicentral_distance_m": area.centroid.distance(epicenter),
                   **summarize(risk.iloc[indices])}
            accepted.append(row)
            windows.append({**row, "geometry": area})
        audit = {"case_id": cid, "status": "complete" if len(accepted) == cfg["reference_windows_per_case"] else "insufficient_windows",
                 "accepted": len(accepted), "attempts": attempts, "inventory_n": n_inventory,
                 "original_epicentral_distance_m": original_distance, "distance_tolerance_m": distance_tol}
        sampling_audit.append(audit)
        print(json.dumps(audit, ensure_ascii=False), flush=True)
        if not accepted:
            continue
        ref = pd.DataFrame(accepted)
        for metric in METRICS:
            vals = ref[metric].to_numpy()
            value = obs[metric]
            tol = np.finfo(float).eps * 100 * max(1, abs(value))
            upper = (1 + np.count_nonzero(vals >= value - tol)) / (len(vals) + 1)
            comparisons.append({"case_id": cid, "metric": metric, "observed": value,
                                "reference_n": len(vals), "reference_median": np.median(vals),
                                "reference_q05": np.quantile(vals, 0.05), "reference_q95": np.quantile(vals, 0.95),
                                "difference_from_reference_median": value - np.median(vals),
                                "reference_midpoint_percentile": 100 * (np.count_nonzero(vals < value - tol) + 0.5 * np.count_nonzero(np.abs(vals - value) <= tol)) / len(vals),
                                "upper_reference_tail_fraction": upper,
                                "interpretation": "Exploratory conditional reference fraction, not a building-damage accuracy or general inferential p-value."})
    pd.DataFrame(comparisons).to_csv(out / "spatial_reference_comparison.csv", index=False, encoding="utf-8-sig")
    if windows:
        wg = gpd.GeoDataFrame(windows, geometry="geometry", crs=risk.crs)
        wg.to_file(out / "spatial_reference_windows.gpkg", layer="translated_reference_windows", driver="GPKG")
        pd.DataFrame(wg.drop(columns="geometry")).to_csv(out / "spatial_reference_samples.csv", index=False, encoding="utf-8-sig")
    after = {k: sha(p) for k, p in protected.items()}
    assert all(before[k]["sha256"] == after[k] for k in before), "An input changed during validation"
    assert case_buildings.damage_status.eq("unknown").all()
    manifest = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "config": cfg,
                "inputs": before, "inputs_unchanged": True, "building_damage_labels_unchanged": True,
                "risk_sample_n": len(risk), "candidate_n": len(candidates), "matched_risk_n": case_buildings.Risk_Final.notna().sum().item(),
                "matched_region_units_n": sum(r["risk_n"] > 0 for r in observed.values()),
                "top10_threshold": threshold, "static_top10_raw_threshold": static_threshold,
                "global_top10_n": int(risk.risk_top10.sum()), "global_static_top10_n": int(risk.static_risk_top10.sum()),
                "selection_geometry_check_passed": True, "sampling_audit": sampling_audit,
                "percentile_reference": "same 40,000-building complete risk sample for static and corrected scores",
                "static_comparison": "rank(H_Index * N1-99(V_static) * E_Index); normalization on same 41939; H/E and 40000-building cohort fixed",
                "limitations": ["Regional presence assumption does not identify damaged buildings.",
                                "Background damage unknown; sampled windows can overlap each other and are not independent surveyed controls.",
                                "Only two named case regions have model coverage; subcampuses are not independent earthquake cases.",
                                "Reference matching does not control building typology or all shaking/site differences.",
                                "Envelope hazard is not the observed 2026 event ground motion; InSAR is from 2017-2019."]}
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    lines = ["# 震害存在区域与当前模型的探索性统计对照", "",
             "区域层面的震害存在按用户假设设为存在；具体受损建筑及震害等级未知。背景区域震害也未知。", "",
             f"当前全区风险样本{len(risk):,}栋；候选{len(candidates)}栋，匹配最新风险{manifest['matched_risk_n']}栋。正式模型与原始标签均未改写。", "",
             "## 区域描述", "", "|区域|候选栋数|有效风险|风险中位数|高/极高比例|全区前10%比例|InSAR风险排名变化中位数（百分点）|",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for row in group_rows:
        if row["level"] not in ("case", "background"):
            continue
        lines.append(f"|{row['name']}|{fmt(row.get('candidate_n', np.nan), 0)}|{row['risk_n']}|{fmt(row.get('risk_median', np.nan), 4)}|{fmt(row.get('risk_high_share_pct', np.nan))}%|{fmt(row.get('risk_top10_share_pct', np.nan))}%|{fmt(row.get('risk_rank_shift_median_pp', np.nan))}|")
    lines += ["", "表中高/极高使用全区既有Jenks类别；前10%使用全区冻结分位阈值。未对子区域重新归一化。财大采用南/北院截图边界，农大采用东/西苑OSM边界；当前不使用任何分析缓冲区。江南春没有完整边界，本轮不设统计范围，不作零风险或零建筑结论。", "",
              "## 空间参照", "", "在每个案例3km邻域内均匀随机平移原范围，面积和形状不变；建筑总数、有效风险数均在案例±25%内，覆盖率差≤15个百分点；震中距离差≤max(500m, 原距离×20%)。排除与现有案例重叠及超出研究范围的窗口。", "",
              "|案例|指标|案例值|参照中位数|参照5%—95%范围|案例在参照分布中的百分位|",
              "|---|---|---:|---:|---:|---:|"]
    names = {"risk_median": "风险中位数", "risk_high_share_pct": "高/极高比例（%）", "risk_top10_share_pct": "全区前10%比例（%）", "risk_rank_shift_median_pp": "InSAR风险排名变化（百分点）", "vulnerability_rank_shift_median_pp": "InSAR易损性排名变化（百分点）"}
    for row in comparisons:
        digits = 4 if row["metric"] == "risk_median" else 2
        lines.append(f"|{row['case_id']}|{names[row['metric']]}|{fmt(row['observed'], digits)}|{fmt(row['reference_median'], digits)}|{fmt(row['reference_q05'], digits)}—{fmt(row['reference_q95'], digits)}|{fmt(row['reference_midpoint_percentile'])}|")
    lines += ["", "空间参照百分位和上尾比例用于描述案例是否偏高；它们不是震害分类准确率，也不作为普适显著性结论。模拟999个窗口不会增加真实独立震害案例的数量。", "",
              "## InSAR比较", "", "静态对照固定同一批完整风险建筑及H/E，比较H×N1-99(V_static)×E与当前风险的全区排名；不新设静态风险类别。分数或排名上升只表示案例的相对关注优先级变化，不能据此认定精度提高。", "",
              "校园整体存在震害的假设不进一步推定各分院均受灾，分院只作描述性汇总。截图和OSM边界均为校园参考边界，不是震害界线。", "",
              "## 结论范围", "", "若某案例排名较高，可表述为该震害存在区域与模型较高评分具有空间一致性；若不偏高，应如实报告缺乏这种支持。区域内只要有少量受损楼栋，中位数仍可能较低，低中位数不能直接证明模型失败。", "",
              f"没有逐栋受损/未受损标签和等级，无法估计准确率、召回率或震害等级预测误差。仅有财大、农大两个可统计案例，不把{manifest['matched_risk_n']}栋建筑当成同样数量的独立震害案例。", "",
              "当前危险性是多断层情景包络，相近震中距离也不等于相同实际震动；用途、结构类型、场地条件与2017—2019年InSAR至2026年的时间间隔仍限制解释。", "",
              "输入指纹、覆盖率、选区复核和抽样数量见run_manifest.json。所有输入逐字节核对未变。", "",
              "计算参照尾比例采用加一形式(1+至少同样极端的窗口数)/(1+窗口数)。该形式参考[SciPy随机置换计算说明](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html)，本研究空间参照设计及解释边界仍由上述规则限定。"]
    (out / "report_CN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(group_table.loc[group_table.level.isin(["case", "background"]), ["name", "risk_n", "risk_median", "risk_high_share_pct", "risk_rank_shift_median_pp"]].to_string(index=False), flush=True)
    print(f"Report: {out / 'report_CN.md'}", flush=True)


if __name__ == "__main__":
    main()
