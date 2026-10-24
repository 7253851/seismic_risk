"""Independent H/V/E/R joins for the same 188 campus buildings; reuse official map renderers."""
from pathlib import Path
import hashlib,json,zipfile,xml.etree.ElementTree as ET
import geopandas as gpd
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'result/validation/13_event_validation/maps/campus_hver';OUT.mkdir(exist_ok=True)
CONFIGS=[
 dict(key='hazard',file='result/hazard/scs_pipeline/06_building_hazard.gpkg',layer='building_hazard',
      value='PGA_Final_g',class_field='PGA_Class',project='04_seismic_hazard/qgis/projects/04_seismic_hazard_streets.qgz'),
 dict(key='vulnerability',file='result/vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg',
      layer='building_comprehensive_vulnerability',value='Vul_Index',class_field='Vul_Class',project='08_vulnerability_exposure/qgis/projects/08a_vulnerability.qgz'),
 dict(key='exposure',file='result/exposure/scs_paper_method/building_exposure.gpkg',layer='building_exposure_scs',
      value='Exp_Final',class_field='Exposure_Class',project='08_vulnerability_exposure/qgis/projects/08b_exposure.qgz'),
 dict(key='risk',file='result/risk/scs_paper_method/building_risk.gpkg',layer='building_risk_scs',value='Risk_Final',
      class_field='Risk_Class',project='10_risk_transects/qgis/projects/10_risk_base.qgz')]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    scope_path=ROOT/'result/validation/13_event_validation/results/campus_boundary_scope.gpkg'
    scope=gpd.read_file(scope_path,layer='selection_areas')
    all_b=gpd.read_file(scope_path,layer='candidate_buildings_latest')
    buildings=all_b[['Build_ID','case_id','location_id','geometry']].copy()
    assert len(buildings)==188 and buildings.Build_ID.is_unique
    protected={str(p):sha(p) for p in [scope_path,ROOT/'manuscript/tex/manuscript.tex']}
    configs=[];counts=[]
    for config in CONFIGS:
        config=config.copy();src=ROOT/config['file'];map_path=ROOT/'plot'/config['project']
        protected[str(src)]=sha(src);protected[str(map_path)]=sha(map_path)
        source=gpd.read_file(src,layer=config['layer'],columns=['Build_ID',config['value'],config['class_field']])
        assert source.Build_ID.is_unique
        fields=['Build_ID',config['value'],config['class_field']]
        subset=source[source.Build_ID.isin(buildings.Build_ID)][fields]
        buildings=buildings.merge(subset,on='Build_ID',how='left',validate='one_to_one')
        with zipfile.ZipFile(map_path) as z:
            root=ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.qgs'))))
        ml=next(l for l in root.findall('./projectlayers/maplayer') if
                (l.find('./customproperties/Option/Option[@name="seismic_building/result_key"]') is not None and
                 l.find('./customproperties/Option/Option[@name="seismic_building/result_key"]').attrib['value']==config['key']))
        renderer=ml.find('renderer-v2');assert renderer is not None
        style_file=OUT/(config['key']+'_renderer.xml');style_file.write_text(ET.tostring(renderer,encoding='unicode'))
        colors=[]
        for symbol in renderer.findall('./symbols/symbol'):
            color=symbol.find('./layer/Option/Option[@name="color"]').attrib['value']
            r,g,b=map(int,color.split(',')[:3]);colors.append(f'#{r:02x}{g:02x}{b:02x}')
        config['colors']=colors;config['renderer']=str(style_file.relative_to(ROOT))
        assert len(colors)==5
        configs.append(config)
        for cid,frame in buildings.groupby('case_id'):
            counts.append(dict(case_id=cid,indicator=config['key'],campus_buildings=len(frame),
                               valid=int(frame[config['value']].notna().sum()),missing=int(frame[config['value']].isna().sum())))
        # Join values and stored classes exactly; never recompute campus thresholds.
        indexed=subset.set_index('Build_ID')
        for field in fields[1:]:
            current=buildings.set_index('Build_ID').loc[indexed.index,field]
            assert current.equals(indexed[field]),field
    gp=OUT/'campus_hver.gpkg'
    if gp.exists():gp.unlink()
    buildings.to_file(gp,layer='campus_hver',driver='GPKG')
    scope.to_file(gp,layer='campus_boundaries',driver='GPKG')
    known=buildings[buildings.Build_ID.isin([34360,45948,35945])].copy();known['damage_status']='damaged_user_confirmed'
    known.to_file(gp,layer='confirmed_damage',driver='GPKG')
    # Rendering uses FlatGeobuf: independent provider filters avoid shared SQLite query state.
    buildings.to_file(OUT/'campus_hver.fgb',driver='FlatGeobuf')
    scope.to_file(OUT/'campus_boundaries.fgb',driver='FlatGeobuf')
    known.to_file(OUT/'confirmed_damage.fgb',driver='FlatGeobuf')
    pd.DataFrame(counts).to_csv(OUT/'indicator_coverage.csv',index=False,encoding='utf-8-sig')
    (OUT/'data_manifest.json').write_text(json.dumps(dict(configs=configs,counts=counts,sources_sha256=protected,
      selection='same 188 campus footprints; independent indicator joins by Build_ID',values_and_classes_unchanged=True,
      positive_ids=[34360,45948,35945],global_classes_preserved=True,missing_values='retained as null for each indicator'),ensure_ascii=False,indent=2)+'\n')
    print(pd.DataFrame(counts).to_string(index=False))

if __name__=='__main__':main()
