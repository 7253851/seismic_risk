"""Run the existing supplementary GNSS/PS trend matching in the current workspace.

Numerical conventions follow 05GNSS_PS_U_valid.py: raw GNSS-U, ref0,
year+(DOY-1)/365.25, global Top10 by trend error, then 0.7 trend + 0.3 distance.
The selected matches are a descriptive consistency experiment, not an unbiased
accuracy estimate. Increment lag never shifts the rate or displacement pairs.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import WORKSPACE_ROOT, resolve_path

DEFAULT_CONFIG = Path(__file__).with_name("config.json")


def fingerprint(path: Path, digest: bool = True) -> dict:
    info = {"path": str(path), "bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns}
    if digest:
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                sha.update(block)
        info["sha256"] = sha.hexdigest()
    return info


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def parse_date_column(column: str) -> pd.Timestamp | None:
    match = re.fullmatch(r"F(\d{4})_(\d{1,2})_(\d{1,2})(?:_(\d{1,2})_(\d{1,2}))?", column)
    if not match:
        return None
    return pd.Timestamp(*[int(v or 0) for v in match.groups()])


def time_axis(dates) -> np.ndarray:
    """Preserve the supplementary script's decimal-year convention exactly."""
    dt = pd.DatetimeIndex(dates)
    if dt.hasnans or dt.duplicated().any() or not dt.is_monotonic_increasing:
        raise ValueError("Dates must be finite, unique and increasing")
    return np.asarray(dt.year + (dt.dayofyear - 1) / 365.25, dtype=float)


def slopes(matrix: np.ndarray, dates) -> np.ndarray:
    values = np.atleast_2d(np.asarray(matrix, dtype=float))
    t = time_axis(dates)
    if values.shape[1] != len(t) or len(t) < 3:
        raise ValueError("At least three matching epochs are required")
    centered = t - t.mean()
    # Center both terms, as in the source script; NaN rows remain invalid.
    return ((values - values.mean(axis=1, keepdims=True)) @ centered) / (centered @ centered)


def haversine_km(lon, lat, station_lon: float, station_lat: float) -> np.ndarray:
    longitude, latitude = np.deg2rad(lon), np.deg2rad(lat)
    x, y = np.deg2rad([station_lon, station_lat])
    a = np.sin((latitude-y)/2)**2 + np.cos(latitude)*np.cos(y)*np.sin((longitude-x)/2)**2
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def pair_metrics(gnss, insar) -> dict:
    g, p = np.asarray(gnss, float), np.asarray(insar, float)
    valid = np.isfinite(g) & np.isfinite(p)
    g, p = g[valid], p[valid]
    if len(g) < 3:
        raise ValueError("Insufficient paired observations")
    r = float(np.corrcoef(g, p)[0, 1]) if np.std(g) > 0 and np.std(p) > 0 else None
    return {"n_pairs": int(len(g)), "pearson_r": r,
            "rmse_mm": float(np.sqrt(np.mean((p-g)**2))),
            "mae_mm": float(np.mean(np.abs(p-g))), "bias_mm": float(np.mean(p-g))}


def increment_metrics(gnss, insar, max_lag: int = 1) -> dict:
    dg, dp = np.diff(gnss), np.diff(insar)
    def evaluate(p, g, lag):
        metrics = pair_metrics(g, p)
        return {"r_delta": metrics["pearson_r"], "RMSE_delta": metrics["rmse_mm"],
                "lag_used": lag, "N_valid": metrics["n_pairs"]}
    best = evaluate(dp, dg, 0)
    for lag in range(1, max_lag + 1):
        if len(dp) - lag < 3:
            break
        for candidate in (evaluate(dp[lag:], dg[:-lag], lag), evaluate(dp[:-lag], dg[lag:], -lag)):
            if candidate["r_delta"] is not None and (best["r_delta"] is None or candidate["r_delta"] > best["r_delta"]):
                best = candidate
    best["N_valid_lagged"] = best["N_valid"]
    # Source code reports the unlagged increment count separately from best-lag diagnostics.
    best["N_valid"] = int(np.sum(np.isfinite(dg) & np.isfinite(dp)))
    return best


def rank_candidates(frame: pd.DataFrame, distance_weight: float) -> pd.DataFrame:
    ranked = frame.copy()
    def scale(values):
        span = values.max() - values.min()
        return (values-values.min()) / span if span > 0 else np.zeros(len(values))
    ranked["combined_score"] = ((1-distance_weight)*scale(ranked.trend_score)
                                 + distance_weight*scale(ranked.distance_km))
    ranked = ranked.sort_values(["combined_score", "PS_ID"], kind="stable").reset_index(drop=True)
    ranked.insert(0, "rank", np.arange(1, len(ranked)+1))
    return ranked


def daily_input_audit(path: Path, gnss: pd.DataFrame) -> dict:
    """Do not silently replace the authoritative, archived per-scene inputs."""
    daily = pd.read_csv(path, parse_dates=["date"]).set_index("date").U_rel_mm
    dates = pd.DatetimeIndex(gnss.date_insar)
    interpolated = daily.reindex(daily.index.union(dates)).sort_index().interpolate(
        method="time", limit_area="inside").reindex(dates).to_numpy(copy=True)
    interpolated -= interpolated[0]
    difference = interpolated - gnss.gnss_u_ref0.to_numpy()
    return {"compared_daily_file": str(path),
            "max_abs_difference_mm": float(np.max(np.abs(difference))) if np.isfinite(difference).all() else None,
            "identical_within_1e_8_mm": bool(np.isfinite(difference).all() and np.allclose(difference, 0, atol=1e-8)),
            "policy": "Use the original per-scene raw series from GNSS_PS_Windows; no regeneration or substitution"}


def validate_configuration(config: dict) -> None:
    if config["method"] != "supplementary_trend_top10":
        raise ValueError("Unsupported method")
    s = config["selection"]
    if not 0 <= s["coherence_min"] <= 1 or not 0 <= s["distance_weight"] <= 1:
        raise ValueError("Coherence and distance weight must lie in [0, 1]")
    if s["top_n"] < 1 or s["chunk_size"] < 1 or not 0 <= s["max_increment_lag"] <= 1:
        raise ValueError("Invalid TopN, chunk size or lag")
    names = [scene["name"] for scene in config["inputs"]["scenes"]]
    if not names or len(set(names)) != len(names) or any(not re.fullmatch(r"[A-Za-z0-9_]+", n) for n in names):
        raise ValueError("Scene names must be unique safe identifiers")


def run_scene(connection, scene: dict, config: dict, station: pd.Series, output: Path) -> tuple[dict, dict]:
    name, layer = scene["name"], scene["layer"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", layer):
        raise ValueError("Invalid layer name")
    columns = [r[1] for r in connection.execute(f'PRAGMA table_info("{layer}")')]
    required = {"fid", "Field1", "lon", "lat", "v", "inc", "coh"}
    if not required.issubset(columns):
        raise ValueError(f"Missing PS columns in {layer}: {required-set(columns)}")
    gnss_path = resolve_path(scene["gnss_series"])
    gnss = pd.read_csv(gnss_path, parse_dates=["date_insar"]).sort_values("date_insar")
    dates = pd.DatetimeIndex(gnss.date_insar)
    time_axis(dates)
    g = gnss.gnss_u_ref0.to_numpy(dtype=float)
    if not np.isfinite(g).all() or not np.isclose(g[0], 0):
        raise ValueError("GNSS input must be finite and ref0 aligned")
    date_map = {parse_date_column(c): c for c in columns if parse_date_column(c) is not None}
    if set(dates) != set(date_map):
        raise ValueError(f"GNSS/PS acquisition dates differ in {name}")
    time_columns = [date_map[d] for d in dates]
    k_g = float(slopes(g, dates)[0])
    selection = config["selection"]
    # As in the old script, the vectorized mean rejects any incomplete series.
    fields = ["fid", "Field1", "lon", "lat", "v", "inc", "coh"] + time_columns
    sql = 'SELECT ' + ', '.join(f'"{c}"' for c in fields) + f' FROM "{layer}" WHERE coh >= ? ORDER BY fid'
    pool = pd.DataFrame()
    counters = {"coherence_pass": 0, "finite_complete_pass": 0, "same_sign_pass": 0}
    for chunk in pd.read_sql_query(sql, connection, params=(selection["coherence_min"],), chunksize=selection["chunk_size"]):
        counters["coherence_pass"] += len(chunk)
        inc = chunk.inc.to_numpy(float)
        los = chunk[time_columns].to_numpy(float)
        valid = (np.isfinite(los).all(axis=1) & np.isfinite(inc) & (inc > 0) & (inc < np.pi/2)
                 & np.isfinite(chunk.lon) & np.isfinite(chunk.lat))
        counters["finite_complete_pass"] += int(valid.sum())
        rates = slopes(los / np.cos(inc)[:, None], dates)
        if selection["require_same_trend_sign"]:
            valid &= np.sign(rates) == (np.sign(k_g) if abs(k_g) > 1e-6 else 0)
        counters["same_sign_pass"] += int(valid.sum())
        subset = chunk.loc[valid].copy()
        subset["k_ps"] = rates[valid]
        subset["k_g"] = k_g
        subset["trend_score"] = abs(subset.k_ps-k_g) / (abs(k_g)+1e-9)
        pool = pd.concat([pool, subset], ignore_index=True).sort_values(
            ["trend_score", "Field1"], kind="stable").head(selection["top_n"])
        if counters['coherence_pass'] % 250000 == 0:
            print(f"{name}: processed {counters['coherence_pass']:,} coherent points", flush=True)
    if pool.empty:
        raise ValueError(f"No matching PS candidates in {name}")
    pool = pool.rename(columns={"Field1": "PS_ID", "v": "v_los"})
    pool["distance_km"] = haversine_km(pool.lon, pool.lat, float(station.lon), float(station.lat))
    pool["v_vertical_stored"] = pool.v_los / np.cos(pool.inc)
    maximum_lag = selection["max_increment_lag"] if selection["allow_increment_lag"] else 0
    # Convert selected original LOS series once; output remains compatible with Final_Data.
    pool.loc[:, time_columns] = pool[time_columns].to_numpy() / np.cos(pool.inc.to_numpy())[:, None]
    records = []
    for _, row in pool.iterrows():
        p = row[time_columns].to_numpy(float)
        p = p-p[0]
        records.append({**increment_metrics(g, p, maximum_lag),
                        **{"paired_"+k: v for k, v in pair_metrics(g, p).items()}})
    for key in records[0]:
        pool[key] = [r[key] for r in records]
    ranked = rank_candidates(pool, selection["distance_weight"])
    ranked["rate_residual_mm_yr"] = ranked.k_ps-ranked.k_g
    ranked["stored_rate_residual_mm_yr"] = ranked.v_vertical_stored-ranked.k_g
    ranked["gnss_lon"], ranked["gnss_lat"] = float(station.lon), float(station.lat)
    ranked.to_csv(output/f"{name}_Top10_Complete.csv", index=False)
    ranked.iloc[[0]].to_csv(output/f"{name}_Top1_Complete.csv", index=False)
    ranked.drop(columns=time_columns).to_csv(output/f"{name}_rate_validation.csv", index=False)
    gnss.to_csv(output/f"{name}_GNSS_Series.csv", index=False)
    pairs = []
    for _, row in ranked.iterrows():
        p = row[time_columns].to_numpy(float)
        p = p-p[0]
        pairs.append(pd.DataFrame({"scene": name, "rank": int(row['rank']), "PS_ID": int(row.PS_ID),
                                   "date": dates, "gnss_u_mm": g, "insar_u_mm": p,
                                   "residual_mm": p-g}))
    pd.concat(pairs).to_csv(output/f"{name}_paired_timeseries.csv", index=False)
    top = ranked.iloc[0]
    residuals = ranked.rate_residual_mm_yr.to_numpy()
    summary = {"scene": name, "n_epochs": len(dates), "n_selected_ps": len(ranked),
               "start_date": str(dates.min().date()), "end_date": str(dates.max().date()),
               "gnss_rate_mm_yr": k_g, "top1_PS_ID": int(top.PS_ID),
               "top1_ps_rate_mm_yr": float(top.k_ps), "top1_rate_residual_mm_yr": float(top.k_ps-k_g),
               "top1_stored_vertical_rate_mm_yr": float(top.v_vertical_stored),
               "top1_stored_rate_residual_mm_yr": float(top.v_vertical_stored-k_g),
               "top1_distance_km": float(top.distance_km),
               "top1_rmse_mm": float(top.paired_rmse_mm),
               "top1_pearson_r": None if pd.isna(top.paired_pearson_r) else float(top.paired_pearson_r),
               "rate_residual_mean_mm_yr": float(residuals.mean()),
               "rate_residual_rmse_mm_yr": float(np.sqrt(np.mean(residuals**2))),
               "rate_residual_std_mm_yr": float(residuals.std(ddof=1)) if len(residuals)>1 else None,
               "stored_rate_residual_mean_mm_yr": float(ranked.stored_rate_residual_mm_yr.mean()),
               "stored_rate_residual_rmse_mm_yr": float(np.sqrt(np.mean(ranked.stored_rate_residual_mm_yr**2))),
               "distance_min_km": float(ranked.distance_km.min()), "distance_max_km": float(ranked.distance_km.max())}
    legacy = output.parent/"legacy_reference"/f"{name}_Top10_Complete.csv"
    legacy_audit = None
    if legacy.exists():
        old = pd.read_csv(legacy)
        shared = sorted(set(old.PS_ID)&set(ranked.PS_ID))
        old_shared = old.set_index("PS_ID").loc[shared]
        new_shared = ranked.set_index("PS_ID").loc[shared]
        metric_columns = ["k_g", "k_ps", "trend_score", "distance_km", "combined_score",
                          "r_delta", "RMSE_delta", "lag_used", "N_valid"]
        legacy_audit = {"file": str(legacy), "top10_common_ids": len(set(old.PS_ID)&set(ranked.PS_ID)),
                        "archived_top1_id": int(old.PS_ID.iloc[0]), "current_top1_id": int(top.PS_ID),
                        "rank_order_identical": old.PS_ID.tolist() == ranked.PS_ID.tolist(),
                        "metric_max_abs_differences": {
                            c: float((new_shared[c]-old_shared[c]).abs().max()) for c in metric_columns
                        } if shared else {},
                        "policy": "Recompute with the supplied script and current source data; keep old results separately"}
    audit = {"gnss_input": fingerprint(gnss_path), "layer": layer,
             "source_ps_count": int(connection.execute(f'SELECT COUNT(*) FROM "{layer}"').fetchone()[0]),
             "filter_counts": counters, "selected_count": len(ranked),
             "incidence_unit": "radians", "displacement_unit": "mm", "rate_unit": "mm/year",
             "lag_scope": "increment diagnostics only; rates and paired displacement metrics use original dates",
             "gnss_daily_consistency": daily_input_audit(resolve_path(config["inputs"]["gnss_daily"]), gnss),
             "legacy_result_comparison": legacy_audit,
             "selected_series_sha256": hashlib.sha256(ranked[time_columns].to_numpy().tobytes()).hexdigest()}
    return summary, audit


def report_text(summaries: list[dict], audits: dict) -> str:
    text = ["# GNSS 形变速率匹配验证", "",
            "按 Supplementary_experiments/Script/05GNSS_PS_U_valid.py 的现有方法复算。",
            "默认输入为 GNSS_PS_Windows 中的 raw GNSS-U，不切换到去季节序列。PS 使用当前 data/TSX_PS/TSX_PS.gpkg 完整时序，按各点入射角由 LOS 转为垂直位移。",
            "", "相干性 ≥0.8；完整时序、与 GNSS 速率同号；全景按相对速率差筛 Top10；在 Top10 内将速率差及距离分别 min-max 归一化，用 0.7/0.3 综合排序。Top1 取综合排序第一。时序均首期归零；速率使用原脚本 year+(DOY−1)/365.25 时间轴的线性斜率。",
            "", "|景|期数|GNSS速率|Top1 PS速率|PS−GNSS|距离(km)|时序RMSE(mm)|", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in summaries:
        text.append(f"|{s['scene']}|{s['n_epochs']}|{s['gnss_rate_mm_yr']:.4f}|{s['top1_ps_rate_mm_yr']:.4f}|{s['top1_rate_residual_mm_yr']:+.4f}|{s['top1_distance_km']:.3f}|{s['top1_rmse_mm']:.3f}|")
    text += ["", "研究使用的原始垂直速率另外核验如下（同一组选定点）：", "",
             "|景|Top1原始v/cos(inc)|Top1原始速率−GNSS|Top10原始速率残差RMSE|", "|---|---:|---:|---:|"]
    for s in summaries:
        text.append(f"|{s['scene']}|{s['top1_stored_vertical_rate_mm_yr']:.4f}|{s['top1_stored_rate_residual_mm_yr']:+.4f}|{s['stored_rate_residual_rmse_mm_yr']:.4f}|")
    text += ["", "速率单位 mm/年；正值沿用原数据的垂直正方向。`k_ps` 是时序重新拟合的速率；`v_vertical_stored` 是现有风险模型使用的原始 v/cos(inc)，两者分别输出，避免混用。原始速率或风险结果不由本模块改写。",
             "", "## 适用范围和来源核验", "",
             "- 只有一个 GNSS 站；Top10 按速率接近程度筛选，因此残差描述筛选后的一致性，不是研究区无偏精度或10个独立 GNSS 站的验证。",
             "- 匹配点可远离 KMIN；距离完整输出，不将全景匹配点解释为站旁共址观测。",
             "- 站点经纬度只提供至0.01度；GNSS/InSAR速度参考框架与InSAR参考点未注明；垂直换算沿用论文忽略水平运动的假设。这些条件未核验前，结果不能证明全区绝对垂直速率精度。",
             "- 可选±1期滞后仅用于增量相关性诊断。散点、时序、位移RMSE及速率差均使用原日期、不作滞后或尺度拟合。",
             "- 原脚本的 MIN_VALID_RATIO=0.85、TOP_TREND_POOL 和 TREND_SCORE_MAX 等未参与实际筛选。本模块复现有效代码：缺一期的向量斜率无效，直接取全景最接近的10点。",
             "- 原 Save_data.py 另有按最小 trend_score 选Top1的路径；这里统一使用05主流程的 combined_score，防止图与表点位不一致。"]
    for name, a in audits.items():
        d = a['gnss_daily_consistency']
        text.append(f"- {name} 原始逐景GNSS输入与现存 GNSS_U_Full_TS.csv 插值对比最大差为 {d['max_abs_difference_mm']} mm；保留逐景输入作为本次复算依据。")
        old = a['legacy_result_comparison']
        if old:
            text.append(f"- {name} 与存档Top10重合 {old['top10_common_ids']}/10 点；存档Top1={old['archived_top1_id']}，复算Top1={old['current_top1_id']}。旧结果单独保留，不用于覆盖本次复算。")
    text += ["", "## 方法背景", "",
             "现有方法的复算说明见 project/code/Validation/README.md。GNSS有色噪声及参考框架会影响速度不确定度，参见 [Williams et al. (2004)](https://doi.org/10.1029/2003JB002741)；空间邻近配对及GNSS投影到LOS的研究示例见 [Hussain et al. (2018)](https://www.nature.com/articles/s41467-018-03739-2)。这些文献用于说明解释边界，不替代本项目已有选点算法。", ""]
    return "\n".join(text)


def run(config: dict, config_path: Path) -> Path:
    validate_configuration(config)
    output = resolve_path(config["outputs"]["results_dir"])
    output.mkdir(parents=True, exist_ok=True)
    station_path = resolve_path(config["inputs"]["station"])
    stations = pd.read_csv(station_path)
    if len(stations) != 1 or not np.isfinite(stations[["lon", "lat"]].to_numpy()).all():
        raise ValueError("This experiment requires one finite station location")
    ps_path = resolve_path(config["inputs"]["ps_gpkg"])
    before = fingerprint(ps_path, digest=False)
    summaries, audits = [], {}
    with sqlite3.connect(ps_path.as_uri()+"?mode=ro", uri=True) as connection:
        for scene in config["inputs"]["scenes"]:
            summary, audit = run_scene(connection, scene, config, stations.iloc[0], output)
            summaries.append(summary)
            audits[scene["name"]] = audit
    if before != fingerprint(ps_path, digest=False):
        raise RuntimeError("PS input changed during validation")
    pd.DataFrame(summaries).to_csv(output/"validation_summary.csv", index=False)
    (output/"validation_report.md").write_text(report_text(summaries, audits), encoding="utf-8")
    write_json(output/"run_manifest.json", {
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "method": config["method"], "config": config,
        "config_fingerprint": fingerprint(config_path), "code_fingerprint": fingerprint(Path(__file__)),
        "station_input": fingerprint(station_path), "ps_input": before,
        "station_count": 1, "input_ps_unchanged": True, "scenes": audits,
        "interpretation": "Trend-selected matches; descriptive consistency only, not independent regional accuracy"})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--plot", action="store_true", help="Generate the requested standalone TSX2 time-series figure")
    parser.add_argument("--all-plots", action="store_true", help="Also export the earlier three composite figures with --plot")
    parser.add_argument("--dpi", type=int, default=600, help="Final PNG resolution when --plot is supplied")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output = run(config, args.config)
    if args.plot:
        sys.path.insert(0, str(WORKSPACE_ROOT/"plot/06_insar_deformation/code/gnss"))
        from draw_validation import draw_all, draw_tsx2_timeseries
        draw_tsx2_timeseries(output, resolve_path(config["outputs"]["plot_dir"]),
                            resolve_path(config["outputs"]["final_figure_dir"]), args.dpi)
        if args.all_plots:
            draw_all(output, resolve_path(config["outputs"]["plot_dir"]),
                     resolve_path(config["outputs"]["final_figure_dir"]), args.dpi)
    print(f"GNSS validation saved: {output}")


if __name__ == "__main__":
    main()
