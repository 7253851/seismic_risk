"""Cache real imagery for the enlarged D1/D2 display windows, without stretching it."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from io import BytesIO
import hashlib
import json
import sys
import urllib.parse
import urllib.request

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'result/validation/13_event_validation/maps/damage_cases_2x3'
SERVICE = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'SeismicRiskValidation/1.0'})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def cached_mosaic(case, bounds, pixels, png):
    """Fill real imagery margins from the regional cache, preserving campus detail."""
    parent = ROOT / 'result/validation/13_event_validation/maps/damage_distribution_collage/local_satellite.tif'
    detail = ROOT / case['tif']
    transform = from_bounds(*bounds, *pixels)
    result = np.zeros((3, pixels[1], pixels[0]), dtype='uint8')
    with rasterio.open(parent) as source:
        assert source.bounds.left <= bounds[0] and source.bounds.bottom <= bounds[1]
        assert source.bounds.right >= bounds[2] and source.bounds.top >= bounds[3]
        for band in range(3):
            reproject(rasterio.band(source, band + 1), result[band],
                      src_transform=source.transform, src_crs=source.crs,
                      dst_transform=transform, dst_crs='EPSG:3857', resampling=Resampling.bilinear)
    high_resolution = np.zeros_like(result)
    mask = np.zeros((pixels[1], pixels[0]), dtype='uint8')
    with rasterio.open(detail) as source:
        for band in range(3):
            reproject(rasterio.band(source, band + 1), high_resolution[band],
                      src_transform=source.transform, src_crs=source.crs,
                      dst_transform=transform, dst_crs='EPSG:3857', resampling=Resampling.bilinear)
        reproject(source.read_masks(1), mask, src_transform=source.transform, src_crs=source.crs,
                  dst_transform=transform, dst_crs='EPSG:3857', resampling=Resampling.nearest)
    result[:, mask > 0] = high_resolution[:, mask > 0]
    Image.fromarray(result.transpose(1, 2, 0)).save(png)
    sources = [dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
               for path in [parent, detail]]
    return dict(width=pixels[0], height=pixels[1],
                extent=dict(zip(['xmin', 'ymin', 'xmax', 'ymax'], bounds)),
                method='Georeferenced mosaic: original detailed campus cache over regional real imagery',
                sources=sources, resampling='bilinear', no_generated_content=True)


def main():
    ASSETS.mkdir(exist_ok=True)
    source = json.loads((ROOT / 'result/validation/13_event_validation/maps/campus_2x3/imagery_manifest.json').read_text())
    records = []
    for case in source['cases']:
        cid = case['case_id']
        x0, y0, x1, y1 = case['bounds_3857']
        width, height = x1 - x0, y1 - y0
        display = [x0 - .11 * width, y0 - .19 * height, x1 + .11 * width, y1 + .03 * height]
        padding = (display[2] - display[0]) / 4096 * 3
        requested = [display[0] - padding, display[1] - padding,
                     display[2] + padding, display[3] + padding]
        pixels = [4096, round(4096 * 82 / 86)]
        query = dict(f='pjson', bbox=','.join(f'{v:.9f}' for v in requested),
                     bboxSR=3857, imageSR=3857, size=','.join(map(str, pixels)),
                     format='png24', transparent='false', dpi=300)
        url = SERVICE + '/export?' + urllib.parse.urlencode(query)
        metadata_path = ASSETS / (cid + '_satellite_full_export_png.json')
        png = ASSETS / (cid + '_satellite_full.png')
        tif = ASSETS / (cid + '_satellite_full.tif')
        if not metadata_path.exists() or not png.exists():
            if '--cached-mosaic' in sys.argv:
                metadata = cached_mosaic(case, requested, pixels, png)
                url = None
            else:
                providers = [SERVICE, SERVICE.replace('services.arcgisonline.com', 'server.arcgisonline.com')]
                for index, provider in enumerate(providers):
                    url = provider + '/export?' + urllib.parse.urlencode(query)
                    try:
                        metadata = json.loads(get(url))
                        assert 'error' not in metadata, metadata
                        payload = get(metadata['href'])
                        image = Image.open(BytesIO(payload))
                        image.load()
                        assert image.size == (metadata['width'], metadata['height']) == tuple(pixels)
                        break
                    except (OSError, TimeoutError, ValueError):
                        if index == len(providers) - 1:
                            raise
                        print(cid, 'retrying public imagery endpoint', flush=True)
                png.write_bytes(payload)
            metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
        metadata = json.loads(metadata_path.read_text())
        if metadata.get('sources'):
            url = None
        extent = metadata['extent']
        actual = [extent[key] for key in ['xmin', 'ymin', 'xmax', 'ymax']]
        assert actual[0] <= display[0] and actual[1] <= display[1]
        assert actual[2] >= display[2] and actual[3] >= display[3]
        image = np.array(Image.open(png).convert('RGB'))
        assert image.shape[:2] == tuple(pixels[::-1])
        if not tif.exists():
            with rasterio.open(tif, 'w', driver='GTiff', width=pixels[0], height=pixels[1],
                               count=3, dtype='uint8', crs='EPSG:3857',
                               transform=from_bounds(*actual, *pixels),
                               compress='deflate', tiled=True) as target:
                target.write(image.transpose(2, 0, 1))
        with rasterio.open(tif) as raster:
            assert raster.nodatavals[0] is None
            assert raster.bounds.left <= display[0] and raster.bounds.bottom <= display[1]
            assert raster.bounds.right >= display[2] and raster.bounds.top >= display[3]
        records.append(dict(case_id=cid, display_extent=display, actual_extent=actual,
                            pixels=pixels, png=str(png.relative_to(ROOT)), tif=str(tif.relative_to(ROOT)),
                            png_sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
                            tif_sha256=hashlib.sha256(tif.read_bytes()).hexdigest(),
                            method=metadata.get('method', 'Direct service export'),
                            local_sources=metadata.get('sources', []),
                            export_url=url, display_fully_covered=True))
        print(cid, 'full-frame imagery cached', pixels, flush=True)
    manifest = dict(cached_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    source=SERVICE, copyright=source['copyright'],
                    role=source['role'], satellite_acquisition_date=source['satellite_acquisition_date'],
                    georeferencing='Service returned extents or georeferenced cached-image mosaic; no stretching',
                    cases=records)
    (ASSETS / 'satellite_full_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
