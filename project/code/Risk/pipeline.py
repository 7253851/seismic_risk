#!/usr/bin/env python3
"""Calculate integrated building earthquake risk from current H, V and E outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR.parent))
from paths import DATA_ROOT, RESULT_ROOT, WORKSPACE_ROOT, resolve_path  # noqa: E402
from classification import jenks_breaks as shared_jenks_breaks, classify as shared_classify, JENKS_METHOD

CLASS_NAMES = ["Very Low", "Low", "Moderate", "High", "Very High"]


def fingerprint(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def minmax(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    low, high = float(x.min()), float(x.max())
    if not np.isfinite(low) or not np.isfinite(high) or np.isclose(low, high):
        return pd.Series(0.0, index=x.index, dtype=float)
    return ((x - low) / (high - low)).astype(float)


def read_layer(path: Path, layer: str) -> gpd.GeoDataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing workspace input: {path}")
    frame = gpd.read_file(path, layer=layer)
    if frame.empty or frame.crs is None:
        raise ValueError(f"Input is empty or has no CRS: {path} | {layer}")
    return frame


def clean_ids(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if "Build_ID" not in frame:
        raise KeyError(f"{name} is missing Build_ID")
    out = frame.copy()
    out["Build_ID"] = pd.to_numeric(out["Build_ID"], errors="coerce")
    if out["Build_ID"].isna().any() or out["Build_ID"].duplicated().any():
        raise ValueError(f"{name} must have unique, non-null Build_ID values")
    out["Build_ID"] = out["Build_ID"].astype("int64")
    return out


def jenks_breaks(values: pd.Series, classes: int = 5, max_values: int = 2000) -> list[float]:
    return shared_jenks_breaks(values, classes, max_values)


def classify(values: pd.Series, breaks: list[float]) -> pd.Series:
    return shared_classify(values, breaks)


def calculate(hazard: gpd.GeoDataFrame, vulnerability: gpd.GeoDataFrame, exposure: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, dict]:
    hazard = clean_ids(hazard, "hazard")
    vulnerability = clean_ids(vulnerability, "vulnerability")
    exposure = clean_ids(exposure, "exposure")
    conf = config["inputs"]
    required = {
        "hazard": conf["hazard"]["pga_field"],
        "vulnerability": conf["vulnerability"]["index_field"],
        "exposure": conf["exposure"]["index_field"],
    }
    for name, field in required.items():
        frame = {"hazard": hazard, "vulnerability": vulnerability, "exposure": exposure}[name]
        if field not in frame:
            raise KeyError(f"{name} input is missing {field}")
    id_sets = {name: set(frame.Build_ID) for name, frame in [("hazard", hazard), ("vulnerability", vulnerability), ("exposure", exposure)]}
    common = id_sets["hazard"] & id_sets["vulnerability"] & id_sets["exposure"]
    if not common:
        raise ValueError("Hazard, vulnerability and exposure have no common building IDs")

    h = hazard.loc[hazard.Build_ID.isin(common), ["Build_ID", required["hazard"]]].rename(columns={required["hazard"]: "PGA_g"})
    v_fields = ["Build_ID", required["vulnerability"]]
    if "Vul_Class" in vulnerability:
        v_fields.append("Vul_Class")
    v = pd.DataFrame(vulnerability[v_fields]).rename(columns={required["vulnerability"]: "Vul_Index"})
    e_fields = ["Build_ID", required["exposure"]]
    for field in ["Idx_Pop", "Idx_Econ", "Pop_Value", "Econ_Val", "Area_m2", "Height_m", "UnitPrice", "PriceFill"]:
        if field in exposure:
            e_fields.append(field)
    e = pd.DataFrame(exposure[e_fields]).rename(columns={required["exposure"]: "Exp_Final"})
    table = h.merge(v, on="Build_ID", how="inner", validate="one_to_one").merge(e, on="Build_ID", how="inner", validate="one_to_one")
    table = table.sort_values("Build_ID").reset_index(drop=True)
    for field in ["PGA_g", "Vul_Index", "Exp_Final"]:
        table[field] = pd.to_numeric(table[field], errors="coerce").replace([np.inf, -np.inf], np.nan)
    if table[["PGA_g", "Vul_Index", "Exp_Final"]].isna().any().any():
        raise ValueError("Common risk sample contains missing or non-finite H, V or E values")
    if (table["PGA_g"] < 0).any() or not table["Vul_Index"].between(0, 1).all() or not table["Exp_Final"].between(0, 1).all():
        raise ValueError("Risk inputs are outside their expected domains (PGA >= 0; V and E within [0,1])")
    table["H_Index"] = minmax(table["PGA_g"])
    table["V_Index"] = table["Vul_Index"].astype(float)
    table["E_Index"] = table["Exp_Final"].astype(float)
    table["R_raw"] = table["H_Index"] * table["V_Index"] * table["E_Index"]
    table["Risk_Final"] = minmax(table["R_raw"])
    breaks = jenks_breaks(table["Risk_Final"], int(config["model"]["risk_classes"]), int(config["model"]["jenks_quantile_representatives"]))
    table["Risk_Class"] = classify(table["Risk_Final"], breaks)
    if table.Risk_Class.eq("Invalid").any():
        raise ValueError(f"{int(table.Risk_Class.eq('Invalid').sum())} risk records were not assigned a Jenks class")
    geom = vulnerability.loc[vulnerability.Build_ID.isin(common), ["Build_ID", vulnerability.geometry.name]].copy()
    result = geom.merge(table, on="Build_ID", how="inner", validate="one_to_one")
    result = gpd.GeoDataFrame(result, geometry=vulnerability.geometry.name, crs=vulnerability.crs)
    result = result.sort_values("Build_ID").reset_index(drop=True)

    count_rows = []
    for name, ids in id_sets.items():
        count_rows.append({"dataset": name, "unique_building_ids": len(ids), "in_complete_risk_sample": len(ids & common), "excluded_from_risk_sample": len(ids - common)})
    count_rows.append({"dataset": "complete_risk_sample", "unique_building_ids": len(common), "in_complete_risk_sample": len(common), "excluded_from_risk_sample": 0})
    intersection = pd.DataFrame(count_rows)
    class_rows = []
    for i, label in enumerate(CLASS_NAMES):
        mask = result.Risk_Class.eq(label)
        class_rows.append({"risk_class": label, "lower_break": breaks[i], "upper_break": breaks[i + 1], "building_count": int(mask.sum()), "percentage": float(mask.mean() * 100)})
    class_frame = pd.DataFrame(class_rows)
    summary = {
        "hazard_buildings": int(len(hazard)),
        "vulnerability_buildings": int(len(vulnerability)),
        "exposure_buildings": int(len(exposure)),
        "complete_risk_buildings": int(len(result)),
        "pga_min_g": float(table.PGA_g.min()), "pga_max_g": float(table.PGA_g.max()),
        "hazard_index_min": float(table.H_Index.min()), "hazard_index_max": float(table.H_Index.max()),
        "vulnerability_index_mean": float(table.V_Index.mean()), "exposure_index_mean": float(table.E_Index.mean()),
        "risk_index_min": float(table.Risk_Final.min()), "risk_index_mean": float(table.Risk_Final.mean()),
        "risk_index_median": float(table.Risk_Final.median()), "risk_index_max": float(table.Risk_Final.max()),
        "jenks_breaks": breaks,
        "jenks_method": f"Dynamic-programming Jenks on up to {config['model']['jenks_quantile_representatives']:,} equally spaced probability-quantile representatives; breaks assigned to all observations.",
        "class_counts": {row["risk_class"]: row["building_count"] for row in class_rows},
    }
    return result, intersection, class_frame, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace only configured SCS risk outputs")
    args = parser.parse_args()
    config_path = SCRIPT_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    inputs = {key: resolve_path(value["path"]) for key, value in config["inputs"].items()}
    output_dir = resolve_path(config["outputs"]["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / config["outputs"]["risk"]
    files = [output_path, output_dir / "calculation_summary.json", output_dir / "run_manifest.json", output_dir / "sample_intersection.csv", output_dir / "risk_class_breaks.csv"]
    if not args.overwrite and any(path.exists() for path in files):
        raise FileExistsError(f"SCS risk output already exists; pass --overwrite to replace it: {output_dir}")

    started = time.time()
    print("[1/4] Reading the current SCS hazard, vulnerability and exposure outputs...", flush=True)
    hazard = read_layer(inputs["hazard"], config["inputs"]["hazard"]["layer"])
    vulnerability = read_layer(inputs["vulnerability"], config["inputs"]["vulnerability"]["layer"])
    exposure = read_layer(inputs["exposure"], config["inputs"]["exposure"]["layer"])
    print("[2/4] Intersecting building IDs and recalculating relative risk...", flush=True)
    result, intersection, class_frame, summary = calculate(hazard, vulnerability, exposure, config)
    print(f"    Complete H-V-E sample: {len(result):,}", flush=True)
    print("[3/4] Writing risk map and audit tables...", flush=True)
    result.to_file(output_path, layer="building_risk_scs", driver="GPKG", index=False)
    intersection.to_csv(output_dir / "sample_intersection.csv", index=False, encoding="utf-8-sig")
    class_frame.to_csv(output_dir / "risk_class_breaks.csv", index=False, encoding="utf-8-sig")
    summary["run_started_utc"] = datetime.fromtimestamp(started, timezone.utc).isoformat()
    summary["run_finished_utc"] = datetime.now(timezone.utc).isoformat()
    summary["method"] = "Risk_Final = minmax(minmax(PGA_g) * Vul_Index * Exp_Final); vulnerability and exposure are not renormalized at the intersection."
    (output_dir / "calculation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "method_reference": "manuscript/tex/manuscript.tex, Integrated risk and building identification; Supplementary_material.tex, Complete risk sample and five classes",
        "inputs": {key: fingerprint(path) for key, path in inputs.items()},
        "output": str(output_path), "output_rows": int(len(result)),
        "notes": ["Vulnerability and exposure indices are retained as already normalized on their own samples.", "PGA is min-max normalized over the complete common H-V-E risk sample.", "The vulnerability geometry is retained for the integrated building-level risk layer."],
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[4/4] Risk calculation complete.", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
