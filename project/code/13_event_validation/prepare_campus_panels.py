"""Subset the existing four campus boundaries and unaltered risk / deformation values."""
from pathlib import Path
import json,hashlib
import geopandas as gpd
import rasterio
from rasterio.mask import mask

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'result/validation/13_event_validation/maps/campus_2x3';OUT.mkdir(parents=True,exist_ok=True)

def main():
    source=ROOT/'result/validation/13_event_validation/results/campus_boundary_scope.gpkg'
    scope=gpd.read_file(source,layer='selection_areas')
    candidates=gpd.read_file(source,layer='candidate_buildings_latest')
    target=OUT/'campus_panel_data.gpkg'
    if target.exists():target.unlink()
    scope.to_file(target,layer='campus_boundaries',driver='GPKG')
    candidates.to_file(target,layer='campus_buildings',driver='GPKG')
    known=candidates[candidates.Build_ID.isin([34360,45948,35945])].copy()
    known['damage_status']='damaged_user_confirmed'
    known.to_file(target,layer='confirmed_damage',driver='GPKG')
    rate=ROOT/'data/TSX_PS/TSX_merged_v_vertical_20m.tif'
    records=[]
    with rasterio.open(rate) as src:
        for case,sub in scope.groupby('case_id'):
            data,transform=mask(src,sub.to_crs(src.crs).geometry,crop=True,filled=True)
            profile=src.profile.copy();profile.update(width=data.shape[2],height=data.shape[1],transform=transform,compress='deflate')
            destination=OUT/f'{case}_vertical_velocity.tif'
            with rasterio.open(destination,'w',**profile) as dst:dst.write(data)
            valid=data[0][data[0]!=src.nodata]
            records.append(dict(case_id=case,rate_valid_pixels=int(valid.size),minimum=float(valid.min()),maximum=float(valid.max()),
              candidates=int(candidates.case_id.eq(case).sum()),risk_valid=int((candidates.case_id.eq(case)&candidates.Risk_Final.notna()).sum())))
    (OUT/'panel_data_manifest.json').write_text(json.dumps(dict(cases=records,positive_ids=[34360,45948,35945],
      risk='current SCS final five-class result; missing risk retains null',deformation='existing 20m vertical-velocity raster clipped to campus boundaries; no interpolation',
      boundary_buffers_created=0,sources_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,rate,ROOT/'result/risk/scs_paper_method/building_risk.gpkg',ROOT/'manuscript/tex/manuscript.tex']}),ensure_ascii=False,indent=2)+'\n')
    print(records)

if __name__=='__main__':main()
