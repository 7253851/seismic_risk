# 输入数据需求

数据不随仓库发布。运行前在仓库根目录建立 `data/`，按下表放置。代码中的路径以仓库根目录为基准，具体文件名见 `project/code/paths.py` 和各模块的 `config.json`。

| 目录 | 内容 | 用途 |
| --- | --- | --- |
| `data/buildings/` | 研究区建筑轮廓矢量，含唯一建筑编号；建筑高度底图 | 危险性、脆弱性、暴露度、风险的计算单元 |
| `data/TSX_PS/` | TerraSAR-X 升/降轨 PS 点（含年均速率和时序字段）及垂直形变速率栅格 | 建筑形变指标、IBSI、InSAR 讨论实验 |
| `data/GNSS/` | 研究区内 GNSS 连续站日解（N/E/U）及站点位置 | InSAR 形变验证 |
| `data/faults/` | 区域活动断层矢量及文献属性 | 地震危险性情景、制图 |
| `data/earthquakes/` | 历史地震目录 | 危险性与研究区制图 |
| `data/vs30/` | VS30 场地条件栅格 | 场地放大 |
| `data/dem/` | 数字高程模型 | 地形、山体阴影 |
| `data/population/` | 人口格网栅格 | 暴露度 |
| `data/administrative/` | 市、区县、街道行政边界 | 统计单元与制图 |
| `data/china_administrative_boundaries_gs_2024_0650/` | 带审图号的国家标准行政边界 | 研究区制图 |
| `data/cartography/` | 道路、水系等底图要素 | 制图 |
| `data/study_area/` | 研究区及 InSAR 覆盖范围、建成区 | 范围裁剪 |
| `data/water/` | 湖泊岸线参考 | 制图 |
| `data/validation/` | 地震受损案例点、校园边界、候选建筑 | 地震案例验证 |

模型中间数据和结果写入本地 `result/`，同样不纳入版本控制。
