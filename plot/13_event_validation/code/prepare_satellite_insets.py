"""Cache the highest locally available World Imagery tiles for the two inset windows."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import math
import urllib.request

import geopandas as gpd
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'result/intermediate/13_event_validation/cartography/satellite'
SERVICE = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'
BUILDINGS = ROOT / 'result/validation/13_event_validation/maps/campus_hver/confirmed_damage.fgb'
INSETS = [('C', 35945, 'YNAU West'), ('A', 34360, 'YUFE South')]
HALF_WORLD = 20037508.342787


def get(url):
    alternatives = [url, url.replace('services.arcgisonline.com', 'server.arcgisonline.com'), url]
    failure = None
    for candidate in alternatives:
        try:
            request = urllib.request.Request(candidate, headers={'User-Agent': 'SeismicRiskValidation/1.0'})
            with urllib.request.urlopen(request, timeout=12) as response:
                return response.read()
        except (OSError, TimeoutError) as error:
            failure = error
    raise failure


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tiles = OUT / 'tiles'
    tiles.mkdir(exist_ok=True)
    service_path = OUT / 'service_metadata.json'
    if service_path.exists():
        metadata = json.loads(service_path.read_text())
    else:
        metadata = json.loads(get(SERVICE + '?f=pjson'))
        assert 'error' not in metadata, metadata
        service_path.write_text(json.dumps(metadata, indent=2) + '\n')
    source = gpd.read_file(BUILDINGS).to_crs(4543)
    mercator = Transformer.from_crs(4543, 3857, always_xy=True)
    lonlat = Transformer.from_crs(4543, 4326, always_xy=True)
    lods = sorted(metadata['tileInfo']['lods'], key=lambda entry: entry['level'], reverse=True)
    tile_size = metadata['tileInfo']['cols']
    origin = metadata['tileInfo']['origin']
    records = []
    for code, bid, campus in INSETS:
        geometry = source.loc[source.Build_ID == bid].geometry.iloc[0]
        x0, y0, x1, y1 = geometry.bounds
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        half_height = 250. * 42. / 64.
        bounds = [cx - 250., cy - half_height, cx + 250., cy + half_height]
        mx, my = mercator.transform(cx, cy)
        checks = []
        chosen = None
        for entry in lods:
            z, resolution = entry['level'], entry['resolution']
            row = math.floor((origin['y'] - my) / (resolution * tile_size))
            col = math.floor((mx - origin['x']) / (resolution * tile_size))
            url = f'{SERVICE}/tilemap/{z}/{row}/{col}/1/1?f=json'
            answer = json.loads(get(url))
            available = answer.get('data') == [1]
            checks.append({'level': z, 'available': available, 'url': url})
            if available:
                chosen = entry
                break
        assert chosen is not None, (code, checks)
        z, resolution = chosen['level'], chosen['resolution']
        corners = [mercator.transform(x, y) for x in (bounds[0], bounds[2]) for y in (bounds[1], bounds[3])]
        left, bottom = min(p[0] for p in corners), min(p[1] for p in corners)
        right, top = max(p[0] for p in corners), max(p[1] for p in corners)
        col0 = math.floor((left - origin['x']) / (resolution * tile_size))
        col1 = math.floor((right - origin['x']) / (resolution * tile_size))
        row0 = math.floor((origin['y'] - top) / (resolution * tile_size))
        row1 = math.floor((origin['y'] - bottom) / (resolution * tile_size))
        count_x, count_y = col1 - col0 + 1, row1 - row0 + 1
        availability_url = f'{SERVICE}/tilemap/{z}/{row0}/{col0}/{count_x}/{count_y}?f=json'
        availability = json.loads(get(availability_url))
        assert availability.get('data') and all(value == 1 for value in availability['data']), availability
        mosaic = np.empty((count_y * tile_size, count_x * tile_size, 3), dtype=np.uint8)

        def fetch_tile(row, col):
            path = tiles / f'{z}_{row}_{col}.jpg'
            if not path.exists():
                payload = get(f'{SERVICE}/tile/{z}/{row}/{col}')
                image = Image.open(BytesIO(payload)).convert('RGB')
                assert image.size == (tile_size, tile_size), image.size
                path.write_bytes(payload)
            with Image.open(path) as image:
                array = np.asarray(image.convert('RGB'))
                assert array.shape == (tile_size, tile_size, 3)
            return row, col, array, {'row': row, 'col': col, 'path': str(path.relative_to(ROOT)),
                                     'sha256': sha256(path.read_bytes()).hexdigest()}

        tile_records = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            tasks = [pool.submit(fetch_tile, row, col) for row in range(row0, row1 + 1)
                     for col in range(col0, col1 + 1)]
            for task in as_completed(tasks):
                row, col, array, record = task.result()
                y, x = (row - row0) * tile_size, (col - col0) * tile_size
                mosaic[y:y + tile_size, x:x + tile_size] = array
                tile_records.append(record)
        tif = OUT / f'{code}_building_{bid}_satellite.tif'
        transform = from_origin(origin['x'] + col0 * tile_size * resolution,
                                origin['y'] - row0 * tile_size * resolution,
                                resolution, resolution)
        with rasterio.open(tif, 'w', driver='GTiff', width=mosaic.shape[1], height=mosaic.shape[0],
                           count=3, dtype='uint8', crs='EPSG:3857', transform=transform,
                           tiled=True, compress='deflate') as target:
            target.write(mosaic.transpose(2, 0, 1))
            target.update_tags(SOURCE=SERVICE, TILE_LEVEL=str(z),
                               ATTRIBUTION=metadata['copyrightText'],
                               ROLE='Satellite basemap context; acquisition date varies by mosaic')
        latitude = lonlat.transform(cx, cy)[1]
        record = {'code': code, 'Build_ID': bid, 'campus': campus, 'bounds_4543': bounds,
                  'tif': str(tif.relative_to(ROOT)), 'tif_sha256': sha256(tif.read_bytes()).hexdigest(),
                  'highest_available_level': z, 'checked_levels': checks,
                  'full_window_availability_url': availability_url, 'all_window_tiles_available': True,
                  'native_mercator_resolution_m': resolution,
                  'approx_ground_resolution_m': resolution * math.cos(math.radians(latitude)),
                  'pixels': [mosaic.shape[1], mosaic.shape[0]],
                  'tiles': sorted(tile_records, key=lambda entry: (entry['row'], entry['col'])),
                  'resampled_or_upscaled': False}
        records.append(record)
        print(code, bid, 'cached at highest available level', z, 'pixels', record['pixels'], flush=True)
    manifest = {'cached_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'source': SERVICE,
                'copyright': metadata['copyrightText'], 'method': 'Native tiles, georeferenced without resampling',
                'role': 'Satellite basemap context; not event-date damage evidence',
                'acquisition_date': 'Unknown; World Imagery mosaic dates vary', 'cases': records}
    (OUT / 'satellite_insets_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
