"""Read-only geometry extraction; run with the seismic environment for geospatial libraries.

Road-derived faces are exploratory neighborhood proxies, not cadastral blocks.
"""
from pathlib import Path
import json
import geopandas as gpd
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'result/intermediate/12_insar_contribution'


def main():
    buildings = gpd.read_file(ROOT / 'result/risk/scs_paper_method/building_risk.gpkg',
                              layer='building_risk_scs')[['Build_ID', 'geometry']].to_crs(32648)
    centroids = buildings.copy()
    centroids.geometry = buildings.geometry.centroid
    ll = centroids.to_crs(4326)
    centroids['centroid_x_utm48n_m'] = centroids.geometry.x
    centroids['centroid_y_utm48n_m'] = centroids.geometry.y
    centroids['longitude_wgs84'] = ll.geometry.x
    centroids['latitude_wgs84'] = ll.geometry.y
    streets = gpd.read_file(ROOT / 'data/administrative/kunming_streets.shp').to_crs(32648)
    streets = streets.rename(columns={'县': 'district', '乡': 'subdistrict'})
    joined = gpd.sjoin(centroids, streets[['district', 'subdistrict', 'geometry']],
                      how='left', predicate='within').drop(columns='index_right')
    if not joined.Build_ID.is_unique:
        raise ValueError('Overlapping street polygons require explicit resolution')
    roads = gpd.read_file(ROOT / 'data/cartography/kunming_simple_basemap.gpkg', layer='roads').to_crs(32648)
    road_types = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary',
                  'unclassified', 'residential', 'living_street',
                  'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link']
    roads = roads[roads.kind.isin(road_types)]
    network = unary_union(roads.geometry.to_list())
    faces = [p for p in polygonize(network) if 1000 <= p.area <= 5_000_000]
    faces.sort(key=lambda p: (*p.bounds, p.area))
    blocks = gpd.GeoDataFrame({'road_block_id': [f'RB{i:05d}' for i in range(1, len(faces)+1)],
                              'road_block_area_m2': [p.area for p in faces]}, geometry=faces, crs=32648)
    joined = gpd.sjoin(joined, blocks, how='left', predicate='within').drop(columns='index_right')
    if not joined.Build_ID.is_unique:
        raise ValueError('Road-derived faces unexpectedly overlap')
    record = joined.drop(columns='geometry').to_json(orient='records', force_ascii=False, double_precision=15)
    (OUT / '过程数据/spatial_context.json').write_text(record, encoding='utf-8')
    blocks.to_file(OUT / '过程数据/road_blocks.gpkg', layer='road_derived_blocks', driver='GPKG')
    metadata = {'crs_projected': 'EPSG:32648', 'coordinate_reference': 'WGS84 EPSG:4326, footprint centroids',
                'road_types': road_types, 'road_segments_used': len(roads), 'road_faces': len(faces),
                'road_face_area_range_m2': [1000, 5_000_000],
                'buildings': len(joined), 'with_road_block': int(joined.road_block_id.notna().sum()),
                'without_subdistrict': int(joined.subdistrict.isna().sum()),
                'limitation': 'Road centerline polygonization is a local neighborhood proxy. Road widths, grade separation, omitted roads and campus/property boundaries are not verified.'}
    (OUT / '过程数据/spatial_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
