# -*- coding: utf-8 -*-
"""Replace current TSX footprints by rotated rectangles and sync active copies.

Use run_pyqgis.sh. Rectangles are constructed in the layout CRS, EPSG:4543,
then stored in the existing EPSG:4326 Shapefiles, preserving paths and fields.
The total footprint remains the geometric union, not a third bounding box.
Use --align-overlap to keep TSX1 fixed and align TSX2's upper/lower edges to it.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import shutil
import tempfile
import zipfile
import sys

from qgis.core import (
    QgsApplication, QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsGeometry, QgsFeature, QgsVectorFileWriter, QgsPointXY,
)

_APP = QgsApplication.instance()
if _APP is None:
    _APP = QgsApplication([], False)
    _APP.initQgis()

WORKSPACE = Path(__file__).resolve().parents[4]
QGIS_ROOT = WORKSPACE / 'plot'
TARGET_DIRS = [
    QGIS_ROOT / '../data/study_area',
]
NAMES = ['TSX1_Extent', 'TSX2_Extent', 'TSX_Total_Extent']
CORE = ['.shp', '.shx', '.dbf', '.prj', '.cpg']
GENERATED_SIDECARS = ['.qix', '.sbn', '.sbx', '.qpj', '.shp.xml', '.fix']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def corners(geometry):
    points = list(geometry.vertices())
    if points and points[0] == points[-1]:
        points.pop()
    return points


def rectangle_check(geometry):
    points = corners(geometry)
    if len(points) != 4:
        return {'corner_count': len(points), 'rectangle': False}
    angles, lengths = [], []
    for i, p in enumerate(points):
        prev, nxt = points[(i - 1) % 4], points[(i + 1) % 4]
        u, v = (prev.x() - p.x(), prev.y() - p.y()), (nxt.x() - p.x(), nxt.y() - p.y())
        lu, lv = math.hypot(*u), math.hypot(*v)
        cosine = max(-1, min(1, (u[0] * v[0] + u[1] * v[1]) / (lu * lv)))
        angles.append(math.degrees(math.acos(cosine)))
        lengths.append(lv)
    deviation = max(abs(a - 90) for a in angles)
    equal_error = max(abs(lengths[0] - lengths[2]), abs(lengths[1] - lengths[3]))
    return {'corner_count': 4, 'angles_degrees': angles, 'side_lengths_m': lengths,
            'max_angle_error_degrees': deviation, 'opposite_side_error_m': equal_error,
            'rectangle': deviation < 1e-7 and equal_error < 1e-5 and geometry.isGeosValid()}


def alignment_basis(reference):
    points = corners(reference)
    edges = [(points[i], points[(i + 1) % 4]) for i in range(4)]
    a, b = min(edges, key=lambda pair: math.hypot(pair[1].x() - pair[0].x(), pair[1].y() - pair[0].y()))
    length = math.hypot(b.x() - a.x(), b.y() - a.y())
    u = ((b.x() - a.x()) / length, (b.y() - a.y()) / length)
    if u[0] < 0:
        u = (-u[0], -u[1])
    v = (-u[1], u[0])
    origin = reference.centroid().asPoint()
    return origin, u, v


def axis_values(geometry, basis):
    origin, u, v = basis
    coords = [(p.x() - origin.x(), p.y() - origin.y()) for p in corners(geometry)]
    return [(x * u[0] + y * u[1], x * v[0] + y * v[1]) for x, y in coords]


def align_to_reference(reference, moving):
    """Preserve TSX2 width/cross-track centre; share TSX1 top and bottom lines."""
    basis = alignment_basis(reference)
    origin, u, v = basis
    ref_coords, moving_coords = axis_values(reference, basis), axis_values(moving, basis)
    centre_u = sum(x for x, _ in moving_coords) / 4
    moving_points = corners(moving)
    width = min(math.hypot(moving_points[(i + 1) % 4].x() - p.x(),
                           moving_points[(i + 1) % 4].y() - p.y()) for i, p in enumerate(moving_points))
    lo, hi = min(y for _, y in ref_coords), max(y for _, y in ref_coords)
    u0, u1 = centre_u - width / 2, centre_u + width / 2
    ring = [QgsPointXY(origin.x() + x * u[0] + y * v[0], origin.y() + x * u[1] + y * v[1])
            for x, y in [(u0, lo), (u0, hi), (u1, hi), (u1, lo), (u0, lo)]]
    return QgsGeometry.fromPolygonXY([ring])


def overlap_check(reference, moving):
    basis = alignment_basis(reference)
    a, b = axis_values(reference, basis), axis_values(moving, basis)
    overlap = min(max(x for x, _ in a), max(x for x, _ in b)) - max(min(x for x, _ in a), min(x for x, _ in b))
    edge_error = max(abs(min(y for _, y in a) - min(y for _, y in b)),
                     abs(max(y for _, y in a) - max(y for _, y in b)))
    return {'shared_edge_length_m_each': overlap, 'top_bottom_line_error_m': edge_error,
            'aligned': overlap > 0 and edge_error < 1e-5 and rectangle_check(moving)['rectangle']}


def write_stage(path, geometry, fields, attributes, crs, project):
    layer = QgsVectorLayer('MultiPolygon?crs=' + crs.authid(), path.stem, 'memory')
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()
    feature = QgsFeature(layer.fields())
    feature.setAttributes(attributes)
    output_geometry = QgsGeometry(geometry)
    output_geometry.convertToMultiType()
    feature.setGeometry(output_geometry)
    assert provider.addFeatures([feature])[0]
    layer.updateExtents()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'ESRI Shapefile'
    options.fileEncoding = 'UTF-8'
    result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), project.transformContext(), options)
    if result[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(str(result))


def main(align_overlap=False):
    project = QgsProject()
    metric = QgsCoordinateReferenceSystem('EPSG:4543')
    timestamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d_%H%M%S')
    record = QGIS_ROOT / 'history/changes' / (timestamp + ('_tsx_overlap_alignment' if align_overlap else '_tsx_rectangles'))
    record.mkdir(parents=True)
    originals, rects, native_rects, measurements = {}, {}, {}, {}
    for name in NAMES:
        layer = QgsVectorLayer(str(TARGET_DIRS[0] / (name + '.shp')), name, 'ogr')
        assert layer.isValid() and layer.featureCount() == 1
        feature = next(layer.getFeatures())
        old = QgsGeometry(feature.geometry())
        old.transform(QgsCoordinateTransform(layer.crs(), metric, project))
        originals[name] = {'geometry': old, 'crs': layer.crs(), 'fields': layer.fields(),
                           'attributes': feature.attributes()}
        if name == 'TSX_Total_Extent':
            continue
        if rectangle_check(old)['rectangle']:
            rectangle = QgsGeometry(old)
            _, _, angle, width, height = old.orientedMinimumBoundingBox()
        else:
            rectangle, _, angle, width, height = old.orientedMinimumBoundingBox()
        assert rectangle_check(rectangle)['rectangle']
        lost = old.difference(rectangle).area()
        assert lost < 1e-3, f'Old coverage was clipped: {name}, {lost} m2'
        rects[name] = rectangle
        measurements[name] = {
            'old_corner_count': len(corners(old)), 'old_area_km2': old.area() / 1e6,
            'new_area_km2': rectangle.area() / 1e6,
            'area_change_percent': (rectangle.area() / old.area() - 1) * 100,
            'old_coverage_lost_m2': lost, 'orientation_degrees': angle,
            'width_m': width, 'height_m': height, 'validation': rectangle_check(rectangle),
        }
    alignment = None
    if align_overlap:
        rects['TSX2_Extent'] = align_to_reference(rects['TSX1_Extent'], rects['TSX2_Extent'])
        moving, old = rects['TSX2_Extent'], originals['TSX2_Extent']['geometry']
        _, _, angle, width, height = moving.orientedMinimumBoundingBox()
        measurements['TSX2_Extent'].update({
            'new_area_km2': moving.area() / 1e6,
            'area_change_percent': (moving.area() / old.area() - 1) * 100,
            'old_coverage_lost_m2': old.difference(moving).area(),
            'orientation_degrees': angle, 'width_m': width, 'height_m': height,
            'validation': rectangle_check(moving),
        })
        alignment = overlap_check(rects['TSX1_Extent'], moving)
        assert alignment['aligned']
    rects['TSX_Total_Extent'] = QgsGeometry.unaryUnion([rects['TSX1_Extent'], rects['TSX2_Extent']])
    assert rects['TSX_Total_Extent'].isGeosValid()
    for name, geometry in rects.items():
        native = QgsGeometry(geometry)
        native.transform(QgsCoordinateTransform(metric, originals[name]['crs'], project))
        native_rects[name] = native

    manifest_file = QGIS_ROOT / 'shared/qgis/manifests/workspace_manifest.json'
    to_archive = []
    for directory in TARGET_DIRS:
        for name in NAMES:
            for file in directory.glob(name + '.*'):
                # Keep styles and source metadata; replace geometry, indices and stale locks.
                suffix = file.name[len(name):]
                if suffix in CORE + GENERATED_SIDECARS or suffix.endswith('.lock'):
                    to_archive.append(file)
    to_archive.append(manifest_file)
    backup = record / 'before.zip'
    with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in to_archive:
            archive.write(file, str(file.relative_to(WORKSPACE)))
    before_hashes = {str(f.relative_to(WORKSPACE)): sha(f) for f in to_archive}
    updated = []
    try:
        with tempfile.TemporaryDirectory(prefix='tsx_rectangles_') as temporary:
            stage = Path(temporary)
            for name in NAMES:
                data = originals[name]
                if align_overlap and name == 'TSX1_Extent':
                    # Keep the red reference frame byte-for-byte unchanged.
                    for extension in CORE:
                        shutil.copy2(TARGET_DIRS[0] / (name + extension), stage / (name + extension))
                else:
                    write_stage(stage / (name + '.shp'), native_rects[name], data['fields'], data['attributes'], data['crs'], project)
                check = QgsVectorLayer(str(stage / (name + '.shp')), name, 'ogr')
                assert check.isValid() and check.featureCount() == 1
                saved_feature = next(check.getFeatures())
                assert saved_feature.attributes() == data['attributes']
                saved = saved_feature.geometry()
                saved.transform(QgsCoordinateTransform(check.crs(), metric, project))
                if name != 'TSX_Total_Extent':
                    measurements[name]['saved_validation'] = rectangle_check(saved)
                    assert measurements[name]['saved_validation']['rectangle']
                assert saved.symDifference(rects[name]).area() < 1e-2
            for directory in TARGET_DIRS:
                for name in NAMES:
                    for extension in CORE:
                        src = stage / (name + extension)
                        assert src.exists()
                        dst = directory / src.name
                        swap = directory / ('.' + src.name + '.new')
                        shutil.copy2(src, swap)
                        swap.replace(dst)
                        updated.append(dst)
                    for file in directory.glob(name + '.*'):
                        suffix = file.name[len(name):]
                        if suffix in GENERATED_SIDECARS or suffix.endswith('.lock'):
                            file.unlink()
            manifest = json.loads(manifest_file.read_text())
            for layer in manifest['base_layers']:
                if layer['key'] in ['tsx1', 'tsx2', 'study_extent']:
                    layer['note'] = ('2026-10-14: TSX1 fixed; TSX2 aligned to TSX1 orientation and upper/lower edges. '
                                     if align_overlap else '2026-10-14: minimum rotated rectangles constructed in EPSG:4543. ') + \
                                    'Stored in original EPSG:4326 with unchanged fields; total is their geometric union.'
            manifest['tsx_rectangle_update'] = {
                'updated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                'method': 'TSX2 aligned to TSX1 shared upper/lower edges' if align_overlap else 'minimum rotated bounding rectangle in EPSG:4543',
                'storage_crs': 'EPSG:4326',
                'report': str((record / 'verification.json').relative_to(QGIS_ROOT)),
            }
            manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')

        # Validate every active copy and total union in the map projection.
        copies = []
        for directory in TARGET_DIRS:
            saved = {}
            for name in NAMES:
                layer = QgsVectorLayer(str(directory / (name + '.shp')), name, 'ogr')
                assert layer.isValid() and layer.featureCount() == 1
                geometry = next(layer.getFeatures()).geometry()
                geometry.transform(QgsCoordinateTransform(layer.crs(), metric, project))
                saved[name] = geometry
                if name != 'TSX_Total_Extent':
                    assert rectangle_check(geometry)['rectangle']
                for extension in CORE:
                    assert sha(directory / (name + extension)) == sha(TARGET_DIRS[0] / (name + extension))
            delta = saved['TSX_Total_Extent'].symDifference(QgsGeometry.unaryUnion([saved[n] for n in NAMES[:2]])).area()
            assert delta < 1e-2
            if align_overlap:
                assert overlap_check(saved['TSX1_Extent'], saved['TSX2_Extent'])['aligned']
            copies.append({'directory': str(directory.relative_to(WORKSPACE)), 'total_union_error_m2': delta,
                           'all_three_layers_valid': True, 'all_copies_identical': True})
    except Exception:
        with zipfile.ZipFile(backup) as archive:
            for member in archive.namelist():
                destination = WORKSPACE / member
                destination.write_bytes(archive.read(member))
        raise

    report = {
        'updated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'method': 'TSX1 fixed; TSX2 upper/lower edges aligned in EPSG:4543' if align_overlap else 'minimum rotated bounding rectangle of each old footprint in EPSG:4543',
        'edge_alignment': alignment,
        'storage_crs_unchanged': 'EPSG:4326', 'fields_unchanged': True,
        'measurements': measurements, 'copies': copies,
        'total_area_km2': rects['TSX_Total_Extent'].area() / 1e6,
        'before_sha256': before_hashes,
        'after_sha256': {str(f.relative_to(WORKSPACE)): sha(f) for f in updated},
        'originals_archived': str(backup), 'active_old_geometry_removed': True,
    }
    (record / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (record / 'change_record.md').write_text(
        '# TSX 范围修正为矩形\n\n' +
        ('按用户截图要求，固定红色 TSX1，将黄色 TSX2 的方向及上、下边与 TSX1 对齐，使其边线部分重合；'
         '保持 TSX2 宽度及横向中心位置，纵向范围改用 TSX1 的上下边界。'
         if align_overlap else '按用户要求，以 EPSG:4543 构建两个最小旋转外接矩形，完整包住旧范围。') +
        '写回原 EPSG:4326 Shapefile，保持文件路径、ID、Name 不变。'
        'QGIS 基础数据、原计算项目 Data 及 Result/Data 中的三组当前文件全部同步替换，'
        '总范围为两个新矩形的并集。旧几何只保留在 before.zip 历史备份中。\n\n'
        '这些矩形由已有 PS 范围拟合，并非重新取得的卫星场景四角元数据。'
        '已有建筑及 H/V/E/R 结果未重新计算。几何、直角、对边等长、并集及副本一致性检查见 verification.json。\n',
        encoding='utf-8',
    )
    print(json.dumps({'record': str(record), 'measurements': measurements, 'copies': copies,
                      'total_area_km2': report['total_area_km2']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main(align_overlap='--align-overlap' in sys.argv[1:])
