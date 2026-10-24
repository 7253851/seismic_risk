"""Refresh the 5.1 building table after the vulnerability and risk pipelines are rerun.

The Static-only baseline (V_static, H, E, R0 and its Jenks classes) does not depend
on InSAR and must be unchanged. InSAR-dependent fields are replaced from the current
vulnerability and risk GeoPackages, the IBSI decomposition is recomputed, and stale
derived columns from the original ablation export are dropped.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
TABLE = ROOT/'result/intermediate/12_insar_contribution/strict_ablation_full_40000.csv'
AUDIT = ROOT/'result/intermediate/12_insar_contribution/analysis_audit.json'
VULNERABILITY = ROOT/'result/vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg'
RISK = ROOT/'result/risk/scs_paper_method/building_risk.gpkg'
VULNERABILITY_CONFIG = ROOT/'project/code/Vulnerability/config.json'
STATIC = ['PGA_g', 'H_Index', 'E_Index', 'Exp_Final', 'Idx_Pop', 'Idx_Econ', 'SCI', 'BFOCI', 'BD_200m',
          'SCI_n', 'BFOCI_n', 'BD_n', 'V_static', 'PS_Count', 'PS_CohMn', 'PS_Cov', 'PS_Dens', 'PS_Q_OK',
          'Q_insar', 'Count_n', 'Dens_n', 'Coh_n', 'Cov_n', 'R0', 'Class0_Jenks']
INSAR_MARKERS = ('Risk_Final', 'Vul_Index', 'IBSI', 'V_raw', 'V_RMS', 'Tilt', 'DGI', 'T_anom',
                 'R_legacy', 'delta_', 'raw_amplification', 'R1_campus', 'V_Index', 'R_raw', 'Risk_Class', 'Vul_Class')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_table(path, layer):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as connection:
        frame = pd.read_sql_query(f'SELECT * FROM "{layer}"', connection)
    return frame.drop(columns=['fid', 'geom'], errors='ignore')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    old = pd.read_csv(TABLE, float_precision='round_trip', low_memory=False, encoding='utf-8-sig')
    vulnerability = read_table(VULNERABILITY, 'building_comprehensive_vulnerability')
    risk = read_table(RISK, 'building_risk_scs')
    current = risk.merge(vulnerability.drop(columns=[c for c in vulnerability if c in risk and c != 'Build_ID']),
                         on='Build_ID', validate='one_to_one')
    assert len(current) == 40000 and set(current.Build_ID) == set(old.Build_ID)
    new = old[['Build_ID']].merge(current, on='Build_ID', validate='one_to_one')

    unchanged = {}
    for column in STATIC:
        if column in new:
            unchanged[column] = float(np.nanmax(np.abs(new[column].to_numpy(float) - old[column].to_numpy(float))))
    assert all(error < 1e-12 for error in unchanged.values()), unchanged

    model = json.loads(VULNERABILITY_CONFIG.read_text())['model']
    base = new.Q_insar*new.V_RMS_n
    new['IBSI_base'] = base
    new['IBSI_tilt'] = base*float(model['beta_tilt'])*new.T_anom_n
    new['IBSI_DGI'] = base*float(model['gamma_dgi'])*new.DGI_n
    assert np.allclose((new.IBSI_base+new.IBSI_tilt+new.IBSI_DGI).clip(0, 1), new.IBSI, rtol=0, atol=1e-12)

    kept = [c for c in old if c in new or not any(m in c for m in INSAR_MARKERS)]
    for column in kept:
        if column not in new:
            new[column] = old[column]
    dropped = [c for c in old if c not in kept]
    new = new[kept]
    def differs(column):
        if not (pd.api.types.is_numeric_dtype(new[column]) and pd.api.types.is_numeric_dtype(old[column])):
            return not new[column].astype(str).equals(old[column].astype(str))
        return not np.allclose(new[column], old[column], equal_nan=True, rtol=0, atol=1e-12)
    changed = sorted(c for c in kept if c in current and differs(c))

    audit = json.loads(AUDIT.read_text())
    risk_breaks = pd.read_csv(RISK.parent/'risk_class_breaks.csv', encoding='utf-8-sig')
    quantiles = new[['V_RMS', 'Tilt_Angle', 'DGI_Str', 'IBSI']]
    v_raw = vulnerability.V_raw
    audit.update({
        'normalization_insar': [float(v_raw.quantile(.01)), float(v_raw.quantile(.99))],
        'deformation_p75': quantiles.quantile(.75).to_dict(),
        'deformation_p90': quantiles.quantile(.90).to_dict(),
        'refreshed_after_vertical_rate_fix': {
            'formula': 'v_vertical = v_los / cos(inc), inc in radians',
            'static_columns_max_abs_change': unchanged, 'insar_columns_changed': changed,
            'stale_columns_dropped': dropped},
        'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in [VULNERABILITY, RISK]},
    })
    audit['insar_breaks'] = [*map(float, risk_breaks.lower_break), float(risk_breaks.upper_break.iloc[-1])]
    for key in ['changed_n', 'up_n', 'down_n', 'max_uplift_steps', 'moderate_to_high_n', 'reliable_robust_uplift_n',
                'selected_upgrade_ids', 'selected_control_ids', 'selected_moderate_to_high_n', 'eligible_pairs_n',
                'selected_pairs_n', 'shortlist_n', 'output_row_counts', 'source_field_errors', 'checked_source_fields',
                'max_reconstruction_error']:
        audit.pop(key, None)
    print(json.dumps({'insar_columns_changed': changed, 'stale_columns_dropped': len(dropped),
                      'static_columns_unchanged': len(unchanged)}, ensure_ascii=False))
    if not args.check_only:
        new.to_csv(TABLE, index=False, encoding='utf-8-sig')
        AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
