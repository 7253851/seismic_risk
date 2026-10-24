"""Download a native WorldCover window and extract class 50 for the study map.

Run using run_pyqgis.sh. Network is needed only when the raw subset is missing.
No existing building, administrative, DEM or study-footprint data are modified.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import math
import tempfile
import urllib.request

import numpy as np
from osgeo import gdal, ogr, osr
from qgis.core import QgsApplication, QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / '../result/intermediate/landcover/esa_worldcover_2021_kunming_study_landcover.tif'
DEST = ROOT / '../data/landcover'
BINARY = DEST / 'kunming_study_builtup_2021.tif'
VECTOR = DEST / 'kunming_study_builtup_2021.gpkg'
SOURCE = 'https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N24E102_Map.tif'
SOURCE_ETAG = 'e716c9b6bc62524e0d98783d60dc24a2-18'
SOURCE_TILE = RAW.parent / Path(SOURCE.rsplit('/', 1)[-1])
PRODUCT = 'https://esa-worldcover.org/en/data-access'
MANUAL = 'https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/docs/WorldCover_PUM_V2.0.pdf'
DOI = 'https://doi.org/10.5281/zenodo.7254221'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def progress(stage):
    last = [-1]
    def callback(fraction, message, data):
        pct = int(fraction * 10) * 10
        if pct > last[0]:
            print(f'{stage}: {pct}%', flush=True)
            last[0] = pct
        return 1
    return callback


def download_source_tile():
    """Cache the immutable COG locally to avoid unreliable remote range reads."""
    part = SOURCE_TILE.with_suffix('.part.tif')
    request = urllib.request.Request(SOURCE, headers={'User-Agent': 'Kunming-study-area-map/1.0'})
    with urllib.request.urlopen(request, timeout=90) as response:
        etag = response.headers.get('ETag', '').strip('"')
        if etag != SOURCE_ETAG:
            raise RuntimeError('ESA WorldCover tile ETag differs from the recorded source')
        total = int(response.headers.get('Content-Length', '0'))
        downloaded = 0
        last_reported = -10
        with part.open('wb') as stream:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                stream.write(block)
                downloaded += len(block)
                if total:
                    pct = downloaded * 100 // total
                    if pct >= last_reported + 10:
                        print(f'Downloading ESA source tile: {pct}%', flush=True)
                        last_reported = pct
    if total and downloaded != total:
        part.unlink(missing_ok=True)
        raise RuntimeError(f'Incomplete ESA tile download: {downloaded} of {total} bytes')
    part.replace(SOURCE_TILE)


def build():
    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], False)
        app.initQgis()
    project = QgsProject()
    if not project.read(str(ROOT / '01_study_area/qgis/projects/01_study_area.qgz')):
        raise RuntimeError('Study project unavailable')
    map_ = project.layoutManager().layoutByName('Kunming_Study_Area').itemById('C_Study_Area')
    crs = QgsCoordinateReferenceSystem('EPSG:4326')
    extent = QgsCoordinateTransform(map_.crs(), crs, project).transformBoundingBox(map_.extent())
    extent.grow(0.015)  # Retain context beyond the current frame, about 1.5 km.
    requested = [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()]
    RAW.parent.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    gdal.UseExceptions()
    for name, value in {
        'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR',
        'CPL_VSIL_CURL_ALLOWED_EXTENSIONS': '.tif',
        'GDAL_HTTP_TIMEOUT': '30', 'GDAL_HTTP_MAX_RETRY': '2',
        'GDAL_HTTP_RETRY_DELAY': '2', 'CPL_VSIL_CURL_CHUNK_SIZE': '262144',
    }.items():
        gdal.SetConfigOption(name, value)
    if not RAW.exists():
        if not SOURCE_TILE.exists():
            print('Downloading the verified ESA WorldCover COG for reliable local extraction', flush=True)
            download_source_tile()
        remote = gdal.Open(str(SOURCE_TILE), gdal.GA_ReadOnly)
        if remote is None:
            raise RuntimeError('Cannot open ESA WorldCover source tile: ' + str(SOURCE_TILE))
        gt = remote.GetGeoTransform()
        inv = gdal.InvGeoTransform(gt)
        x0, y0 = gdal.ApplyGeoTransform(inv, requested[0], requested[3])
        x1, y1 = gdal.ApplyGeoTransform(inv, requested[2], requested[1])
        x0, y0, x1, y1 = math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)
        if not (0 <= x0 < x1 <= remote.RasterXSize and 0 <= y0 < y1 <= remote.RasterYSize):
            raise RuntimeError('Requested area is outside the verified source tile')
        print(f'Native source window: {x1-x0} × {y1-y0} pixels', flush=True)
        part = RAW.with_suffix('.part.tif')
        dataset = gdal.Translate(str(part), remote, srcWin=[x0, y0, x1-x0, y1-y0],
                                 format='GTiff', creationOptions=['TILED=YES', 'COMPRESS=DEFLATE'],
                                 callback=progress('Downloading regional data'))
        dataset = None
        remote = None
        part.replace(RAW)
    raw = gdal.Open(str(RAW), gdal.GA_ReadOnly)
    gt = raw.GetGeoTransform()
    bounds = [gt[0], gt[3] + raw.RasterYSize * gt[5], gt[0] + raw.RasterXSize * gt[1], gt[3]]
    if not (bounds[0] <= requested[0] and bounds[1] <= requested[1] and bounds[2] >= requested[2] and bounds[3] >= requested[3]):
        raise RuntimeError('Existing raw subset does not cover the requested frame and buffer')
    print('Extracting native class 50 (Built-up)', flush=True)
    binary_part = BINARY.with_suffix('.part.tif')
    binary = gdal.GetDriverByName('GTiff').Create(str(binary_part), raw.RasterXSize, raw.RasterYSize, 1,
                                               gdal.GDT_Byte, ['TILED=YES', 'COMPRESS=DEFLATE'])
    binary.SetGeoTransform(gt)
    binary.SetProjection(raw.GetProjection())
    band = binary.GetRasterBand(1)
    band.SetNoDataValue(255)
    band.SetDescription('1=ESA WorldCover class 50; 0=other valid cover; 255=NoData')
    mask = gdal.GetDriverByName('MEM').Create('', raw.RasterXSize, raw.RasterYSize, 1, gdal.GDT_Byte)
    mask.SetGeoTransform(gt)
    mask.SetProjection(raw.GetProjection())
    counts = {}
    for row in range(0, raw.RasterYSize, 256):
        height = min(256, raw.RasterYSize - row)
        arr = raw.GetRasterBand(1).ReadAsArray(0, row, raw.RasterXSize, height)
        values, n = np.unique(arr, return_counts=True)
        for value, count in zip(values, n):
            counts[int(value)] = counts.get(int(value), 0) + int(count)
        built = (arr == 50).astype(np.uint8)
        mask.GetRasterBand(1).WriteArray(built, 0, row)
        built[arr == 0] = 255
        band.WriteArray(built, 0, row)
    binary.FlushCache()
    if counts.get(50, 0) == 0:
        raise RuntimeError('No built-up pixels were found')
    color = gdal.ColorTable()
    color.SetColorEntry(0, (0, 0, 0, 0))
    color.SetColorEntry(1, (255, 240, 192, 255))
    color.SetColorEntry(255, (0, 0, 0, 0))
    band.SetRasterColorTable(color)
    band.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    vector_part = VECTOR.with_suffix('.part.gpkg')
    if vector_part.exists():
        vector_part.unlink()
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    driver = ogr.GetDriverByName('GPKG')
    with tempfile.TemporaryDirectory(prefix='kunming_builtup_') as tmp:
        polygons = driver.CreateDataSource(str(Path(tmp) / 'pixels.gpkg'))
        source_layer = polygons.CreateLayer('pixels', srs, ogr.wkbPolygon)
        source_layer.CreateField(ogr.FieldDefn('built', ogr.OFTInteger))
        gdal.Polygonize(band, mask.GetRasterBand(1), source_layer, 0, [], callback=progress('Polygonizing class 50'))
        final = driver.CreateDataSource(str(vector_part))
        target = final.CreateLayer('builtup_2021', srs, ogr.wkbMultiPolygon)
        for name, type_ in [('source_class', ogr.OFTInteger), ('year', ogr.OFTInteger), ('pixels', ogr.OFTInteger64)]:
            target.CreateField(ogr.FieldDefn(name, type_))
        target.StartTransaction()
        polygon_count, repaired, total_pixels = 0, 0, 0
        pixel_area = abs(gt[1] * gt[5])
        for feature in source_layer:
            geom = feature.GetGeometryRef().Clone()
            n_pixels = round(geom.GetArea() / pixel_area)
            if not geom.IsValid():
                geom = geom.MakeValid()
                repaired += 1
            geom = ogr.ForceToMultiPolygon(geom)
            if ogr.wkbFlatten(geom.GetGeometryType()) != ogr.wkbMultiPolygon or geom.IsEmpty():
                raise RuntimeError('Cannot preserve polygonized built-up geometry')
            record = ogr.Feature(target.GetLayerDefn())
            record.SetField('source_class', 50)
            record.SetField('year', 2021)
            record.SetField('pixels', n_pixels)
            record.SetGeometry(geom)
            target.CreateFeature(record)
            polygon_count += 1
            total_pixels += n_pixels
        target.CommitTransaction()
        final = None
        polygons = None
    if total_pixels != counts[50]:
        raise RuntimeError('Raster/vector built-up pixel totals do not match')
    band = None
    binary = None
    raw = None
    mask = None
    binary_part.replace(BINARY)
    vector_part.replace(VECTOR)
    info = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'product': 'ESA WorldCover 2021 v200', 'year': 2021,
        'product_url': PRODUCT, 'product_manual': MANUAL, 'doi': DOI,
        'source_tile_url': SOURCE, 'source_tile': 'N24E102',
        'source_tile_etag': SOURCE_ETAG,
        'license': 'Creative Commons Attribution 4.0 International',
        'attribution': '© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium',
        'class_value': 50, 'class_name': 'Built-up',
        'interpretation': 'Remote-sensing built-up land cover; not an official statistical urban-area boundary.',
        'scope': 'Kunming study-map rectangle plus 0.015 degree context, not the full municipality',
        'requested_extent_wgs84': requested, 'actual_extent_wgs84': bounds,
        'crs': 'EPSG:4326', 'nominal_resolution_m': 10, 'pixel_size_degrees': [abs(gt[1]), abs(gt[5])],
        'raster_pixels': [int(round((bounds[2]-bounds[0])/gt[1])), int(round((bounds[3]-bounds[1])/abs(gt[5])))],
        'source_class_pixel_counts': counts, 'builtup_pixels': counts[50],
        'vector_features': polygon_count, 'repaired_geometries': repaired,
        'vector_pixel_sum_equals_raster': True,
        'processing': 'Native COG window without resampling; extract class 50; 4-connected polygonize; make valid when needed; preserve all pixel components without filtering or smoothing.',
        'binary_values': {'0': 'other valid cover', '1': 'built-up', '255': 'NoData'},
        'source_tile_file': str(SOURCE_TILE),
        'files': {str(p): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in [SOURCE_TILE, RAW, BINARY, VECTOR]},
    }
    (DEST / 'kunming_study_builtup_2021.source.json').write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    build()
