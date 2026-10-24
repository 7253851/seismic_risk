"""Explicit relaxed matching tiers; no risk or classification is recalculated."""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
RELAXED_TIERS=[
 {'name':'B_observation_support','min_ps':8,'min_coh':.75,'min_cov':.05,'min_q':.4,'risk':.01,'v':.05,'h':.03,'e':.05,'area':(.5,2),'height':(.5,2),'ibsi_gap':.1,'rms_ratio':1.5,'control_ibsi':.15,'radius':300,'robust_target':True,'same_block':True},
 {'name':'C_same_block_static_tolerances','min_ps':8,'min_coh':.75,'min_cov':.05,'min_q':.4,'risk':.02,'v':.10,'h':.05,'e':.10,'area':(1/3,3),'height':(.5,2),'ibsi_gap':.05,'rms_ratio':1.2,'control_ibsi':.25,'radius':300,'robust_target':True,'same_block':True},
 {'name':'D_same_block_all_quality_upgrades','min_ps':8,'min_coh':.75,'min_cov':.05,'min_q':.4,'risk':.03,'v':.10,'h':.05,'e':.10,'area':(1/3,3),'height':(.5,2),'ibsi_gap':.05,'rms_ratio':1.2,'control_ibsi':.25,'radius':500,'robust_target':False,'same_block':True},
 {'name':'E_same_subdistrict_500m','min_ps':8,'min_coh':.75,'min_cov':.05,'min_q':.4,'risk':.03,'v':.10,'h':.05,'e':.10,'area':(1/3,3),'height':(.5,2),'ibsi_gap':.05,'rms_ratio':1.2,'control_ibsi':.25,'radius':500,'robust_target':False,'same_block':False}]

def search(d,t):
 quality=d.PS_Count.ge(t['min_ps'])&d.PS_CohMn.ge(t['min_coh'])&d.PS_Cov.ge(t['min_cov'])&d.Q_insar.ge(t['min_q'])
 targets=d[quality&d.class_steps.gt(0)&d.delta_R_static_baseline.ge(.003)]
 if t['robust_target']:targets=targets[targets.screen_eligible]
 controls=d[quality&d.class_steps.eq(0)&d.IBSI.le(t['control_ibsi'])]
 tree=cKDTree(controls[['centroid_x_utm48n_m','centroid_y_utm48n_m']]);out=[]
 for _,r in targets.iterrows():
  positions=tree.query_ball_point([r.centroid_x_utm48n_m,r.centroid_y_utm48n_m],t['radius']);pool=controls.iloc[positions].copy()
  pool=pool[pool.static_class.eq(r.static_class)&pool.subdistrict.eq(r.subdistrict)&pool.district.eq(r.district)]
  if t['same_block']:
   if pd.isna(r.road_block_id):continue
   pool=pool[pool.road_block_id.eq(r.road_block_id)]
  if pool.empty:continue
  pool=pool[(pool.R_static_baseline-r.R_static_baseline).abs().le(t['risk'])&(pool.V_static-r.V_static).abs().le(t['v'])&(pool.H_Index-r.H_Index).abs().le(t['h'])&(pool.E_Index-r.E_Index).abs().le(t['e'])&(pool.Area_m2/r.Area_m2).between(*t['area'])&(pool.Height_m/r.Height_m).between(*t['height'])&(r.IBSI-pool.IBSI).ge(t['ibsi_gap'])&(r.V_RMS/pool.V_RMS).ge(t['rms_ratio'])]
  for _,c in pool.iterrows():
   dist=float(np.hypot(r.centroid_x_utm48n_m-c.centroid_x_utm48n_m,r.centroid_y_utm48n_m-c.centroid_y_utm48n_m))
   out.append({'target_id':int(r.Build_ID),'control_id':int(c.Build_ID),'distance_m':dist,'static_risk_absdiff':abs(r.R_static_baseline-c.R_static_baseline),'static_v_absdiff':abs(r.V_static-c.V_static),'H_absdiff':abs(r.H_Index-c.H_Index),'E_absdiff':abs(r.E_Index-c.E_Index),'IBSI_gap':r.IBSI-c.IBSI,'rms_ratio':r.V_RMS/c.V_RMS,'target_Q':r.Q_insar,'control_Q':c.Q_insar,'target_delta':r.delta_R_static_baseline,'control_delta':c.delta_R_static_baseline,'target_transition':r.transition,'control_transition':c.transition,'road_block':r.road_block_id,'district':r.district,'subdistrict':r.subdistrict})
 return pd.DataFrame(out)
