# seismic_risk

昆明建筑尺度地震风险评估的计算与制图代码。仓库包含代码、QGIS 工程/样式、最终图件的压缩 PNG 和建筑级结果属性表（`data_release/`）；输入数据和中间数据不公开，需按 [数据需求](DATA_zh.md) 自行准备后放在 `data/` 下。

## 目录

| 目录 | 内容 |
| --- | --- |
| `project/code/` | 数值模型：`Hazard/` 地震危险性、`Vulnerability/` 脆弱性与 IBSI、`Exposure/` 暴露度、`Risk/` 风险集成、`Validation/` GNSS 验证、`12_insar_contribution/` InSAR 增量实验、`13_event_validation/` 地震案例验证 |
| `project/experiments/` | 按章节顺序指向上述代码的符号链接入口；`experiment_index.json` 为机器索引 |
| `plot/NN_*/` | 每幅图的绘图代码（`code/`）、QGIS 工程与版式（`qgis/`、`layout/`） |
| `plot/shared/` | 跨图分析函数、PyQGIS 脚本与运行器、图层样式 |
| `figures/` | 最终图件的压缩 PNG（图 1–13、补充图 S1–S2） |
| `docs/DATA_zh.md` | 运行所需的输入数据说明 |

## 运行

1. 按 `docs/DATA_zh.md` 准备 `data/` 目录。
2. 模型计算（危险性 → 脆弱性 → 暴露度 → 风险）：

   ```bash
   python project/code/Hazard/pipeline.py
   python project/code/Vulnerability/pipeline.py
   python project/code/Exposure/pipeline.py
   python project/code/Risk/pipeline.py
   ```

   统一路径定义在 `project/code/paths.py`，各模块参数在其 `config.json`，结果写入本地 `result/`。
3. 验证与讨论实验：`project/code/Validation/`、`project/code/12_insar_contribution/run_static_baseline.py`、`project/code/13_event_validation/`。
4. 制图：运行 `plot/NN_*/code/` 下的脚本；地图类图件用 QGIS 打开 `plot/NN_*/qgis/` 中的工程。`plot/figure_index.json` 记录每幅图的入口脚本。

## 图件

| 图 | 内容 |
| --- | --- |
| 1 | 研究区与数据 |
| 2 | 概念框架 |
| 3 | 技术流程 |
| 4 | 建筑危险性分布与统计 |
| 5 | 距离与场地响应 |
| 6 | 形变观测与 GNSS |
| 7 | 建筑形变指标与 IBSI |
| 8 | 脆弱性与暴露度空间分布 |
| 9 | 四指标等级构成 |
| 10 | 双剖面风险 |
| 11 | 街道风险与行政区构成 |
| 12 | InSAR 状态信息的增量作用 |
| 13 | 地震受损建筑案例验证 |
| S1–S2 | 补充图 |
