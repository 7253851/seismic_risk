"""Prepare a local context boundary layer without changing Kunming's 14 districts.

Run with the seismic conda Python (geopandas/shapely). The pinned public source
must already be downloaded to data/intermediate/cartography/administrative_sources.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

import geopandas as gpd
from shapely.geometry import box, MultiPolygon
from shapely import make_valid

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / '../result/intermediate/cartography/administrative_sources/geoBoundaries-CHN-ADM2.geojson'
DEST = ROOT / '../data/administrative/kunming_surrounding_counties.gpkg'
METADATA = DEST.with_suffix('.source.json')
DOWNLOAD = 'https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/releaseData/gbOpen/CHN/ADM2/geoBoundaries-CHN-ADM2.geojson'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    source = gpd.read_file(RAW)
    assert len(source) == 2391 and source.crs.to_epsg() == 4326
    city_file = ROOT / '../data/administrative/kunming_city_boundary.gpkg'
    city = gpd.read_file(city_file, layer='city_boundary').to_crs(4543)
    # Generous selection envelope, beyond the final left map on every side.
    context = gpd.GeoSeries([box(101.4, 23.8, 104.5, 27.15)], crs=4326).to_crs(4543).iloc[0]
    counties = source.loc[source.intersects(box(101.4, 23.8, 104.5, 27.15))].to_crs(4543)
    counties = counties.loc[counties.intersects(context)].copy()
    original_count = len(counties)
    mask = city.geometry.union_all()
    clipped = []
    for geom in counties.geometry:
        geom = make_valid(geom).difference(mask)
        if geom.geom_type == 'Polygon':
            geom = MultiPolygon([geom])
        if geom.geom_type == 'GeometryCollection':
            geom = MultiPolygon([g for g in geom.geoms if g.geom_type == 'Polygon'])
        clipped.append(geom)
    counties.geometry = clipped
    # Ignore tiny mismatches between historical external data and the local city.
    counties = counties.loc[(~counties.is_empty) & (counties.area >= 500000)].copy()
    counties['source_year'] = 2017
    counties['source_set'] = 'geoBoundaries CHN ADM2 17275852 / 9469f09'
    assert counties.is_valid.all()
    if DEST.exists():
        DEST.unlink()
    counties.to_file(DEST, layer='surrounding_counties', driver='GPKG')
    overlap = counties.geometry.intersection(mask).area.sum()
    assert overlap < 0.01
    info = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'api': 'https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM2/',
        'download': DOWNLOAD, 'commit': '9469f09',
        'boundary_id': 'CHN-ADM2-17275852', 'represented_year': 2017,
        'administrative_level': 'County Level', 'source_crs': 'EPSG:4326',
        'source': 'National Administration of Surveying, Mapping and Geoinformation of China; Revolutionary GIS; geoBoundaries',
        'license': 'Open Data Commons Public Domain Dedication and License (PDDL) v1.0',
        'source_national_feature_count': len(source),
        'selected_before_city_subtraction': original_count,
        'output_feature_count': len(counties), 'output_crs': 'EPSG:4543',
        'selection_wgs84': [101.4, 23.8, 104.5, 27.15],
        'processing': 'Select surrounding counties, make valid, subtract the unchanged local Kunming city polygon, omit outside pieces smaller than 0.5 km². No feature labels.',
        'overlap_with_local_city_m2': float(overlap),
        'raw_file': str(RAW), 'raw_sha256': digest(RAW),
        'local_city_sha256': digest(city_file),
        'output_file': str(DEST), 'output_sha256': digest(DEST),
    }
    METADATA.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build()
