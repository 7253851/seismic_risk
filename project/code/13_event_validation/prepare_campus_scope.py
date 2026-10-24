"""Use digitized YUFE and OSM YNAU campus polygons as the active validation scope."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'result/validation/13_event_validation/results'
TARGET = OUT / 'campus_boundary_scope.gpkg'
SOURCES = {
    'south': ROOT / 'data/validation/campuses/yufe_south/yufe_longquan_campus_boundary.shp',
    'north': ROOT / 'data/validation/campuses/yufe_north/yufe_longquan_north_campus_boundary.shp',
    'cases': ROOT / 'data/validation/cases/case_candidates.gpkg',
    'inventory': ROOT / 'result/vulnerability/scs_paper_method/01_building_vulnerability_metrics.gpkg',
    'risk': ROOT / 'result/risk/scs_paper_method/building_risk.gpkg',
}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    assert not TARGET.exists(), 'Campus scope already exists; choose a new version before rebuilding.'
    protected = dict(SOURCES)
    for key in ('south', 'north'):
        for ext in ('.shx', '.dbf', '.prj', '.cpg'):
            p = SOURCES[key].with_suffix(ext)
            if p.exists():
                protected[key + ext] = p
    fingerprints = {str(p): sha(p) for p in protected.values()}
    original_areas = gpd.read_file(SOURCES['cases'], layer='selection_areas').to_crs(32648)
    originals = original_areas.set_index('location_id')
    osm = gpd.read_file(SOURCES['cases'], layer='site_boundaries').to_crs(32648)
    rows = []
    for loc, key in [('CF01', 'south'), ('CF02', 'north')]:
        row = originals.loc[loc].drop(labels='geometry').to_dict()
        row.update(location_id=loc, selection_mode='boundary', buffer_radius_m=None,
                   boundary_source=str(SOURCES[key].relative_to(ROOT)),
                   boundary_authority='User screenshot digitization; reference campus boundary',
                   geometry=gpd.read_file(SOURCES[key]).to_crs(32648).geometry.union_all())
        rows.append(row)
    for _, f in osm.loc[osm.case_id.eq('NY')].iterrows():
        row = originals.loc[f.location_id].drop(labels='geometry').to_dict()
        row.update(location_id=f.location_id, selection_mode='boundary', buffer_radius_m=None,
                   boundary_source=f.boundary_source, boundary_authority=f.boundary_status, geometry=f.geometry)
        rows.append(row)
    areas = gpd.GeoDataFrame(rows, geometry='geometry', crs=32648)
    assert len(areas) == 4 and areas.geometry.is_valid.all()
    assert areas.selection_mode.eq('boundary').all()
    areas.to_file(TARGET, layer='selection_areas', driver='GPKG')
    gpd.read_file(SOURCES['cases'], layer='site_points').to_file(TARGET, layer='site_points', driver='GPKG')
    gpd.read_file(SOURCES['cases'], layer='epicenter').to_file(TARGET, layer='epicenter', driver='GPKG')
    # Existing OSM park polygon remains a reference only, outside the active statistical scope.
    gpd.read_file(SOURCES['cases'], layer='site_boundaries').to_file(TARGET, layer='site_boundaries', driver='GPKG')
    inventory = gpd.read_file(SOURCES['inventory'], layer='building_vulnerability_metrics').to_crs(32648)
    risk = gpd.read_file(SOURCES['risk'], layer='building_risk_scs')
    points = inventory.geometry.representative_point()
    records, counts = [], []
    for _, a in areas.iterrows():
        indices = points.sindex.query(a.geometry, predicate='intersects')
        frame = inventory.iloc[indices][['Build_ID', 'geometry']].copy()
        frame['case_id'], frame['case_name'] = a.case_id, a.case_name
        frame['location_id'], frame['location_name'] = a.location_id, a.location_name
        frame['damage_status'] = 'unknown'
        frame['case_damage_presence'] = 'assumed_present'
        frame['selection_method'] = 'campus_boundary_representative_point'
        records.append(frame)
        counts.append({'location_id': a.location_id, 'case_id': a.case_id, 'name': a.location_name,
                       'area_ha': a.geometry.area / 10000, 'candidate_n': len(frame),
                       'risk_n': int(frame.Build_ID.isin(risk.Build_ID).sum()), 'boundary_source': a.boundary_source})
    candidates = gpd.GeoDataFrame(pd.concat(records, ignore_index=True), geometry='geometry', crs=32648)
    assert not candidates.Build_ID.duplicated().any(), 'Overlapping campus scopes require an explicit association rule.'
    candidates = candidates.merge(pd.DataFrame(risk.drop(columns='geometry')), on='Build_ID', how='left', validate='one_to_one')
    candidates['has_latest_risk'] = candidates.Risk_Final.notna().astype(int)
    candidates.to_file(TARGET, layer='candidate_buildings_latest', driver='GPKG')
    pd.DataFrame(candidates.drop(columns='geometry')).to_csv(OUT / 'campus_boundary_candidates.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(counts).to_csv(OUT / 'campus_boundary_counts.csv', index=False, encoding='utf-8-sig')
    assert all(sha(Path(p)) == h for p, h in fingerprints.items())
    report = {'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'scope': str(TARGET),
              'selection': 'representative point intersects campus boundary', 'active_boundary_n': 4, 'buffer_n': 0,
              'candidate_n': len(candidates), 'risk_n': int(candidates.has_latest_risk.sum()), 'locations': counts,
              'excluded_cases': [{'case_id': 'JN', 'reason': 'Complete boundary unavailable; POI and partial reference polygon only; no statistical scope assigned.'}],
              'source_data_unchanged': True, 'source_sha256': fingerprints}
    (OUT / 'campus_boundary_scope_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['active_boundary_n', 'buffer_n', 'candidate_n', 'risk_n']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
