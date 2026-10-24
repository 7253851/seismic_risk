#!/usr/bin/env python3
"""Recalculate building exposure from data and result using the current SCS method."""

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
from classification import jenks_breaks, classify, JENKS_METHOD


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


def validate_ids(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if "Build_ID" not in frame:
        raise KeyError(f"{name} is missing Build_ID")
    out = frame.copy()
    out["Build_ID"] = pd.to_numeric(out["Build_ID"], errors="coerce")
    if out["Build_ID"].isna().any() or out["Build_ID"].duplicated().any():
        raise ValueError(f"{name} must have unique, non-null Build_ID values")
    out["Build_ID"] = out["Build_ID"].astype("int64")
    return out


def calculate(population: gpd.GeoDataFrame, economic: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, model: dict) -> tuple[gpd.GeoDataFrame, dict]:
    population = validate_ids(population, "population")
    economic = validate_ids(economic, "economic")
    buildings = validate_ids(buildings, "building inventory")
    required_pop = ["Pop_Value"]
    required_econ = ["Area_m2", "Height_m", "UnitPrice", "PriceFill"]
    missing = [f"population.{f}" for f in required_pop if f not in population]
    missing += [f"economic.{f}" for f in required_econ if f not in economic]
    if missing:
        raise KeyError(f"Missing exposure input field(s): {missing}")
    if len(population) != len(buildings) or set(population.Build_ID) != set(buildings.Build_ID):
        raise ValueError("Prepared population records must cover the complete repaired building inventory")
    if population.crs != economic.crs or population.crs != buildings.crs:
        raise ValueError(f"Input CRS mismatch: population={population.crs}, economic={economic.crs}, buildings={buildings.crs}")
    if not set(economic.Build_ID).issubset(set(population.Build_ID)):
        raise ValueError("Economic input contains building IDs without a population record")

    econ_fields = ["Build_ID", "Area_m2", "Height_m", "UnitPrice", "PriceFill"]
    for field in ["HeightSrc", "HeightValid", "Height_Norm", "Height_Factor", "Econ_Area", "Econ_Val", "Function", "AvgPrice", "HasPrice", "PriceSrc"]:
        if field in economic.columns:
            econ_fields.append(field)
    geometry_field = buildings.geometry.name
    geometry = buildings[["Build_ID", geometry_field]].copy()
    population_table = pd.DataFrame(population[["Build_ID", "Pop_Value"]])
    result = geometry.merge(population_table, on="Build_ID", how="inner", validate="one_to_one")
    result = result.merge(pd.DataFrame(economic[econ_fields]), on="Build_ID", how="inner", validate="one_to_one")
    result = gpd.GeoDataFrame(result, geometry=geometry_field, crs=buildings.crs)
    pop = pd.to_numeric(result.Pop_Value, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0).clip(lower=0)
    area = pd.to_numeric(result.Area_m2, errors="coerce")
    height = pd.to_numeric(result.Height_m, errors="coerce")
    price = pd.to_numeric(result.UnitPrice, errors="coerce")
    if area.isna().any() or (area <= 0).any() or height.isna().any() or (height <= 0).any() or price.isna().any() or (price <= 0).any():
        raise ValueError("Retained economic inputs require positive area, height and unit price")

    p99 = float(height.quantile(0.99))
    height_cap = height.clip(upper=p99)
    height_log = np.log1p(height_cap)
    height_norm = minmax(height_log)
    alpha = float(model["height_alpha"])
    height_factor = 1.0 + alpha * height_norm
    econ_area = area * price
    econ_value = econ_area * height_factor
    pop_index = minmax(np.log1p(pop))
    econ_index = minmax(np.log1p(econ_value))
    weighted = float(model["population_weight"]) * pop_index + float(model["economic_weight"]) * econ_index
    exposure = minmax(weighted)

    result["Pop_Value"] = pop.astype(float)
    result["Area_m2"] = area.astype(float)
    result["Height_m"] = height.astype(float)
    result["Height_P99_Cap_m"] = height_cap.astype(float)
    result["Height_Norm"] = height_norm
    result["Height_Factor"] = height_factor
    result["UnitPrice"] = price.astype(float)
    result["Econ_Area"] = econ_area
    result["Econ_Val"] = econ_value
    result["Idx_Pop"] = pop_index
    result["Idx_Econ"] = econ_index
    result["Exp_Final"] = exposure
    breaks = jenks_breaks(result["Exp_Final"])
    result["Exposure_Class"] = classify(result["Exp_Final"], breaks)
    result = result.sort_values("Build_ID").reset_index(drop=True)
    summary = {
        "classification": JENKS_METHOD, "jenks_breaks": breaks,
        "inventory_buildings": int(len(buildings)),
        "population_buildings": int(len(population)),
        "economic_buildings_with_positive_height": int(len(economic)),
        "exposure_buildings": int(len(result)),
        "population_records_missing_economic_height": int(len(population) - len(result)),
        "matched_unit_price_count": int(result.get("PriceFill", pd.Series(index=result.index, dtype=object)).eq("matched").sum()),
        "function_median_price_count": int(result.get("PriceFill", pd.Series(index=result.index, dtype=object)).eq("function_median").sum()),
        "global_median_price_count": int(result.get("PriceFill", pd.Series(index=result.index, dtype=object)).eq("global_median").sum()),
        "height_p99_cap_m": p99,
        "height_alpha": alpha,
        "population_weight": float(model["population_weight"]),
        "economic_weight": float(model["economic_weight"]),
        "height_factor_min": float(height_factor.min()),
        "height_factor_max": float(height_factor.max()),
        "mean_population_index": float(pop_index.mean()),
        "mean_economic_index": float(econ_index.mean()),
        "mean_exposure_index": float(exposure.mean()),
        "median_exposure_index": float(exposure.median()),
        "zero_population_count": int((pop == 0).sum()),
    }
    return result, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace only configured SCS exposure outputs")
    args = parser.parse_args()
    config_path = SCRIPT_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    inputs = {key: resolve_path(value["path"]) for key, value in config["inputs"].items()}
    output_dir = resolve_path(config["outputs"]["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / config["outputs"]["exposure"]
    summary_path = output_dir / "calculation_summary.json"
    manifest_path = output_dir / "run_manifest.json"
    if not args.overwrite and any(p.exists() for p in [output_path, summary_path, manifest_path]):
        raise FileExistsError(f"SCS exposure output already exists; pass --overwrite to replace it: {output_dir}")

    started = time.time()
    print(f"[1/3] Reading prepared inputs from data and result: {inputs}", flush=True)
    population = read_layer(inputs["population"], config["inputs"]["population"]["layer"])
    economic = read_layer(inputs["economic"], config["inputs"]["economic"]["layer"])
    buildings = read_layer(inputs["buildings"], config["inputs"]["buildings"]["layer"])
    print("[2/3] Recomputing exposure components and final index...", flush=True)
    result, summary = calculate(population, economic, buildings, config["model"])
    result.to_file(output_path, layer="building_exposure_scs", driver="GPKG", index=False)
    summary["run_started_utc"] = datetime.fromtimestamp(started, timezone.utc).isoformat()
    summary["run_finished_utc"] = datetime.now(timezone.utc).isoformat()
    summary["method"] = "Current SCS manuscript exposure equations; population and economic components are log1p-minmax normalized; final weighted index is minmax normalized."
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    class_table = result["Exposure_Class"].value_counts().reindex(
        ["Very Low", "Low", "Moderate", "High", "Very High"], fill_value=0).rename_axis("exposure_class").rename("building_count").reset_index()
    class_table["lower_break"] = summary["jenks_breaks"][:-1]
    class_table["upper_break"] = summary["jenks_breaks"][1:]
    class_table["percentage"] = class_table["building_count"] / len(result) * 100
    class_table.to_csv(output_dir / "exposure_class_breaks.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "method_reference": "manuscript/tex/manuscript.tex, Building exposure; Supplementary_material.tex, Exposure, sample intersection and risk classification",
        "inputs": {key: fingerprint(path) for key, path in inputs.items()},
        "output": str(output_path),
        "output_rows": int(len(result)),
        "classification": JENKS_METHOD,
        "jenks_breaks": summary["jenks_breaks"],
        "notes": [
            "Prepared population and economic component layers were migrated from earlier preprocessing outputs into result/intermediate/exposure_inputs; source fingerprints record their provenance.",
            "The repaired building inventory supplies output geometries to ensure valid mapped footprints; population and economic values are joined by Build_ID.",
            "No absolute loss interpretation is assigned to Econ_Val because source currency and price-area units remain unverified.",
            "Population values retain the building-level assignment from the prepared 100 m grid; provenance of that intermediate grid remains to be confirmed.",
            "Only positive-height buildings enter the exposure sample, following the retained manuscript sample definition.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[3/3] Exposure calculation complete.", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
