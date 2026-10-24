"""Strict matched-pair selector used by the current frozen-baseline experiment."""
import numpy as np
import pandas as pd

def pair_search(d, max_control_ibsi=.15, min_rms_ratio=1.5, static_tolerance=.01):
    targets = d[d.screen_eligible & d.road_block_id.notna()]
    controls = d[d.reliable_ps & d.class_steps.eq(0)
                 & (d.IBSI <= max_control_ibsi) & d.road_block_id.notna()]
    pairs = []
    for _, t in targets.iterrows():
        pool = controls[controls.road_block_id.eq(t.road_block_id) & controls.static_class.eq(t.static_class)
                        & controls.subdistrict.eq(t.subdistrict) & controls.district.eq(t.district)].copy()
        if pool.empty:
            continue
        pool['distance_m'] = np.hypot(pool.centroid_x_utm48n_m-t.centroid_x_utm48n_m,
                                       pool.centroid_y_utm48n_m-t.centroid_y_utm48n_m)
        pool['static_risk_absdiff'] = abs(pool.R0-t.R0)
        pool['static_v_absdiff'] = abs(pool.V_static-t.V_static)
        pool['H_absdiff'] = abs(pool.H_Index-t.H_Index)
        pool['E_absdiff'] = abs(pool.E_Index-t.E_Index)
        pool['area_ratio'] = pool.Area_m2/t.Area_m2
        pool['height_ratio'] = pool.Height_m/t.Height_m
        pool['IBSI_gap'] = t.IBSI-pool.IBSI
        pool['RMS_ratio'] = t.V_RMS/pool.V_RMS
        pool = pool[(pool.distance_m <= 300) & (pool.static_risk_absdiff <= static_tolerance)
                    & (pool.static_v_absdiff <= .05) & (pool.H_absdiff <= .03) & (pool.E_absdiff <= .05)
                    & pool.area_ratio.between(.5, 2) & pool.height_ratio.between(.5, 2)
                    & (pool.IBSI_gap >= .1) & (pool.RMS_ratio >= min_rms_ratio)]
        for _, c in pool.iterrows():
            pairs.append({'target_id': int(t.Build_ID), 'control_id': int(c.Build_ID),
                          'target_transition': t.transition, 'control_transition': c.transition,
                          'district': t.district, 'subdistrict': t.subdistrict,
                          'road_block_id': t.road_block_id, 'road_block_area_m2': t.road_block_area_m2,
                          **{k: float(c[k]) for k in ['distance_m','static_risk_absdiff','static_v_absdiff',
                              'H_absdiff','E_absdiff','area_ratio','height_ratio','IBSI_gap','RMS_ratio']},
                          'target_risk_delta': t.risk_delta, 'control_risk_delta': c.risk_delta,
                          'target_IBSI': t.IBSI, 'control_IBSI': c.IBSI,
                          'target_RMS': t.V_RMS, 'control_RMS': c.V_RMS,
                          'target_Q': t.Q_insar, 'control_Q': c.Q_insar})
    return pd.DataFrame(pairs)
