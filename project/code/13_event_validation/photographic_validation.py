"""Match all campus footprints without score filtering; evaluate user-confirmed cases."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from PIL import Image, ImageDraw
from shapely.affinity import rotate

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'result/validation/13_event_validation'
EVIDENCE = BASE / 'evidence'


def main():
    g = gpd.read_file(BASE / 'results/campus_boundary_scope.gpkg', layer='candidate_buildings_latest').to_crs(4543)
    matches = []
    for loc, name in [('CF01', 'yufe_south_candidate_map'), ('CF02', 'yufe_north_candidate_map'), ('NY02', 'ynau_candidate_map')]:
        im = np.array(Image.open(EVIDENCE / (name + '.png')).convert('RGB'))
        red = (im[:, :, 0] > 180) & (im[:, :, 1] < 65) & (im[:, :, 2] < 65)
        yy, xx = np.where(red)
        target = Image.fromarray(red[yy.min():yy.max()+1, xx.min():xx.max()+1].astype('uint8') * 255)
        a = np.array(target.resize((220, 220), Image.Resampling.NEAREST)) > 0
        # All footprints in the stated campus enter the search, irrespective of their scores.
        for _, f in g[g.location_id.eq(loc)].iterrows():
            best, angle_best = 0., 0.
            for angle in np.arange(-5, 5.1, .5):
                geometry = rotate(f.geometry, angle, origin='centroid')
                minx, miny, maxx, maxy = geometry.bounds
                mask = Image.new('1', (220, 220))
                draw = ImageDraw.Draw(mask)
                def pixels(coords):
                    return [((p[0]-minx)/(maxx-minx)*219, (maxy-p[1])/(maxy-miny)*219) for p in coords]
                for polygon in ([geometry] if geometry.geom_type == 'Polygon' else geometry.geoms):
                    draw.polygon(pixels(polygon.exterior.coords), fill=1)
                    for ring in polygon.interiors:
                        draw.polygon(pixels(ring.coords), fill=0)
                b = np.array(mask) > 0
                iou = float((a & b).sum() / (a | b).sum())
                if iou > best:
                    best, angle_best = iou, float(angle)
            matches.append(dict(location_id=loc, screenshot=name, Build_ID=int(f.Build_ID), shape_iou=best,
                                orientation_adjustment_degrees=angle_best))
    matches = pd.DataFrame(matches).sort_values(['location_id', 'shape_iou'], ascending=[True, False])
    matches.to_csv(EVIDENCE / 'screenshot_shape_matching_all_candidates.csv', index=False)
    winners = matches.groupby('location_id', sort=False).head(1).copy()
    print(matches.groupby('location_id', sort=False).head(3).to_string(index=False), flush=True)
    risk = gpd.read_file(ROOT / 'result/risk/scs_paper_method/building_risk.gpkg', layer='building_risk_scs')
    v = gpd.read_file(ROOT / 'result/vulnerability/scs_paper_method/01_building_vulnerability_metrics.gpkg', layer='building_vulnerability_metrics')
    final_v = gpd.read_file(ROOT / 'result/vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg', layer='building_comprehensive_vulnerability')
    low, high = final_v.V_static.quantile([.01, .99])
    final_v['V0'] = ((final_v.V_static.clip(low, high)-low)/(high-low)).clip(0,1)
    risk = risk.merge(v[['Build_ID', 'V_static', 'IBSI', 'F_IBSI', 'V_RMS', 'Tilt_Angle', 'DGI_Str', 'Q_insar']], on='Build_ID', validate='one_to_one')
    risk = risk.merge(final_v[['Build_ID','V0']],on='Build_ID',validate='one_to_one')
    risk['static_raw'] = risk.H_Index * risk.V0 * risk.E_Index
    for col, new in [('Risk_Final', 'corrected_risk_percentile'), ('static_raw', 'static_risk_percentile'),
                     ('V_static', 'static_V_percentile'), ('Vul_Index', 'corrected_V_percentile')]:
        risk[new] = (risk[col].rank(method='average') - .5) / len(risk) * 100
    risk['risk_percentile_change_pp'] = risk.corrected_risk_percentile - risk.static_risk_percentile
    risk['V_percentile_change_pp'] = risk.corrected_V_percentile - risk.static_V_percentile
    risk['IBSI_raw_amplification_pct'] = (risk.F_IBSI - 1) * 100
    result = risk[risk.Build_ID.isin(winners.Build_ID)].drop(columns='geometry').merge(winners, on='Build_ID', validate='one_to_one')
    result['photo_building_identity_status'] = 'confirmed_by_user_2026-10-16'
    result['ablation_method'] = 'alpha=0; identical final P1-P99 normalization on 41939; H/E fixed on 40000'
    result['damage_status'] = 'damaged_user_confirmed'
    result['reported_damage_grade'] = ['reported_slight_secondary_source' if loc != 'CF02' else 'grade_unknown_user_confirmed_damage' for loc in result.location_id]
    result['evidence_role'] = 'User confirmed damage evidence for all three screenshot buildings; footprint IDs matched by shape.'
    result.to_csv(BASE / 'results/photographic_candidate_comparison.csv', index=False, encoding='utf-8-sig')
    coordinates = g[g.Build_ID.isin(winners.Build_ID)][['Build_ID', 'geometry']].to_crs(4326)
    coordinates.geometry = coordinates.geometry.representative_point()
    coordinates['longitude'] = coordinates.geometry.x
    coordinates['latitude'] = coordinates.geometry.y
    result = result.merge(coordinates.drop(columns='geometry'), on='Build_ID')
    result.to_csv(BASE / 'discussion/data/photographic_candidates.csv', index=False, encoding='utf-8-sig')
    evidence = [
        dict(case_id='CF', source='kunming_earthquake_2026_09_report_4.pdf', pdf_page=7, observation='Teaching-building cantilever corridor: enclosure cracking/local loss and underside tile fall.',
             reported_grade='slight (provisional, secondary interpretation)', building_identity='confirmed by user', role='campus earthquake-damage case'),
        dict(case_id='NY', source='kunming_earthquake_2026_09_report_4.pdf', pdf_page=8, observation='Teaching-building stair-flight construction-joint cracking and surface spalling.',
             reported_grade='slight (secondary interpretation)', building_identity='confirmed by user', role='campus earthquake-damage case'),
        dict(case_id='JN', source='kunming_earthquake_2026_09_report_4.pdf', pdf_page=10, observation='Entrance pavement fissure attributed by the article to longstanding subsidence, not this event.',
             reported_grade='not assigned', building_identity='not applicable: pavement', role='attribution and coverage reference; excluded from earthquake positives')]
    pd.DataFrame(evidence).to_csv(BASE / 'discussion/data/evidence_register.csv', index=False, encoding='utf-8-sig')
    captures, capture_detail = [], []
    for fraction in (.1, .15, .2):
        k = int(round(len(risk) * fraction))
        static_ids = set(risk.sort_values(['static_raw', 'Build_ID'], ascending=[False, True]).head(k).Build_ID)
        corrected_ids = set(risk.sort_values(['Risk_Final', 'Build_ID'], ascending=[False, True]).head(k).Build_ID)
        old_n = sum(int(b) in static_ids for b in result.Build_ID)
        new_n = sum(int(b) in corrected_ids for b in result.Build_ID)
        captures.append(dict(screening_fraction=fraction, screening_buildings=k, known_damage_n=len(result),
                             static_captured_n=old_n, corrected_captured_n=new_n, static_capture_pct=old_n/len(result)*100,
                             corrected_capture_pct=new_n/len(result)*100, capture_change_pp=(new_n-old_n)/len(result)*100,
                             role='primary fixed budget' if fraction == .1 else 'budget sensitivity; no threshold selected by best result'))
        for _, row in result.iterrows():
            capture_detail.append(dict(Build_ID=row.Build_ID, screening_fraction=fraction,
                                       static_captured=int(row.Build_ID in static_ids), corrected_captured=int(row.Build_ID in corrected_ids)))
    pd.DataFrame(captures).to_csv(BASE/'discussion/data/screening_capture.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(capture_detail).to_csv(BASE/'discussion/data/screening_capture_by_building.csv',index=False,encoding='utf-8-sig')
    confirmed = g[g.Build_ID.isin(result.Build_ID)][['Build_ID','geometry']].merge(result.drop(columns=['longitude','latitude']),on='Build_ID',validate='one_to_one')
    confirmed.to_file(BASE/'discussion/data/confirmed_damage_buildings.gpkg',layer='confirmed_damage_buildings',driver='GPKG')
    audit = dict(method='Red footprint shape extraction and normalized-mask IoU; all campus candidates searched without score filtering.',
                 limitations=['IoU measures silhouette similarity, not model accuracy or photo-to-building confidence.',
                              'Screenshot locations and damage identities were confirmed by the user; this is not a field-survey audit.',
                              'North-campus damage is user confirmed, but no separate photograph or grade was supplied.',
                              'Red fill is a model classification. Damage labels come from user confirmation and reported photographs.',
                              'The three ascertained positives are not a random or complete damage census; no surveyed negative controls exist.'],
                 candidate_ids=result.Build_ID.tolist(), original_building_damage_labels_modified=False,
                 confirmed_positive_records_in_derived_experiment=3, independent_campuses=2, earthquake_events=1,
                 user_confirmation={'date':'2026-10-16','text':'已确认三个截图中的楼栋均有震害证据'},
                 current_high_risk_capture_n=int(result.Risk_Class.isin(['High','Very High']).sum()), known_positive_n=len(result),
                 overall_accuracy_precision_auc_specificity='not_estimable_from_current_evidence')
    (BASE / 'discussion/data/evidence_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(result[['location_id', 'Build_ID', 'Risk_Final', 'Risk_Class', 'IBSI', 'static_risk_percentile',
                  'corrected_risk_percentile', 'risk_percentile_change_pp', 'V_percentile_change_pp', 'IBSI_raw_amplification_pct']].to_string(index=False))


if __name__ == '__main__':
    main()
