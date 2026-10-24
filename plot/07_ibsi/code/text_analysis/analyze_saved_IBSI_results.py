#!/usr/bin/env python3
"""Descriptive analysis of saved fields only; never imports assessment models."""
import os
os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/ibsi-mpl")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
from pathlib import Path
import hashlib
import json
import sqlite3
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from scipy.stats import skew

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "plot/07_ibsi/output/text_analysis"
SOURCE = ROOT / "result/vulnerability/scs_paper_method/01_building_vulnerability_metrics.gpkg"
DISTRICTS = ROOT / "data/administrative/kunming_districts.shp"

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(2**20), b""):
            h.update(b)
    return h.hexdigest()

def read_saved():
    with sqlite3.connect(SOURCE.as_uri() + "?mode=ro", uri=True) as con:
        table = "building_vulnerability_metrics"
        geom, srid = con.execute("SELECT column_name,srs_id FROM gpkg_geometry_columns WHERE table_name=?", (table,)).fetchone()
        data = pd.read_sql_query(f'SELECT * FROM "{table}" ORDER BY Build_ID', con)
    def wkb(b):
        size = {0:0, 1:32, 2:48, 3:48, 4:64}[(b[3] >> 1) & 7]
        return b[8 + size:]
    geometry = shapely.from_wkb([wkb(b) for b in data.pop(geom)])
    return gpd.GeoDataFrame(data, geometry=geometry, crs=f"EPSG:{srid}")

def summary(x):
    x = np.asarray(x, float)
    return {"N":len(x), "mean":float(x.mean()), "sample_sd":float(x.std(ddof=1)),
            "min":float(x.min()), "max":float(x.max()),
            "skewness_bias_corrected":float(skew(x, bias=False)),
            **{f"P{p:02d}":float(np.quantile(x,p/100)) for p in [25,50,75,90,95,99]}}

def main():
    hashes = {str(SOURCE):digest(SOURCE)}
    hashes.update({str(p):digest(p) for p in DISTRICTS.parent.glob(DISTRICTS.stem + ".*")})
    all_b = read_saved()
    b = all_b.loc[all_b.Vul_Valid.eq(1)].copy()
    assert len(all_b)==57228 and len(b)==41939 and b.Build_ID.is_unique
    fields = ["V_RMS", "Tilt_Angle", "Tilt_Grad", "DGI_Str", "IBSI", "Q_insar", "F_IBSI", "V_RMS_n", "T_anom_n", "DGI_n"]
    assert np.isfinite(b[fields].to_numpy(float)).all()
    stats = {f:summary(b[f]) for f in fields}
    limits = {f:float(b[f].quantile(.9)) for f in ["V_RMS", "Tilt_Angle", "DGI_Str", "IBSI"]}
    high = {f:b[f].gt(t) for f,t in limits.items()}
    high_ibsi = high["IBSI"]
    intersection = int((high_ibsi & high["V_RMS"]).sum())
    union = int((high_ibsi | high["V_RMS"]).sum())
    overlap = {"definition":"strictly above each saved cohort's P90; no damage/risk classification",
               "thresholds":limits,"IBSI_high_N":int(high_ibsi.sum()),
               "RMS_high_N":int(high["V_RMS"].sum()),"intersection_N":intersection,
               "intersection_share_of_high_IBSI_pct":intersection/int(high_ibsi.sum())*100,
               "high_IBSI_not_RMS_top_decile_N":int((high_ibsi & ~high["V_RMS"]).sum()),
               "jaccard":intersection/union}
    threshold_counts=[]
    for field,thresholds in {"V_RMS":[3,5,10], "DGI_Str":[.3,.6,1.2], "IBSI":[.1,.2,.3,.4]}.items():
        for t in thresholds:
            n=int(b[field].gt(t).sum())
            threshold_counts.append({"field":field,"threshold":t,"operator":">","N":n,"percent":n/len(b)*100})
    correlations=b[["IBSI","V_RMS","Tilt_Angle","DGI_Str","Q_insar"]].corr(method="spearman")
    correlations.to_csv(OUT/"spearman_correlations.csv")
    districts=gpd.read_file(DISTRICTS).to_crs(all_b.crs)
    representatives=gpd.GeoDataFrame(all_b[["Build_ID","Vul_Valid"]],geometry=all_b.geometry.representative_point(),crs=all_b.crs)
    join=gpd.sjoin(representatives,districts[["name","geometry"]],how="left",predicate="within")
    duplicate_ids=join.loc[join.Build_ID.duplicated(False),"Build_ID"].unique()
    assert len(duplicate_ids)==0, "Ambiguous administrative assignments; do not double-count"
    assigned=join.set_index("Build_ID")["name"]
    b["district"]=b.Build_ID.map(assigned)
    all_b["district"]=all_b.Build_ID.map(assigned)
    district_rows=[]
    for name,group in b.groupby("district",dropna=False):
        n_high=int(group.IBSI.gt(limits["IBSI"]).sum())
        district_rows.append({"district":str(name),"valid_N":len(group),
                              "inventory_N":int(all_b.district.eq(name).sum()) if pd.notna(name) else int(all_b.district.isna().sum()),
                              "IBSI_mean":float(group.IBSI.mean()),"IBSI_median":float(group.IBSI.median()),
                              "IBSI_P90":float(group.IBSI.quantile(.9)),
                              "IBSI_above_global_P90_N":n_high,
                              "IBSI_above_global_P90_within_district_percent":n_high/len(group)*100,
                              "share_of_all_high_IBSI_percent":n_high/int(high_ibsi.sum())*100})
    district_rows.sort(key=lambda r:r["IBSI_above_global_P90_within_district_percent"],reverse=True)
    pd.DataFrame(district_rows).to_csv(OUT/"district_IBSI_summary.csv",index=False)
    # These summarize existing saved modifier/normalization fields. No new
    # factor or metric is calculated and no assessment model is run.
    anomalies={"tilt_enhancement_active_N":int(b.T_anom_n.gt(0).sum()),
               "DGI_enhancement_active_N":int(b.DGI_n.gt(0).sum()),
               "either_enhancement_active_N":int((b.T_anom_n.gt(0)|b.DGI_n.gt(0)).sum()),
               "both_enhancement_active_N":int((b.T_anom_n.gt(0)&b.DGI_n.gt(0)).sum())}
    factor_pct=(b.F_IBSI.to_numpy(float)-1)*100
    factor_summary=summary(factor_pct)
    factor_summary["definition"]="Per-building relative increase in pre-final-normalization vulnerability, read from saved F_IBSI; percent. Not the change in final normalized Vul_Index."
    result={"source":str(SOURCE),"district_source":str(DISTRICTS),
            "inventory_N":len(all_b),"valid_N":len(b),"valid_share_percent":len(b)/len(all_b)*100,
            "statistics":stats,"threshold_counts":threshold_counts,
            "IBSI_RMS_top_decile_overlap":overlap,
            "spearman_IBSI":correlations.loc["IBSI"].to_dict(),
            "district_assignment":{"method":"polygon interior representative point within district; common full saved valid cohort, including 101 outside fixed figure frame",
                                   "unmatched_inventory_N":int(all_b.district.isna().sum()),"unmatched_valid_N":int(b.district.isna().sum()),"ambiguous_ID_N":0},
            "districts":district_rows,"saved_enhancement_fields":anomalies,
            "saved_F_IBSI_relative_correction_percent":factor_summary,
            "analysis_scope":"Read-only summaries of saved results; no model import, fitting, normalization, imputation, reclassification or source write",
            "sources_sha256":hashes}
    assert all(digest(Path(p))==h for p,h in hashes.items())
    (OUT/"IBSI_results_analysis_summary.json").write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))

if __name__=="__main__":
    main()
