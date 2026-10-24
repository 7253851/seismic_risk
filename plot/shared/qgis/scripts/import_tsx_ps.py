#!/usr/bin/env python3
"""Copy both complete TSX PS point layers to data/TSX_PS/TSX_PS.gpkg.

Run with shared/qgis/scripts/run_pyqgis.sh. GDAL copies features directly and
NumPy Arrow streams compare every original attribute, FID and WKB in bounded
batches. No reprojection, merging, clipping or filtering is performed.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import shutil
import sqlite3
import argparse

import numpy as np
from osgeo import gdal, ogr

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
SOURCE = None
DATA_DIR = ROOT / '../data/TSX_PS'
OUTPUT = DATA_DIR / 'TSX_PS.gpkg'
STAGE = OUTPUT.with_name('.TSX_PS_stage.gpkg')
PROJECT = ROOT / '04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz'
LAYERS = [('tsx1_point', 'TSX1_PS'), ('tsx2_point', 'TSX2_PS')]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def snapshot_gdb():
    return {p.name: {'size': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns}
            for p in sorted(SOURCE.iterdir()) if p.is_file() and not p.name.endswith('.lock')}


def field_schema(layer):
    definition = layer.GetLayerDefn()
    result = []
    for i in range(definition.GetFieldCount()):
        field = definition.GetFieldDefn(i)
        result.append({'name': field.GetName(), 'type': field.GetTypeName(),
                       'subtype': int(field.GetSubType())})
    return result


def progress(label):
    state = {'percent': -10}
    def update(fraction, message, user):
        percent = int(fraction * 100)
        if percent >= state['percent'] + 10 or percent == 100 and state['percent'] != 100:
            state['percent'] = percent
            print(f'{label}: copy {percent}%', flush=True)
        return 1
    return update


def compare_layers(src, dst, old_name, new_name):
    a = src.GetLayerByName(old_name)
    b = dst.GetLayerByName(new_name)
    assert a.GetFeatureCount() == b.GetFeatureCount()
    schema = field_schema(a)
    assert schema == field_schema(b), 'Field names/types changed'
    assert a.GetSpatialRef().IsSame(b.GetSpatialRef())
    assert a.GetGeomType() == b.GetGeomType() == ogr.wkbPoint
    names = [f['name'] for f in schema]
    sa = a.GetArrowStreamAsNumPy(options=['MAX_FEATURES_IN_BATCH=65536', 'INCLUDE_FID=YES'])
    sb = b.GetArrowStreamAsNumPy(options=['MAX_FEATURES_IN_BATCH=65536', 'INCLUDE_FID=YES'])
    ia, ib = iter(sa), iter(sb)
    ba, bb = next(ia, None), next(ib, None)
    oa = ob = count = 0
    signature = hashlib.sha256()
    v_min, v_max = float('inf'), float('-inf')
    v_valid = 0
    last_progress = -1
    total = a.GetFeatureCount()
    fid_a, fid_b = a.GetFIDColumn(), b.GetFIDColumn()
    while ba is not None and bb is not None:
        ga = next(k for k in ba if k not in names and k != fid_a)
        gb = next(k for k in bb if k not in names and k != fid_b)
        n = min(len(ba[fid_a]) - oa, len(bb[fid_b]) - ob)
        pairs = [(name, name) for name in names] + [(fid_a, fid_b), (ga, gb)]
        for ka, kb in pairs:
            av = ba[ka][oa:oa+n]
            bv = bb[kb][ob:ob+n]
            am, bm = np.ma.getmaskarray(av), np.ma.getmaskarray(bv)
            assert np.array_equal(am, bm), f'{new_name}:{ka} null masks changed at {count}'
            ad, bd = np.asarray(av)[~am], np.asarray(bv)[~bm]
            assert ad.dtype == bd.dtype, f'{new_name}:{ka} array type changed'
            if ad.dtype.kind in 'fc':
                equal = np.array_equal(ad, bd, equal_nan=True)
            else:
                equal = np.array_equal(ad, bd)
            assert equal, f'{new_name}:{ka} value or geometry changed at {count}'
            signature.update(am.tobytes())
            if ad.dtype.kind == 'O':
                for value in ad:
                    signature.update(bytes(value))
            else:
                signature.update(ad.tobytes())
            if ka == 'v':
                valid = ad[np.isfinite(ad)]
                if valid.size:
                    v_min = min(v_min, float(valid.min()))
                    v_max = max(v_max, float(valid.max()))
                    v_valid += int(valid.size)
        oa += n
        ob += n
        count += n
        percent = int(100 * count / total)
        if percent // 20 != last_progress:
            print(f'{new_name}: verify {count:,}/{total:,} ({percent}%)', flush=True)
            last_progress = percent // 20
        if oa == len(ba[fid_a]):
            ba = next(ia, None)
            oa = 0
        if ob == len(bb[fid_b]):
            bb = next(ib, None)
            ob = 0
    assert ba is None and bb is None and count == total
    # Release stream before querying layer state again.
    ia = ib = sa = sb = None
    times = [n for n in names if n.startswith('F20')]
    return {'source_layer': old_name, 'output_layer': new_name,
            'features': count, 'crs': 'EPSG:4326', 'geometry_type': 'Point',
            'attribute_count': len(names), 'schema': schema,
            'time_field_count': len(times), 'first_time_field': times[0],
            'last_time_field': times[-1], 'all_attributes_exact': True,
            'all_geometry_wkb_exact': True, 'all_fids_exact': True,
            'comparison_stream_sha256': signature.hexdigest(),
            'v_finite_count': v_valid, 'v_min_source_units': v_min,
            'v_max_source_units': v_max}


def main():
    global SOURCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Original FileGDB containing tsx1_point and tsx2_point')
    SOURCE = parser.parse_args().source.resolve()
    gdal.UseExceptions()
    ogr.UseExceptions()
    assert SOURCE.is_dir()
    assert not OUTPUT.exists(), 'TSX_PS.gpkg already exists; no overwrite performed'
    assert not STAGE.exists(), 'An unfinished staging file exists; inspect it before retrying'
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    assert shutil.disk_usage(OUTPUT.parent).free > 12 * 1024 ** 3
    stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d_%H%M%S')
    history = ROOT / 'history/changes' / (stamp + '_import_tsx_ps')
    history.mkdir(parents=True)
    source_snapshot = snapshot_gdb()
    project_hash = sha(PROJECT)
    write_json(history / 'source_file_snapshot.json', source_snapshot)
    shutil.copy2(Path(__file__), history / Path(__file__).name)
    for i, (old_name, new_name) in enumerate(LAYERS):
        options = gdal.VectorTranslateOptions(
            format='GPKG', accessMode=None if i == 0 else 'update',
            layers=[old_name], layerName=new_name, preserveFID=True,
            transactionSize=100000,
            datasetCreationOptions=['VERSION=1.3'] if i == 0 else None,
            layerCreationOptions=['FID=fid', 'GEOMETRY_NAME=geom', 'SPATIAL_INDEX=YES'],
            callback=progress(new_name))
        destination = gdal.VectorTranslate(str(STAGE), str(SOURCE), options=options)
        assert destination is not None
        destination.FlushCache()
        destination = None
        print(f'{new_name}: layer and spatial index written', flush=True)
    src = gdal.OpenEx(str(SOURCE), gdal.OF_VECTOR | gdal.OF_READONLY)
    dst = gdal.OpenEx(str(STAGE), gdal.OF_VECTOR | gdal.OF_READONLY)
    checks = [compare_layers(src, dst, a, b) for a, b in LAYERS]
    src = dst = None
    with sqlite3.connect(STAGE.as_uri() + '?mode=ro', uri=True) as db:
        integrity = db.execute('PRAGMA quick_check').fetchone()[0]
        assert integrity == 'ok'
        for check in checks:
            name = check['output_layer']
            indexed = db.execute(f'SELECT count(*) FROM "rtree_{name}_geom"').fetchone()[0]
            assert indexed == check['features']
            check['spatial_index_features'] = indexed
    assert source_snapshot == snapshot_gdb(), 'Source GDB changed during copying'
    assert not OUTPUT.exists()
    os.replace(STAGE, OUTPUT)
    print('Hashing completed GeoPackage...', flush=True)
    manifest = {'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                'source_gdb': str(SOURCE.relative_to(WORKSPACE)),
                'output': str(OUTPUT.resolve().relative_to(WORKSPACE)), 'output_bytes': OUTPUT.stat().st_size,
                'output_sha256': sha(OUTPUT), 'history': str(history.relative_to(ROOT)),
                'layers': checks, 'total_records': sum(c['features'] for c in checks),
                'source_gdb_file_snapshot_unchanged': True, 'sqlite_quick_check': integrity,
                'canonical_project_written': False,
                'canonical_project_sha256_after': sha(PROJECT),
                'canonical_project_unchanged_during_import': sha(PROJECT) == project_hash,
                'processing': 'Direct copy. No clipping, filtering, resampling, reprojection or time-series merging.',
                'unit_note': 'v and all time-series values retain source units and signs; these are not reinterpreted here.'}
    write_json(history / 'verification.json', manifest)
    write_json(ROOT / 'shared/qgis/manifests/tsx_ps_manifest.json', manifest)
    report = DATA_DIR / 'README.md'
    report.write_text(f'''# TSX_PS 原始PS形变数据

导入时间：{manifest['created_at']}。

数据文件：`TSX_PS.gpkg`，来源为ArcGIS Pro `Study_Area/Study_Area.gdb`。

|图层|点记录数|业务属性字段数（不含FID）|时序字段数|时段|
|---|---:|---:|---:|---|
|TSX1_PS|3,376,339|43|36|2017-01-10—2019-06-09|
|TSX2_PS|2,673,912|77|70|2017-01-05—2019-08-31|

合计6,050,251条记录；两景重叠区可能有不同观测点，合计数不表示去重后的空间点数。两景分别存储完整时序。

两层均为Point、EPSG:4326，保留原FID和全部属性。`Field1`为原导出序号，`lon/lat`为坐标，`h`为高程字段，`v`为形变速率字段，`inc`为入射角字段，`coh`为相干性，`F日期`字段为逐期位移。单位、角度单位、参考点和正负方向按原InSAR处理说明解释，本次只保留源值。

这些是地表PS-InSAR观测，不直接作为断层滑动速率或左右旋方向。没有将派生的`v_vertical`混入原始点层。

## 使用

在QGIS浏览器展开本目录的`TSX_PS.gpkg`，分别添加`TSX1_PS`或`TSX2_PS`。文件包含空间索引。大量点宜按研究范围/比例尺显示；本次完成数据归档，未修改现有工程或布局。

## 校验与复现

已逐批比较所有记录的全部属性、空值、FID和几何WKB，与原GDB一致；坐标系和字段类型一致。两层空间索引记录数与点数一致，SQLite quick_check通过。源GDB文件清单、大小和修改时间未变。

脚本：`plot/shared/qgis/scripts/import_tsx_ps.py`，用`plot/shared/qgis/scripts/run_pyqgis.sh`运行。脚本采用有界批次校验，现有目标文件存在时停止，不覆盖。

导入清单：`plot/shared/qgis/manifests/tsx_ps_manifest.json`。
历史目录：`QGIS/{manifest['history']}`。
''')
    (history / 'change_record.md').write_text('# 导入TSX_PS\n\n按用户要求将两景完整原始PS点复制至data/TSX_PS/TSX_PS.gpkg。保留全部6,050,251条记录及不同日期的时序字段。原GDB、原PS CSV、现有工程及H/V/E/R均未由此脚本写入。全量属性、空值、FID与WKB逐批校验通过；空间索引完整。详情见verification.json。\n')
    shutil.copy2(report, history / report.name)
    print(json.dumps({'output': str(OUTPUT), 'total_records': manifest['total_records'],
                      'bytes': manifest['output_bytes'], 'history': str(history),
                      'all_fields_FIDs_and_WKB_verified': True}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
