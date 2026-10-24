#!/usr/bin/env python3
"""Read-only source checks and separately labelled fault-nature proposals.

Run in the seismic Python environment. Geodesic trace orientation checks
spatial consistency only; it does not determine dip, rake or slip sense.
Published report descriptions and interpretive candidates remain separate.
No GIS layer or hazard input is written by this script.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json

import numpy as np
import pandas as pd
import pyogrio
from pyproj import Geod

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / '../data/faults/kunming_faults_literature.gpkg'
PROJECT = ROOT / '04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz'
OUT = ROOT / '../result/intermediate/fault_literature/two_fault_inference'
SOURCES = [
    dict(source_id='YAO2020', title='寻甸县先锋乡姚家村煤矿采矿权出让收益评估报告',
         publisher='云南省自然资源厅公开；北京中煤思维咨询有限公司编制',
         url='https://dnr.yn.gov.cn/uploadfile/dnr_old/manage/ewebeditor/uploadfile/20220913172110345.pdf',
         pdf_page=20, printed_page='11', role='published_project_report_geological_description',
         observation='梨花海、小里箐一带的北东向断裂被描述为东南倾、压扭性质，涉及20余km。',
         limitation='未报告明确左/右旋方向、倾角、擦痕侧伏角或第四纪运动分量；地质描述不等于现今运动实测。'),
    dict(source_id='SHAO2024', title='邵九小长地砂场生态修复项目环境影响报告表',
         publisher='云天化网站公开的项目报告',
         url='https://www.yyth.com.cn/file/ythgf/cn/file/20241218/1734503839167083125.pdf',
         pdf_page=120, printed_page='115', role='published_project_report_regional_fault_description',
         observation='区域马厂—县街断裂被列为正断层，走向约NE40°，晚更新世活动；报告长度约40.1km。',
         limitation='区域报告描述，不是本次取得的原始运动学测量；马厂/马场名称与当前约17.75km线段的对应需进一步核实。'),
    dict(source_id='YNDZ2024', title='云南省地震构造环境探查规划（2023—2035）',
         publisher='云南省抗震救灾指挥部办公室，云抗办〔2024〕12号',
         url='https://yndzj.gov.cn/yndzj/_300563/zcjd6/810070/2025052806281676077.pdf',
         pdf_page=18, printed_page='18', role='official_age_and_name_cross_check_only',
         observation='附件1列安宁市F44马厂—县街断裂，活动时代为晚更新世。',
         limitation='只支持名称、地域及时代核对，表中没有运动性质，不作为正断或左右旋证据；不将规划风险等级用于建筑风险。'),
]
PROPOSALS = {
    'KMF_0008': dict(name='梨花海断裂', reported_nature='压扭性；报告称倾向东南',
        proposed_summary='压扭性断层；可能具有逆断分量（待核）；左/右旋未定',
        inference_only='逆断分量是压扭背景下的候选解释，未获擦痕、断距或震源机制直接约束，不确定写为逆断层。',
        strike_slip_sense='undetermined', classification_support='中等：公开项目报告的区域描述',
        reverse_component_support='低：解释性推断', source_ids='YAO2020',
        scope_limit='报告约20余km，现有合并要素约49.74km；只作名称和区域的初步对应，不外推全线。'),
    'KMF_0009': dict(name='马场—县街断裂', reported_nature='马厂—县街区域断裂被报告列为正断层',
        proposed_summary='正断层（区域资料支持；与源线对应待核）；左/右旋未定',
        inference_only='正断性质有报告直接记述，不是仅凭线迹方向推出来的；走滑及斜滑分量仍未知。',
        strike_slip_sense='undetermined', classification_support='中等：区域报告描述及地域/时代交叉核对',
        reverse_component_support='不适用', source_ids='SHAO2024;YNDZ2024',
        scope_limit='报告约40.1km，现有要素约17.75km；马厂/马场别名、覆盖段落与最新运动性质仍需原图核对。'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = {str(p): sha(p) for p in [DATA, PROJECT]}
    source = pyogrio.read_dataframe(DATA, layer='faults_enriched')
    lonlat = source.to_crs(4326)
    geod = Geod(ellps='WGS84')
    records = []
    for uid, proposal in PROPOSALS.items():
        row = source[source.fault_uid == uid].iloc[0]
        geom = lonlat[lonlat.fault_uid == uid].geometry.iloc[0]
        parts = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
        angles, lengths = [], []
        for line in parts:
            c = np.asarray(line.coords)
            a, _, d = geod.inv(c[:-1, 0], c[:-1, 1], c[1:, 0], c[1:, 1])
            angles.extend(a)
            lengths.extend(d)
        angle, weights = np.radians(angles), np.asarray(lengths)
        # Axial direction is invariant under line reversal (modulo 180°).
        v = np.sum(weights * np.exp(2j * angle))
        direction = float(np.degrees(np.angle(v)) / 2 % 180)
        records.append(dict(fault_uid=uid, **proposal,
            source_Fea_Ch=None if pd.isna(row.Fea_Ch) else str(row.Fea_Ch),
            original_AGE=str(row.AGE), original_Length_km=float(row.Length_km),
            original_model_Mw=float(row.Mw), wgs84_bounds=list(geom.bounds),
            trace_axial_direction_deg=round(direction, 1),
            orientation_resultant_length=round(float(abs(v) / weights.sum()), 3),
            trace_part_count=len(parts), adoption_status='separate_candidate_not_written_to_GIS'))
    assert all(sha(p) == h for p, h in before.items()), 'Source/project changed during read-only analysis'
    timestamp = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    result = dict(analyzed_at=timestamp, source_hashes=before, sources=SOURCES, proposals=records,
        methodology='Sources reviewed online in full document context. Trace orientation is a geodesic length-weighted axial average; it does not infer slip sense.',
        source_pdfs_archived=False, verification='Source GPKG and canonical QGZ hashes unchanged.')
    (OUT / 'inference_evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    pd.DataFrame(records).to_csv(OUT / 'candidate_attributes.csv', index=False, encoding='utf-8-sig')
    lines = ['# 梨花海、马场—县街断层性质推断', '', f'分析时间：{timestamp}。推断候选单独存储，正式断层表和工程未更新。', '',
        '|断层|资料支持的性质|本次解释|左/右旋|', '|---|---|---|---|',
        '|梨花海|区域报告描述为压扭性、向东南倾|可能有逆断分量，尚不能正式确定为逆断层|未定|',
        '|马场—县街|区域马厂—县街被报告列为正断层|正断候选有资料支持；别名和具体段落需核实|未定|', '',
        '上述信息不支持给两条断层赋确定的左旋或右旋属性。现今运动方式、滑动速率及最新活动年代没有由这些资料得到新的实测约束。', '', '## 来源与页码', '']
    for s in SOURCES:
        lines += [f"- **{s['source_id']}**：[ {s['title']} ]({s['url']})，PDF第{s['pdf_page']}页（印刷第{s['printed_page']}页）。{s['publisher']}。{s['observation']} {s['limitation']}"]
    lines += ['', '这些文件是发布机构或项目方公开的原始报告文件，但其中区域构造部分沿用了既有地质资料，并非本次获得了原始断层运动学观测。报告记述与推测已分别保存。网页上传年份不作为报告编制年份。', '', '## 与当前数据的对应', '']
    for r in records:
        lines += [f"- **{r['name']} / {r['fault_uid']}**：现有线迹的长度加权轴向方向约N{r['trace_axial_direction_deg']}°E，分为{r['trace_part_count']}个线部件。{r['scope_limit']}"]
    lines += ['', '线迹总体NE向与报告区域描述相容，仅为平面方向一致性检查。该计算不能识别倾向、倾角、滑动方向、上/下盘或断层力学性质；轴向方向不是精确断层面产状。', '',
        '原数据两条Fea_Ch/Fea_En均为空，RefE均为UAFS:Kunming；本地既有6篇学术文献未直接约束这两条要素。原AGE、Mw、Length_km及几何保留。当前Mw是模型参数，不能反推运动性质。', '',
        '## 后续定性所需证据', '',
        '优先核对昆明城市活动断层探测报告及配套原图、先锋矿区原始地质报告；再查具体露头的擦痕/侧伏角、地层或阶地水系错断。与断层空间匹配的震源机制可提供补充，但单个附近地震不能直接确定整条断层。', '',
        '当前制图可继续使用普通断层线。候选性质如需展示，应明确标注资料解释/待核；两条线不使用确定的左旋、右旋箭头，梨花海也不直接画成已证实逆断层。', '',
        '复现：`/Users/bin/miniforge3/envs/seismic/bin/python plot/shared/qgis/scripts/infer_lihuahai_machang_properties.py`。输出为本目录的JSON、CSV和本文。在线原文已核查，保存链接与页码，未存完整PDF副本。']
    report = OUT / '性质推断.md'
    report.write_text('\n'.join(lines) + '\n')
    print(json.dumps({'report': str(report), 'proposals': 2, 'GIS_written': False, 'source_hashes_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
