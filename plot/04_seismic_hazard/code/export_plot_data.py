#!/usr/bin/env python3
"""Export the numeric data for panels (b) and (c) of the current PGA figure."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import shutil
import sqlite3

import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[3]
OUTPUT = WORKSPACE / "plot/04_seismic_hazard/data"
ANALYSIS = WORKSPACE / "result/statistics/Hazard/analysis"
SCENARIOS = WORKSPACE / "result/statistics/Hazard/scs_pipeline/scenario_statistics.csv"
BUILDINGS = WORKSPACE / "result/hazard/scs_pipeline/06_building_hazard.gpkg"
BREAKS = WORKSPACE / "result/hazard/scs_pipeline/pga_class_breaks.csv"
FIGURE_METADATA = WORKSPACE / "plot/04_seismic_hazard/data/map_crop_manifest.json"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", float_precision="round_trip")


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.17g")


def main() -> None:
    metadata = json.loads(FIGURE_METADATA.read_text())
    reference = metadata["histogram_statistics"]
    expected_n = reference["valid_buildings"]
    scenarios = read_csv(SCENARIOS)
    contributions = read_csv(ANALYSIS / "fault_scenario_contributions.csv")
    assert scenarios.scenario_id.is_unique and contributions.Scenario_ID.is_unique
    original = scenarios.set_index("scenario_id").sort_index()
    derived = contributions.set_index("Scenario_ID").sort_index()
    assert original.index.equals(derived.index)
    for source, target in [("mean_pga_g", "Mean_Scenario_PGA_g"),
                           ("max_pga_g", "Maximum_Scenario_PGA_g"),
                           ("dominant_buildings", "Dominant_Building_Count")]:
        np.testing.assert_allclose(original[source], derived[target], rtol=1e-14, atol=1e-15)
    assert int(contributions.Dominant_Building_Count.sum()) == expected_n
    top = contributions.nlargest(min(10, len(contributions)), "Mean_Scenario_PGA_g")
    top = top.sort_values("Mean_Scenario_PGA_g").reset_index(drop=True)
    top.insert(0, "Plot_Y_Bottom_to_Top", np.arange(len(top)))
    top.insert(1, "Rank_Top_to_Bottom", np.arange(len(top), 0, -1))
    pie = contributions.groupby("Fault_Name_Display")["Dominant_Building_Count"].sum()
    pie = pie[pie.gt(0)].sort_values(ascending=False).rename("Building_Count").reset_index()
    pie["Share_pct"] = pie.Building_Count / expected_n * 100
    pie["Share_Label"] = pie.Share_pct.map(lambda value: f"{value:.1f}%")
    colors = {"Puduhe fault": "#B2182B",
              "Western branch of the Xiaojiang fault system (middle segment)": "#E05A70"}
    pie["Color_Hex"] = pie.Fault_Name_Display.map(colors).fillna("#F4A3A8")
    saved_pie = read_csv(ANALYSIS / "dominant_fault_building_counts.csv")
    assert pie.Fault_Name_Display.tolist() == saved_pie.Fault_Name_Display.tolist()
    np.testing.assert_array_equal(pie.Building_Count, saved_pie.Building_Count)
    np.testing.assert_allclose(pie.Share_pct, saved_pie.Share_pct, rtol=1e-14)
    assert int(pie.Building_Count.sum()) == expected_n

    with sqlite3.connect(f"{BUILDINGS.as_uri()}?mode=ro", uri=True) as connection:
        buildings = pd.read_sql_query(
            'SELECT "Build_ID", "PGA_Final_g", "PGA_Class" FROM "building_hazard" ORDER BY "fid"',
            connection)
    values = buildings.PGA_Final_g.to_numpy(float)
    assert buildings.Build_ID.is_unique and buildings.Build_ID.notna().all()
    assert len(values) == expected_n and np.isfinite(values).all()
    counts, edges = np.histogram(values, bins="fd")
    assert len(counts) == reference["bin_count"] and int(counts.sum()) == expected_n
    breaks = read_csv(BREAKS)
    thresholds = breaks.upper_break.to_numpy(float)[:-1]
    np.testing.assert_allclose(thresholds, reference["pga_class_thresholds_g"], rtol=1e-14)
    assigned = breaks.PGA_Class.to_numpy()[np.searchsorted(thresholds, values, side="left")]
    np.testing.assert_array_equal(assigned, buildings.PGA_Class.to_numpy())
    class_counts = pd.Series(assigned).value_counts().reindex(breaks.PGA_Class, fill_value=0)
    np.testing.assert_array_equal(class_counts.to_numpy(), breaks.Building_Count.to_numpy())
    breaks["Color_Hex"] = ["#FFF7BC", "#FEE391", "#FEC44F", "#FC4E2A", "#BD0026"]
    breaks["Lower_Inclusive"] = [True, False, False, False, False]
    breaks["Upper_Inclusive"] = True
    summary_values = [expected_n, float(values.mean()), float(np.median(values)),
                      float(values.min()), float(values.max()), float(values.std(ddof=1))]
    for actual, key in zip(summary_values[1:], ["mean_g", "median_g", "min_g", "max_g", "standard_deviation_g"]):
        assert np.isclose(actual, reference[key], rtol=1e-14, atol=1e-15), key
    summary = pd.DataFrame({
        "Statistic": ["Buildings", "Mean", "Median", "Minimum", "Maximum", "Std. dev."],
        "Value": summary_values, "Unit": ["buildings", "g", "g", "g", "g", "g"],
        "Figure_Label": [f"{expected_n:,}", *[f"{v:.4f} g" for v in summary_values[1:]]],
    })
    histogram = pd.DataFrame({
        "Bin_ID": np.arange(1, len(counts) + 1), "Lower_PGA_g": edges[:-1],
        "Upper_PGA_g": edges[1:], "Midpoint_PGA_g": (edges[:-1] + edges[1:]) / 2,
        "Building_Count": counts, "Percentage": counts / expected_n * 100,
        "Upper_Inclusive": np.arange(len(counts)) == len(counts) - 1,
    })
    panel_b = OUTPUT / "b_fault_contributions"
    panel_c = OUTPUT / "c_pga_histogram"
    panel_b.mkdir(parents=True, exist_ok=True)
    panel_c.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCENARIOS, panel_b / "scenario_statistics.csv")
    shutil.copy2(ANALYSIS / "fault_scenario_contributions.csv", panel_b / "fault_scenario_contributions.csv")
    save_csv(top, panel_b / "top10_fault_ranking.csv")
    save_csv(pie, panel_b / "dominant_fault_shares.csv")
    save_csv(buildings, panel_c / "building_pga.csv")
    save_csv(histogram, panel_c / "histogram_bins.csv")
    save_csv(summary, panel_c / "summary_statistics.csv")
    save_csv(breaks, panel_c / "pga_class_breaks.csv")
    # Check the exported numbers themselves, including float round-trip precision.
    np.testing.assert_array_equal(read_csv(panel_c / "building_pga.csv").PGA_Final_g, values)
    np.testing.assert_array_equal(read_csv(panel_c / "histogram_bins.csv").Building_Count, counts)
    outputs = {str(p.relative_to(OUTPUT)): {"sha256": digest(p), "rows": len(read_csv(p))}
               for p in sorted(OUTPUT.rglob("*.csv"))}
    sources = [SCENARIOS, BUILDINGS, BREAKS, FIGURE_METADATA,
               ANALYSIS / "fault_scenario_contributions.csv", ANALYSIS / "dominant_fault_building_counts.csv"]
    report = {
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "figure": metadata["composite"]["path"],
        "figure_sha256_recorded": metadata["composite"]["sha256"],
        "export_script": str(Path(__file__).resolve()),
        "sources": [{"path": str(p), "sha256": digest(p)} for p in sources], "files": outputs,
        "validation": {"scenario_count": len(contributions), "ranking_bars": len(top),
                       "pie_sectors": len(pie), "buildings": expected_n,
                       "histogram_bins": len(counts), "matches_saved_figure_statistics": True,
                       "class_counts_match_current_jenks": True, "export_float_round_trip_exact": True},
        "histogram_interval_rule": "[lower, upper), except the final bin includes its upper endpoint",
        "pga_class_interval_rule": "(lower, upper], except the first class includes the minimum",
        "standard_deviation_ddof": 1,
        "note": "Data snapshot for the current figure; original result datasets and renderer inputs are unchanged.",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUTPUT / "README.md").write_text("""# PGA拼图：图b、图c绘图数据

数据来自当前PGA abc拼图的原始绘图输入，CSV采用UTF-8 BOM编码，浮点数保留17位有效数字。此目录为绘图数据快照；原始计算数据仍保留在result，绘图代码仍保留在plot/shared。

## 图b：断层场景条形图与控制断层饼图

- `b_fault_contributions/scenario_statistics.csv`：59个场景的原始统计表。
- `b_fault_contributions/fault_scenario_contributions.csv`：完整场景贡献表，包含图中使用的英文显示名称。
- `b_fault_contributions/top10_fault_ranking.csv`：条形图实际使用的10个场景。Mean_Scenario_PGA_g为条形长度（g）；Plot_Y_Bottom_to_Top从0开始，对应图中由下至上的位置；Rank_Top_to_Bottom为由上至下的排名。
- `b_fault_contributions/dominant_fault_shares.csv`：饼图扇区的断层名称、控制建筑数量、比例、显示百分比及颜色。

条形图按平均场景PGA选取前10；饼图按断层显示名称合并控制建筑数量，仅包含数量大于0的断层，分母为57,228栋。场景平均PGA与控制建筑比例是不同统计量。

## 图c：PGA渐变直方图

- `c_pga_histogram/building_pga.csv`：57,228栋建筑的Build_ID、PGA_Final_g和PGA_Class，可重新计算直方图。
- `c_pga_histogram/histogram_bins.csv`：实际绘制的137个Freedman–Diaconis区间，包含左右边界、中点、建筑数、百分比和右端点是否包含。直方图区间左闭右开，最后一个区间包含最大值。
- `c_pga_histogram/summary_statistics.csv`：图上建筑数量、均值、中位数、最小值、最大值、样本标准差及显示文本；标准差ddof=1，PGA单位为g。
- `c_pga_histogram/pga_class_breaks.csv`：五级Jenks完整精度分级边界、建筑数、比例及色带颜色。分级区间右闭，首级同时包含最小值；图上阈值显示三位小数。

manifest.json记录源文件路径、SHA-256、导出文件行数、区间约定及核验结果。数据导出未修改计算结果和现有图表。

## 更新数据快照

在seismic_risk根目录运行：

```sh
python plot/04_seismic_hazard/code/export_plot_data.py
```

脚本按固定名称更新本目录的数据，并与当前拼图保存的统计信息核对；图表或模型结果更新后，先重建拼图，再更新此数据快照。
""")
    print(json.dumps({"folder": str(OUTPUT), **report["validation"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
