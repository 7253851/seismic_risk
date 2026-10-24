"""Independent population, baseline, pair, PS and source-preservation audit."""
from pathlib import Path
import argparse,hashlib,json,re,sqlite3
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import Delaunay
from PIL import Image
from shapely.geometry import LineString
ROOT=Path(__file__).resolve().parents[3]
NAMES=np.array(['Very Low','Low','Moderate','High','Very High'])
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('output_dir',type=Path);out=parser.parse_args().output_dir.resolve()
 d=pd.read_csv(out/'data/all_40000_buildings.csv',float_precision='round_trip').set_index('Build_ID').sort_index()
 source=pd.read_csv(ROOT/'result/intermediate/12_insar_contribution/strict_ablation_full_40000.csv',float_precision='round_trip',low_memory=False).set_index('Build_ID').sort_index()
 s=json.loads((out/'data/static_baseline_statistics.json').read_text());lo,hi=s['static_vulnerability_P1_P99'];pmin,pmax=s['static_risk_product_min_max'];breaks=np.array(s['frozen_static_Jenks_breaks'])
 assert len(d)==40000 and d.index.is_unique and d.index.equals(source.index)
 v0=(np.minimum(np.maximum(source.V_static,lo),hi)-lo)/(hi-lo)
 v1=(np.minimum(np.maximum(source.V_static*(1+s['alpha']*source.IBSI),lo),hi)-lo)/(hi-lo)
 r0=(source.H_Index*v0*source.E_Index-pmin)/(pmax-pmin)
 r1=(source.H_Index*v1*source.E_Index-pmin)/(pmax-pmin)
 errors={}
 for key,a,b in [('baseline_anchor',d.R_static_baseline,source.R0),('baseline_reconstruction',d.R_static_baseline,r0),('after_insar_reconstruction',d.R_insar_static_baseline,r1),('score_increment',d.delta_R_static_baseline,r1-r0)]:
  errors[key]=float(abs(a-b).max());assert errors[key]<1e-14,(key,errors[key])
 assert d.static_class.eq(source.Class0_Jenks).all()
 for values,field in [(r0,'static_class'),(r1,'insar_class')]:assert d[field].eq(NAMES[np.searchsorted(breaks[1:-1],values,side='left')]).all()
 assert d.class_steps.ge(0).all() and d.delta_R_static_baseline.ge(-1e-14).all()
 changed=pd.read_csv(out/'data/all_risk_class_changes.csv',float_precision='round_trip').set_index('Build_ID')
 upgraded=int(d.class_steps.gt(0).sum());assert upgraded==s['upgrade_n']
 assert set(changed.index)==set(d.index[d.class_steps.ne(0)]) and len(changed)==upgraded
 matrix=pd.crosstab(d.static_class,d.insar_class).reindex(index=NAMES,columns=NAMES,fill_value=0)
 assert matrix.to_numpy().tolist()==s['matrix'] and matrix.to_numpy().sum()==40000
 moderate_high=int(matrix.loc['Moderate','High'])
 assert s['unchanged_n']==40000-upgraded and s['downgrade_n']==0 and moderate_high==s['moderate_to_high_n']
 transitions=pd.read_csv(out/'data/risk_class_transition_summary.csv');assert transitions.building_count.sum()==40000
 district=pd.read_csv(out/'data/district_upgrade_rates.csv');assert district.buildings.sum()==40000 and district.upgraded.sum()==upgraded
 c=pd.read_csv(out/'data/candidate_building_cases.csv',float_precision='round_trip');assert c.Build_ID.is_unique and len(c)==s['selected_cases_n']
 pairs=pd.read_csv(out/'data/block_matched_pairs.csv',float_precision='round_trip');cfg=s['accepted_pair_tier']
 assert len(pairs)==s['relaxed_changed_vs_unchanged_pairs_n']==3
 checks=[]
 for _,p in pairs.iterrows():
  t,k=d.loc[int(p.target_id)],d.loc[int(p.control_id)]
  assert t.class_steps>0 and k.class_steps==0 and t.static_class==k.static_class
  assert t.road_block_id==k.road_block_id and t.subdistrict==k.subdistrict and t.district==k.district
  distance=np.hypot(t.centroid_x_utm48n_m-k.centroid_x_utm48n_m,t.centroid_y_utm48n_m-k.centroid_y_utm48n_m)
  assert abs(distance-p.distance_m)<1e-8 and distance<=cfg['radius']
  assert abs(t.R_static_baseline-k.R_static_baseline)<=cfg['risk'] and abs(t.V_static-k.V_static)<=cfg['v']
  assert abs(t.H_Index-k.H_Index)<=cfg['h'] and abs(t.E_Index-k.E_Index)<=cfg['e']
  assert cfg['area'][0]<=k.Area_m2/t.Area_m2<=cfg['area'][1] and cfg['height'][0]<=k.Height_m/t.Height_m<=cfg['height'][1]
  assert t.IBSI-k.IBSI>=cfg['ibsi_gap'] and t.V_RMS/k.V_RMS>=cfg['rms_ratio'] and k.IBSI<=cfg['control_ibsi']
  assert t.screen_eligible
  for row in [t,k]:assert row.PS_Count>=cfg['min_ps'] and row.PS_CohMn>=cfg['min_coh'] and row.PS_Cov>=cfg['min_cov'] and row.Q_insar>=cfg['min_q']
  checks.append({'target_id':int(p.target_id),'control_id':int(p.control_id),'all_accepted_conditions_passed':True})
 spatial_checks=[]
 all_pair_ids=sorted(set(pairs.target_id.astype(int))|set(pairs.control_id.astype(int)))
 pair_where='Build_ID IN ('+','.join(map(str,all_pair_ids))+')'
 buildings=gpd.read_file(ROOT/'result/risk/scs_paper_method/building_risk.gpkg',layer='building_risk_scs',where=pair_where).set_index('Build_ID')
 for _,p in pairs.iterrows():
  block=gpd.read_file(ROOT/'result/intermediate/12_insar_contribution/road_blocks.gpkg',layer='road_derived_blocks',where=f"road_block_id = '{p.road_block}'").geometry.iloc[0]
  tgeom,cgeom=buildings.loc[int(p.target_id)].geometry,buildings.loc[int(p.control_id)].geometry
  assert block.covers(tgeom) and block.covers(cgeom) and block.covers(LineString([tgeom.centroid,cgeom.centroid]))
  spatial_checks.append({'target_id':int(p.target_id),'control_id':int(p.control_id),'both_footprints_and_connector_inside_same_road_derived_block':True,'edge_distance_m':float(tgeom.distance(cgeom))})
 pair_ids=s['pair_ids'];where='Build_ID IN ('+','.join(map(str,pair_ids))+')'
 ps=gpd.read_file(ROOT/'result/intermediate/vulnerability_inputs/building_ps_points.gpkg',layer='building_ps_points',where=where)
 ps_checks=[]
 panel_nodes=pd.read_csv(out/'data/case_panel_PS_nodes.csv',float_precision='round_trip')
 panel_edges=pd.read_csv(out/'data/case_panel_PS_edges.csv',float_precision='round_trip')
 panel_meta=json.loads((out/'data/case_panel_diagnostics.json').read_text())
 assert panel_meta['building_ids']==pair_ids and panel_meta['associated_PS_records']==[109,57]
 assert panel_nodes[['Build_ID','node']].duplicated().sum()==0 and len(panel_nodes)==166
 for bid in pair_ids:
  points=ps[ps.Build_ID.eq(bid)];xy=np.c_[points.geometry.x,points.geometry.y];coords,inv=np.unique(xy,axis=0,return_inverse=True);count=np.bincount(inv)
  v=np.bincount(inv,weights=points.v_vertical)/count;coh=np.bincount(inv,weights=points.coh.clip(0,1))/count
  rms=np.sqrt(np.mean(v*v));center=np.average(coords,axis=0,weights=coh);z=coords-center
  slope,*_=np.linalg.lstsq(z*np.sqrt(coh[:,None]),(v-np.average(v,weights=coh))*np.sqrt(coh),rcond=None)
  tilt=np.degrees(np.arctan(np.linalg.norm(slope)/1000))
  triangles=Delaunay(coords).simplices;edges=np.unique(np.sort(np.concatenate([triangles[:,[0,1]],triangles[:,[1,2]],triangles[:,[2,0]]]),axis=1),axis=0);left,right=edges.T;dist=np.linalg.norm(coords[left]-coords[right],axis=1);ok=(dist>0)&(dist<=20);left,right,dist=left[ok],right[ok],dist[ok]
  g=.5*(coh[left]+coh[right])*abs(v[left]-v[right])/dist;degree=np.bincount(np.r_[left,right],minlength=len(coords));total=np.bincount(np.r_[left,right],weights=np.r_[g,g],minlength=len(coords));gradient=np.divide(total,degree,out=np.full(len(coords),np.nan),where=degree>0);abnormal=gradient>np.nanpercentile(gradient,90);dgi=.5*np.nanmean(gradient[abnormal])+.5*np.nanmax(gradient[abnormal])
  node=panel_nodes[panel_nodes.Build_ID.eq(bid)].sort_values('node')
  edge=panel_edges[panel_edges.Build_ID.eq(bid)]
  assert np.allclose(node[['x','y']],coords,rtol=0,atol=1e-9)
  assert np.allclose(node.observed_rate,v,rtol=0,atol=1e-12)
  plane=np.average(v,weights=coh)+z@slope
  assert np.allclose(node.fitted_rate,plane,rtol=0,atol=1e-12)
  assert np.allclose(node.residual_rate,v-plane,rtol=0,atol=1e-12)
  assert np.allclose(node.point_gradient,gradient,rtol=0,atol=1e-12,equal_nan=True)
  assert np.array_equal(node.gradient_abnormal,abnormal)
  assert np.array_equal(edge[['left_node','right_node']],np.c_[left,right])
  assert np.allclose(edge.edge_gradient,g,rtol=0,atol=1e-12)
  assert node.observed_rate.between(*panel_meta['observed_rate_color_bounds']).all()
  assert node.residual_rate.between(*panel_meta['residual_color_bounds']).all()
  row=d.loc[bid];assert len(points)==row.PS_Count and np.isclose(points.coh.mean(),row.PS_CohMn,atol=1e-12)
  assert np.isclose(rms,row.V_RMS,atol=1e-12) and np.isclose(tilt,row.Tilt_Angle,atol=1e-12) and np.isclose(dgi,row.DGI_Str,atol=1e-12)
  ps_checks.append({'Build_ID':bid,'PS_records':len(points),'unique_locations':len(coords),'RMS_error':abs(rms-row.V_RMS),'Tilt_error':abs(tilt-row.Tilt_Angle),'DGI_error':abs(dgi-row.DGI_Str)})
 preserve=json.loads((out/'data/preservation.json').read_text())
 receipt=out/'data/source_fingerprints_current.json'
 expected_current=json.loads(receipt.read_text())['source_files'] if receipt.is_file() else {}
 historical_fingerprints={}
 for path,value in preserve['formal_source_files'].items():
  actual=sha(ROOT/path);historical_fingerprints[path]=(actual==value)
  assert actual==value or actual==expected_current.get(path),path
 # Check the actual current model attributes, independently of container metadata hashes.
 with sqlite3.connect(f'file:{ROOT}/result/vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg?mode=ro&immutable=1',uri=True) as conn:
  values=pd.read_sql_query('SELECT Build_ID,V_static,IBSI FROM building_comprehensive_vulnerability',conn).set_index('Build_ID').loc[d.index]
 assert np.allclose(values.V_static,d.V_static,rtol=0,atol=1e-14)
 assert np.allclose(values.IBSI,d.IBSI,rtol=0,atol=1e-14)

 gpkg=out/'QGIS/data/static_baseline_5_1.gpkg'
 with sqlite3.connect(f'file:{gpkg}?mode=ro',uri=True) as conn:
  assert conn.execute('SELECT COUNT(*) FROM upgraded_building_points').fetchone()[0]==upgraded
  assert conn.execute('SELECT COUNT(*) FROM all_40000_buildings').fetchone()[0]==40000
  assert conn.execute('SELECT COUNT(*) FROM primary_pair_footprints').fetchone()[0]==2
 current_png=ROOT/'plot/12_insar_contribution/output/final/figure12.png'
 with Image.open(current_png) as im:assert min(im.info['dpi'])>599.9
 assert sha(current_png)==next(f['adopted_sha256'] for f in json.loads((ROOT/'plot/figure_index.json').read_text())['figures'] if f['figure']==12)
 for doc in ['README.md','数值结果分析.md','补充材料.md','图件汇总.md']:
  for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',(out/doc).read_text()):
   if not target.startswith(('http:','https:','#')) and target!='data/verification.json':assert (out/target).exists(),(doc,target)
 report={'status':'passed','protocol':s['protocol'],'sample_n':40000,'upgraded_n':upgraded,'unchanged_n':40000-upgraded,'downgraded_n':0,'Moderate_to_High_n':moderate_high,'maximum_score_reconstruction_errors':errors,'accepted_relaxed_pairs':checks,'pair_spatial_checks':spatial_checks,'primary_pair_PS_reconstruction':ps_checks,'formal_numeric_sources_and_adopted_pngs_unchanged':True,'historical_container_fingerprints_match':historical_fingerprints,'current_model_attributes_match':True,'map_and_csv_population_counts_match':True,'case_panel_source_geometry_rates_planes_and_gradients_verified':True}
 (out/'data/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
