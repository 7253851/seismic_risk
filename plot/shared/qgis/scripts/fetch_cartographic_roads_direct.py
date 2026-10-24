"""Overpass不可用时，从OSM只读map API按小范围读取，仅输出道路和河流。"""
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as E
import geopandas as gpd
from shapely.geometry import LineString,box
import json,hashlib
from qgis_paths import ROOT as BASE
OUT=BASE/'../data/cartography';RAW=BASE/'../result/intermediate/cartography/osm_direct';RAW.mkdir(parents=True,exist_ok=True)
import zipfile
cache_archive=BASE/'../result/intermediate/cartography/osm_source_cache.zip'
if cache_archive.exists():
 with zipfile.ZipFile(cache_archive) as cache_zip:
  for member in cache_zip.namelist():
   if Path(member).name != member: raise RuntimeError('Unsafe cache member')
   if not (RAW/member).exists(): (RAW/member).write_bytes(cache_zip.read(member))
BBOX=(102.491,24.748,103.051,25.257);CAMPUS=box(102.705,25.075,102.735,25.105)
major={'motorway','trunk','primary','secondary','tertiary','motorway_link','trunk_link','primary_link','secondary_link','tertiary_link'}
URL='https://api.openstreetmap.org/api/0.6/map'
def download(bbox,depth=0):
 ident='_'.join(f'{v:.5f}' for v in bbox);p=RAW/(ident+'.osm')
 try:
  if not p.exists():
   request=Request(URL+'?bbox='+','.join(str(v) for v in bbox),headers={'User-Agent':'KunmingResearchCartography/1.0'})
   with urlopen(request,timeout=30) as r:p.write_bytes(r.read())
  root=E.fromstring(p.read_bytes());return [(p,root)]
 except HTTPError as e:
  if e.code==400 and depth<2:
   x1,y1,x2,y2=bbox;xm=(x1+x2)/2;ym=(y1+y2)/2
   result=[]
   for bb in [(x1,y1,xm,ym),(xm,y1,x2,ym),(x1,ym,xm,y2),(xm,ym,x2,y2)]:result+=download(bb,depth+1)
   return result
  raise
xs=[BBOX[0]+(BBOX[2]-BBOX[0])*i/5 for i in range(6)];ys=[BBOX[1]+(BBOX[3]-BBOX[1])*i/5 for i in range(6)]
areas=[(xs[i],ys[j],xs[i+1],ys[j+1]) for j in range(5) for i in range(5)]
parts=[];errors=[]
with ThreadPoolExecutor(max_workers=2) as executor:
 pending={executor.submit(download,b):b for b in areas}
 for future in as_completed(pending):
  try:parts+=future.result();print('OSM map cells ready:',len(parts),flush=True)
  except Exception as e:errors.append({'bbox':pending[future],'error':str(e)});print('cell failed:',str(e)[:130],flush=True)
# 既有财大缓存，确保局部道路细节，且避免重复联网。
cached=BASE/'../result/intermediate/api_reference/yufe_20261012/osm_direct_response.osm'
parts.append((cached,E.parse(cached).getroot()))
rows={};source_files=[]
for p,root in parts:
 nodes={n.get('id'):(float(n.get('lon')),float(n.get('lat'))) for n in root.findall('node')}
 source_files.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 for way in root.findall('way'):
  tags={t.get('k'):t.get('v') for t in way.findall('tag')};highway=tags.get('highway');waterway=tags.get('waterway')
  if not highway and waterway not in {'river','canal'}:continue
  refs=[n.get('ref') for n in way.findall('nd')]
  if any(r not in nodes for r in refs):continue
  if len(refs)<2:continue
  geom=LineString([nodes[r] for r in refs])
  if highway and highway not in major and not geom.intersects(CAMPUS):continue
  geom=geom.intersection(box(*BBOX))
  if geom.is_empty:continue
  rows[way.get('id')]={'osm_id':way.get('id'),'kind':highway or waterway,'feature_type':'road' if highway else 'waterway','geometry':geom}
if errors:
 (OUT/'osm_direct_errors.json').write_text(json.dumps(errors,indent=2))
 raise RuntimeError(f'{len(errors)} cells unavailable; cache retained for retry')
g=gpd.GeoDataFrame(list(rows.values()),crs=4326)
path=OUT/'kunming_simple_basemap.gpkg'
for typ,name in [('road','roads'),('waterway','waterways')]:g[g.feature_type==typ].to_file(path,layer=name,driver='GPKG')
report={'retrieved_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'endpoint':URL,'license':'ODbL 1.0',
 'attribution':'© OpenStreetMap contributors','copyright_url':'https://www.openstreetmap.org/copyright','source_crs':'EPSG:4326',
 'main_bbox_w_s_e_n':BBOX,'roads':int(sum(g.feature_type=='road')),'waterways':int(sum(g.feature_type=='waterway')),
 'no_names_poi_or_buildings_in_export':True,'cached_cells':len(parts),'source_files':source_files}
(OUT/'osm_source.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('Complete:',report['roads'],'roads,',report['waterways'],'waterways',flush=True)
