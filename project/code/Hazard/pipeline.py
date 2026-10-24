"""Executable SCS hazard workflow, adapted from the original six base scripts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classification import jenks_breaks, classify, CLASS_NAMES, JENKS_METHOD

import common
from common import (Context, WORKSPACE_ROOT, building_keys, fingerprint,
                    inventory_normalize, read_vector, write_csv, write_json,
                    write_vector)
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from dbfread import DBF
from rasterio.transform import from_origin, rowcol
from shapely.geometry import LineString
from model import distance_proxy, predict_pga

ATTRIBUTES = ["FZN_Ch", "FZN_En", "FN_Ch", "FN_En", "FSN_Ch", "FSN_En",
              "Fea_Ch", "Fea_En", "AGE", "AGE_Des", "RefE"]
FILES = {
    1: ["01_fault_traces.gpkg"],
    2: ["02_fault_scenarios.gpkg", "02_scenario_registry.csv"],
    3: ["03_vs30.tif"],
    4: ["04_buildings_vs30.gpkg"],
    5: ["05_building_pga_matrix.csv"],
    6: ["06_building_hazard.gpkg", "06_building_hazard_attributes.csv", "pga_class_breaks.csv"],
    7: ["07_validation_report.json"],
}
STATISTICS_FILES = {7: ["scenario_statistics.csv"]}


def convert_faults(ctx):
    """Base step01; retain original attributes and source feature order."""
    features, coordinates, attrs = [], [], {}

    def append():
        if len(coordinates) >= 2:
            row = {name: attrs.get(name, "") for name in ATTRIBUTES}
            row["source_trace_id"] = len(features)
            row["geometry"] = LineString(coordinates)
            features.append(row)

    with ctx.input("faults").open(encoding=ctx.config["inputs"]["faults"]["encoding"]) as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                append()
                coordinates, attrs = [], {}
            elif line.startswith("# @D"):
                values = [p.strip().strip('"') for p in line[4:].strip().split("|")]
                attrs = dict(zip(ATTRIBUTES, values))
            elif not line.startswith(("#", "@")):
                try:
                    x, y = map(float, line.split()[:2])
                except ValueError as exc:
                    raise ValueError(f"Malformed GMT coordinate at line {number}") from exc
                if not np.isfinite([x, y]).all() or not (-180 <= x <= 180 and -90 <= y <= 90):
                    raise ValueError(f"Invalid GMT coordinate at line {number}")
                coordinates.append((x, y))
    append()
    if not features:
        raise ValueError("No fault traces found")
    faults = gpd.GeoDataFrame(features, crs="EPSG:4326")
    faults["FaultName"] = faults.apply(
        lambda r: next((r[k] for k in ("FN_Ch", "FN_En", "FZN_Ch", "FZN_En")
                        if str(r[k]).strip()), "Unnamed_Fault"), axis=1)
    write_vector(faults, ctx.file(FILES[1][0]), "fault_traces")
    ctx.report(1, {"trace_count": len(faults), "source": str(ctx.input("faults"))})


def strike_angle(geometry):
    if geometry.geom_type == "MultiLineString":
        geometry = max(geometry.geoms, key=lambda g: g.length)
    coords = list(geometry.coords)
    dx, dy = coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1]
    return float(np.degrees(np.arctan2(dy, dx)) % 180.)


def prepare_scenarios(ctx):
    """S1.1: propagate names, dissolve, measure complete lines, cap, select."""
    model = ctx.model
    faults = read_vector(ctx.file(FILES[1][0]), {"LineString", "MultiLineString"},
                         model["distance_crs"])
    faults["_strike"] = faults.geometry.map(strike_angle)
    names = faults["FN_En"].fillna("").astype(str)
    faults["FN_En"] = names
    named = set(faults.index[names.str.strip().ne("")])
    unnamed = set(faults.index[names.str.strip().eq("")])
    rounds = []
    for number in range(model["name_join_iterations"]):
        if not unnamed or not named:
            break
        candidates = faults.loc[sorted(named)]
        index = candidates.sindex
        changes = {}
        for idx in sorted(unnamed):
            geom = faults.at[idx, "geometry"]
            positions = index.query(geom.buffer(model["name_join_distance_m"]), predicate="intersects")
            nearby = candidates.iloc[positions].copy()
            if nearby.empty:
                continue
            nearby["_distance"] = nearby.geometry.distance(geom)
            diff = abs(nearby["_strike"] - faults.at[idx, "_strike"])
            diff = np.minimum(diff, 180. - diff)
            nearby = nearby[(nearby["_distance"] <= model["name_join_distance_m"])
                            & (diff <= model["name_join_angle_deg"])]
            if not nearby.empty:
                # Stable source-trace order only breaks exact distance ties.
                best = nearby.sort_index().sort_values("_distance", kind="stable").iloc[0]
                changes[idx] = best["FN_En"]
        rounds.append({"iteration": number + 1, "assigned": len(changes)})
        print(f"  name propagation {number + 1}: {len(changes)}", flush=True)
        if not changes:
            break
        for idx, name in changes.items():
            faults.at[idx, "FN_En"] = name
        named.update(changes)
        unnamed.difference_update(changes)

    faults = faults.drop(columns="_strike")
    mask = faults.FN_En.str.strip().ne("")
    parts = []
    if mask.any():
        parts.append(faults[mask].dissolve(by="FN_En", as_index=False, sort=True))
    if (~mask).any():
        parts.append(faults[~mask])
    scenarios = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True),
                                 crs=faults.crs)
    scenarios["merged_source_id"] = np.arange(len(scenarios))
    scenarios["Length_km"] = scenarios.geometry.length / 1000.
    if (scenarios.Length_km <= 0).any():
        raise ValueError("Non-positive scenario length")
    scenarios["Mw_unbounded"] = 5.08 + 1.16 * np.log10(scenarios.Length_km)
    scenarios["Mw"] = scenarios.Mw_unbounded
    scenarios["Mw_cap"] = np.nan
    for pattern, cap in model["magnitude_caps"].items():
        selected = scenarios.FN_En.str.contains(pattern, case=False, regex=False)
        scenarios.loc[selected, "Mw_cap"] = cap
        scenarios.loc[selected, "Mw"] = np.minimum(scenarios.loc[selected, "Mw"], cap)
    scenarios["FaultName"] = scenarios.FN_En
    area = read_vector(ctx.input("study_area"), {"Polygon", "MultiPolygon"},
                       model["distance_crs"])
    buffer = area.geometry.union_all().buffer(model["study_buffer_km"] * 1000.)
    scenarios = scenarios[scenarios.geometry.intersects(buffer)].reset_index(drop=True)
    if scenarios.empty:
        raise ValueError("No fault scenarios intersect the study buffer")
    # S1 IDs refer to the row order of the retained original shapefile.
    scenarios["scenario_id"] = np.arange(len(scenarios), dtype=int)
    scenarios["matrix_name"] = [str(name).strip() or f"Fault_{idx}"
                                 for idx, name in zip(scenarios.scenario_id, scenarios.FaultName)]
    wkb = scenarios.geometry.to_wkb()
    scenarios["duplicate_geometry"] = wkb.duplicated(keep=False)
    scenarios["is_length_extrapolated"] = ~scenarios.Length_km.between(1.3, 432.)
    scenarios["is_mw_out_of_range"] = ~scenarios.Mw.between(4.2, 7.9)
    scenarios["is_mechanism_extrapolated"] = ~scenarios.Mw.between(4.2, 6.1)
    # Mechanisms are the SCS screening assumption, not a reinterpretation of Fea_En.
    scenarios["adopted_mechanism"] = "strike-slip"
    write_vector(scenarios, ctx.file(FILES[2][0]), "fault_scenarios")
    registry = scenarios.drop(columns="geometry")
    write_csv(registry, ctx.file(FILES[2][1]))
    ctx.report(2, {"scenario_count": len(scenarios), "propagation": rounds,
                   "duplicate_geometry_ids": scenarios.loc[scenarios.duplicate_geometry, "scenario_id"].tolist(),
                   "length_extrapolated_ids": scenarios.loc[scenarios.is_length_extrapolated, "scenario_id"].tolist(),
                   "overall_mw_extrapolated_ids": scenarios.loc[scenarios.is_mw_out_of_range, "scenario_id"].tolist(),
                   "mechanism_extrapolated_ids": scenarios.loc[scenarios.is_mechanism_extrapolated, "scenario_id"].tolist(),
                   "geometry_policy": "entire scenario; no clipping or deduplication"})


def dbf_numeric_chunks(path, fields, chunk_size):
    """Bounded-memory reader for numeric DBF fields; respects deleted records.

    This yields original record order, matching direct point-to-cell assignment
    in base step03, without materializing the 13.8-million-record national table.
    """
    table = DBF(str(path), load=False)
    offset, offsets, widths = 1, {}, {}
    for field in table.fields:
        if field.name in fields:
            if field.type not in ("N", "F"):
                raise ValueError(f"DBF field {field.name} must be numeric")
            offsets[field.name], widths[field.name] = offset, field.length
        offset += field.length
    if set(fields) != set(offsets):
        raise KeyError(f"Missing DBF fields: {set(fields) - set(offsets)}")
    dtype = np.dtype({"names": ["_deleted", *fields],
                      "formats": ["S1", *(f"S{widths[k]}" for k in fields)],
                      "offsets": [0, *(offsets[k] for k in fields)],
                      "itemsize": table.header.recordlen})
    with Path(path).open("rb") as handle:
        handle.seek(table.header.headerlen)
        remaining = table.header.numrecords
        while remaining:
            count = min(remaining, chunk_size)
            raw = np.fromfile(handle, dtype=dtype, count=count)
            if len(raw) != count:
                raise ValueError("Truncated DBF records")
            raw = raw[raw["_deleted"] != b"*"]
            values = {}
            for name in fields:
                column = np.char.strip(raw[name])
                values[name] = np.where(column == b"", b"nan", column).astype(float)
            yield values
            remaining -= count


def create_vs30_raster(ctx):
    """S1.3.1: 30-arcsec geographic grid, bbox+0.1°, no interpolation."""
    m = ctx.model
    bounds = read_vector(ctx.input("study_area"), {"Polygon", "MultiPolygon"},
                         "EPSG:4326").total_bounds
    minx, miny, maxx, maxy = bounds + np.array([-1., -1., 1., 1.]) * m["vs30_buffer_deg"]
    resolution = m["vs30_resolution_deg"]
    width, height = int(np.ceil((maxx - minx) / resolution)), int(np.ceil((maxy - miny) / resolution))
    grid = np.full((height, width), -9999., dtype=np.float32)
    filled = np.zeros(grid.shape, dtype=bool)
    spec = ctx.config["inputs"]["vs30"]
    lon, lat, value = [spec[k] for k in ("longitude_field", "latitude_field", "value_field")]
    records, selected, collisions = 0, 0, 0
    for chunk in dbf_numeric_chunks(ctx.input("vs30"), [lon, lat, value], m["dbf_chunk_size"]):
        x, y, v = chunk[lon], chunk[lat], chunk[value]
        records += len(x)
        keep = (np.isfinite(x) & np.isfinite(y) & np.isfinite(v)
                & (x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy))
        rows = np.clip(((maxy - y[keep]) / resolution).astype(int), 0, height - 1)
        cols = np.clip(((x[keep] - minx) / resolution).astype(int), 0, width - 1)
        pairs = rows * width + cols
        collisions += int(len(pairs) - len(np.unique(pairs)) + filled.ravel()[np.unique(pairs)].sum())
        # Same explicit last-source-record rule as the base script.
        grid[rows, cols] = v[keep]
        filled[rows, cols] = True
        selected += int(keep.sum())
        if records % 2000000 < m["dbf_chunk_size"]:
            print(f"  Vs30 national records scanned: {records:,}", flush=True)
    if not filled.any():
        raise ValueError("No Vs30 points in the study bounding box")
    path = ctx.file(FILES[3][0])
    temp = path.with_name(f".{path.stem}.{os.getpid()}.tif")
    with rasterio.open(temp, "w", driver="GTiff", height=height, width=width,
                       count=1, dtype="float32", crs="EPSG:4326", nodata=-9999.,
                       transform=from_origin(minx, maxy, resolution, resolution)) as dst:
        dst.write(grid, 1)
    os.replace(temp, path)
    ctx.report(3, {"source_records": records, "selected_records": selected,
                   "occupied_cells": int(filled.sum()), "cell_collisions": collisions,
                   "assignment": "last source record wins; no interpolation",
                   "origin": [float(minx), float(maxy)], "width": width, "height": height,
                   "resolution_deg": resolution, "study_area": fingerprint(ctx.input("study_area"))})


def prepare_vs30(raw, minimum=140., maximum=1130.):
    raw = np.asarray(raw, dtype=float)
    missing = ~np.isfinite(raw) | (raw <= 0)
    if missing.all():
        raise ValueError("No finite positive Vs30 samples; cannot define an imputation median")
    median = float(np.median(raw[~missing]))
    filled = np.where(missing, median, raw)
    used = np.clip(filled, minimum, maximum)
    return filled, used, missing, (used != filled), median


def sample_building_vs30(ctx):
    """Base step04 with raw samples and sampling-stage flags retained."""
    buildings = read_vector(ctx.input("buildings"), {"Polygon", "MultiPolygon"},
                            ctx.model["distance_crs"], allow_invalid=True)
    buildings["building_id"] = building_keys(buildings, ctx.id_field)
    centers = buildings.geometry.centroid
    with rasterio.open(ctx.file(FILES[3][0])) as src:
        if src.crs is None:
            raise ValueError("Vs30 raster has no CRS")
        points = centers.to_crs(src.crs)
        # floor, rather than truncation toward zero, correctly rejects points
        # just outside the north/west border.
        rows, cols = rowcol(src.transform, points.x.to_numpy(), points.y.to_numpy())
        rows, cols = np.asarray(rows), np.asarray(cols)
        inside = (rows >= 0) & (rows < src.height) & (cols >= 0) & (cols < src.width)
        raster = src.read(1, masked=True)
        raw = np.full(len(buildings), np.nan)
        samples = raster[rows[inside], cols[inside]].filled(np.nan)
        raw[inside] = samples
        status = np.full(len(buildings), "out_of_raster", dtype=object)
        status[inside] = "valid"
        status[inside & ~np.isfinite(raw)] = "nodata_or_nonfinite"
        status[inside & np.isfinite(raw) & (raw <= 0)] = "nonpositive"
    filled, _, imputed, _, median = prepare_vs30(raw)
    buildings["Vs30_raw"] = raw
    buildings["Vs30"] = filled
    buildings["Vs30_sample_imputed"] = imputed
    buildings["Vs30_sample_status"] = status
    write_vector(buildings, ctx.file(FILES[4][0]), "buildings_vs30")
    ctx.report(4, {"building_count": len(buildings), "id_field": ctx.id_field,
                   "imputed_count": int(imputed.sum()), "median_vs30": median,
                   "raw_valid_min": float(np.nanmin(raw[~imputed])),
                   "raw_valid_max": float(np.nanmax(raw[~imputed])),
                   "sampling_status_counts": pd.Series(status).value_counts().to_dict(),
                   "sampling_location": "centroid in the metric CRS, transformed to the raster CRS"})


def calculate_scenario_pga(ctx):
    """Base step05 and S1 Eqs. S2–S9, with explicit scenario/provenance flags."""
    m = ctx.model
    buildings = read_vector(ctx.file(FILES[4][0]), {"Polygon", "MultiPolygon"},
                            m["distance_crs"], allow_invalid=True)
    ids = building_keys(buildings, "building_id")
    faults = read_vector(ctx.file(FILES[2][0]), {"LineString", "MultiLineString"}, m["distance_crs"])
    if not faults.scenario_id.is_unique:
        raise ValueError("Duplicate scenario IDs")
    raw = pd.to_numeric(buildings.Vs30_raw, errors="coerce").to_numpy()
    filled, used, imputed, clipped, median = prepare_vs30(raw, *m["vs30_range"])
    original_flags = buildings.Vs30_sample_imputed.astype(bool).to_numpy()
    imputed |= original_flags
    path = ctx.file(FILES[5][0])
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    rows_written = 0
    try:
        for number, fault in enumerate(faults.itertuples(), 1):
            distance = buildings.geometry.distance(fault.geometry).to_numpy() / 1000.
            rrup_raw, rrup = distance_proxy(distance, m["equivalent_depth_km"], m["rrup_range_km"][0])
            pga, terms = predict_pga(fault.Mw, rrup, used)
            frame = pd.DataFrame({
                "building_id": ids.to_numpy(), "scenario_id": int(fault.scenario_id),
                "fault_name": fault.matrix_name, "fault_length_km": fault.Length_km,
                "Mw": fault.Mw, "Mw_unbounded": fault.Mw_unbounded,
                "fault_distance_km": distance, "Rrup_raw_km": rrup_raw, "Rrup_used_km": rrup,
                "Vs30_raw": raw, "Vs30_preclip": filled, "Vs30_used": used,
                "PGA_Zhang2022_g": pga, "PGA_g": pga, **terms,
                "is_mw_out_of_range": bool(fault.is_mw_out_of_range),
                "is_mechanism_extrapolated": bool(fault.is_mechanism_extrapolated),
                "is_length_extrapolated": bool(fault.is_length_extrapolated),
                "is_rrup_out_of_range": (rrup_raw < m["rrup_range_km"][0]) | (rrup_raw > m["rrup_range_km"][1]),
                "is_vs30_imputed": imputed, "is_vs30_clipped": clipped,
                "gmpe_model": "SCS_Zhang2022_zero_site_reference",
            })
            frame.to_csv(temp, mode="w" if number == 1 else "a", header=number == 1,
                         index=False, encoding="utf-8-sig" if number == 1 else "utf-8")
            rows_written += len(frame)
            print(f"  PGA scenario {number}/{len(faults)}: {fault.matrix_name}", flush=True)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    ctx.report(5, {"buildings": len(buildings), "scenarios": len(faults),
                   "matrix_rows": rows_written, "vs30_median": median,
                   "vs30_imputed_buildings": int(imputed.sum()),
                   "vs30_clipped_buildings": int(clipped.sum()),
                   "site_reference": m["site_reference"], "pga_units": "g",
                   "distance_geometry": "building polygon to entire fault trace"})


def read_envelope(path, chunk_size):
    """S1.4's original chunk tie policy, now with an explicit scenario ID."""
    best = pd.DataFrame()
    fields = ["building_id", "scenario_id", "fault_name", "Mw", "Rrup_used_km", "Vs30_used",
              "PGA_Zhang2022_g", "is_mechanism_extrapolated", "is_mw_out_of_range",
              "is_rrup_out_of_range", "is_vs30_imputed", "is_vs30_clipped", "gmpe_model"]
    for chunk in pd.read_csv(path, chunksize=chunk_size, usecols=fields, dtype={"building_id": str}):
        chunk["PGA_Zhang2022_g"] = pd.to_numeric(chunk.PGA_Zhang2022_g, errors="coerce")
        valid = np.isfinite(chunk.PGA_Zhang2022_g) & (chunk.PGA_Zhang2022_g >= 0)
        chunk = chunk[valid]
        if chunk.empty:
            continue
        candidate = chunk.loc[chunk.groupby("building_id", sort=False).PGA_Zhang2022_g.idxmax()]
        combined = pd.concat([best, candidate.set_index("building_id")])
        combined = combined.sort_values("PGA_Zhang2022_g", kind="stable")
        best = combined[~combined.index.duplicated(keep="last")]
    if best.empty:
        raise ValueError("No valid finite nonnegative PGA values")
    return best.rename(columns={"PGA_Zhang2022_g": "PGA_Final_g", "scenario_id": "Dom_Scenario",
                                "fault_name": "Dom_Fault", "Mw": "Dom_Mw", "Rrup_used_km": "Dom_Rrup",
                                "Vs30_used": "Dom_Vs30", "gmpe_model": "Dom_Model"})


def create_envelope(ctx):
    buildings = read_vector(ctx.file(FILES[4][0]), {"Polygon", "MultiPolygon"},
                            ctx.model["distance_crs"], allow_invalid=True)
    buildings["building_id"] = building_keys(buildings, "building_id")
    best = read_envelope(ctx.file(FILES[5][0]), ctx.model["csv_chunk_size"])
    if set(best.index) != set(buildings.building_id):
        raise ValueError("Envelope building IDs do not exactly match the input inventory")
    final = buildings.join(best, on="building_id")
    final["PGA_Final"] = final.PGA_Final_g
    breaks = jenks_breaks(final.PGA_Final_g)
    final["PGA_Class"] = classify(final.PGA_Final_g, breaks)
    counts = final.PGA_Class.value_counts().reindex(CLASS_NAMES, fill_value=0)
    write_csv(pd.DataFrame({"PGA_Class": CLASS_NAMES, "lower_break": breaks[:-1], "upper_break": breaks[1:], "Building_Count": counts.to_numpy(), "Percentage": counts.to_numpy() / len(final) * 100}), ctx.file("pga_class_breaks.csv"))
    final["Hazard_Norm"], parameters = inventory_normalize(final.PGA_Final_g)
    write_vector(final, ctx.file(FILES[6][0]), "building_hazard")
    fields = ["building_id", ctx.id_field, "PGA_Final", "PGA_Final_g", "Hazard_Norm", "PGA_Class",
              "Dom_Scenario", "Dom_Fault", "Dom_Mw", "Dom_Rrup", "Dom_Vs30", "Dom_Model",
              "is_mechanism_extrapolated", "is_mw_out_of_range", "is_rrup_out_of_range",
              "is_vs30_imputed", "is_vs30_clipped"]
    write_csv(final[list(dict.fromkeys(fields))], ctx.file(FILES[6][1]))
    ctx.report(6, {"buildings": len(final), "normalization": parameters,
                   "classification": JENKS_METHOD, "jenks_breaks": breaks,
                   "dominant_scenarios": {str(k): int(v) for k, v in final.Dom_Scenario.value_counts().items()},
                   "mechanism_extrapolated_envelopes": int(final.is_mechanism_extrapolated.sum()),
                   "tie_rule": "first within 250000-row block; later block replaces equal maximum",
                   "risk_linkage": "risk stage must renormalize raw PGA on its valid H/V/E intersection"})


def validate_results(ctx):
    """Audit pair coverage, recomputed envelope, inventory and manuscript Table S1."""
    faults = gpd.read_file(ctx.file(FILES[2][0]))
    final = gpd.read_file(ctx.file(FILES[6][0]))
    keys = pd.Index(building_keys(final, "building_id"))
    scenario_ids = pd.Index(faults.scenario_id.astype(int))
    seen = np.zeros((len(faults), len(final)), dtype=bool)
    counts = np.zeros(len(faults), dtype=np.int64)
    sums, maxima = np.zeros(len(faults)), np.full(len(faults), -np.inf)
    rows = 0
    for chunk in pd.read_csv(ctx.file(FILES[5][0]), chunksize=ctx.model["csv_chunk_size"],
                              usecols=["building_id", "scenario_id", "PGA_Zhang2022_g"],
                              dtype={"building_id": str}):
        bpos, spos = keys.get_indexer(chunk.building_id), scenario_ids.get_indexer(chunk.scenario_id)
        pga = chunk.PGA_Zhang2022_g.to_numpy()
        if (bpos < 0).any() or (spos < 0).any() or not np.isfinite(pga).all() or (pga < 0).any():
            raise ValueError("Unknown IDs or invalid PGA in scenario matrix")
        pair = spos * len(final) + bpos
        unique = np.unique(pair)
        if len(unique) != len(pair) or seen.ravel()[unique].any():
            raise ValueError("Duplicate building-scenario pair")
        seen.ravel()[unique] = True
        counts += np.bincount(spos, minlength=len(faults))
        sums += np.bincount(spos, weights=pga, minlength=len(faults))
        np.maximum.at(maxima, spos, pga)
        rows += len(chunk)
    if not seen.all():
        raise ValueError("Missing building-scenario pairs")
    envelope = read_envelope(ctx.file(FILES[5][0]), ctx.model["csv_chunk_size"]).reindex(keys)
    np.testing.assert_allclose(final.PGA_Final_g, envelope.PGA_Final_g, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(final.Dom_Scenario, envelope.Dom_Scenario)
    normalized, parameters = inventory_normalize(final.PGA_Final_g)
    np.testing.assert_allclose(final.Hazard_Norm, normalized, atol=1e-12)
    if not final.Hazard_Norm.between(0, 1).all():
        raise ValueError("Hazard_Norm outside [0,1]")
    statistics = faults[["scenario_id", "FaultName", "Length_km", "Mw"]].copy()
    statistics["max_pga_g"], statistics["mean_pga_g"] = maxima, sums / counts
    dominant = final.Dom_Scenario.value_counts()
    statistics["dominant_buildings"] = statistics.scenario_id.map(dominant).fillna(0).astype(int)
    statistics["dominant_share_pct"] = 100. * statistics.dominant_buildings / len(final)
    write_csv(statistics, ctx.statistic_file(STATISTICS_FILES[7][0]))

    report = {"status": "PASS", "building_count": len(final), "scenario_count": len(faults),
              "matrix_rows": rows, "all_pairs_unique_complete_finite_nonnegative": True,
              "envelope_recomputed_match": True, "normalization": parameters,
              "interpretation": "Internal consistency validation of the current SCS-method run."}
    write_json(ctx.file(FILES[7][0]), report)
    print("  validation PASS; internal consistency checks passed", flush=True)


STEPS = {1: convert_faults, 2: prepare_scenarios, 3: create_vs30_raster,
         4: sample_building_vs30, 5: calculate_scenario_pga,
         6: create_envelope, 7: validate_results}


def run_cli(default_steps=None):
    parser = argparse.ArgumentParser(description="SCS building-level deterministic hazard workflow")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path, help="Separate calculation/validation output directory")
    parser.add_argument("--steps", nargs="+", type=int, choices=range(1, 8),
                        default=default_steps or list(STEPS))
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Replace selected outputs in the new project")
    args = parser.parse_args()
    ctx = Context(args.config, args.output_dir)
    # Reject unsupported scientific variants rather than quietly ignoring config.
    fixed = {"reference": "SCS_current_S1", "site_reference": "zero_site_term_S1_eq_S8",
             "mechanism": "strike-slip", "hanging_wall": False, "pga_units": "g",
             "csv_chunk_size": 250000}
    for key, value in fixed.items():
        if ctx.model[key] != value:
            raise ValueError(f"Unsupported {key}; this module implements {value!r}")
    if ctx.model["equivalent_depth_km"] <= 0 or ctx.model["vs30_resolution_deg"] <= 0:
        raise ValueError("Depth and grid spacing must be positive")
    inputs = ctx.check_inputs()
    if args.check_inputs:
        print(json.dumps(inputs, ensure_ascii=False, indent=2))
        return
    for step in args.steps:
        for filename in FILES[step]:
            if ctx.file(filename).exists() and not args.overwrite:
                raise FileExistsError(f"{ctx.file(filename)} already exists; use --overwrite explicitly")
        for filename in STATISTICS_FILES.get(step, []):
            if ctx.statistic_file(filename).exists() and not args.overwrite:
                raise FileExistsError(f"{ctx.statistic_file(filename)} already exists; use --overwrite explicitly")
    manuscript_files = [WORKSPACE_ROOT / "manuscript/tex" / name
                        for name in ("manuscript.tex", "Supplementary_material.tex")]
    manifest = {"status": "running", "started_at": datetime.now().astimezone().isoformat(),
                "config": ctx.config, "config_fingerprint": fingerprint(ctx.config_path),
                "input_fingerprints": inputs, "steps": args.steps,
                "paper_sources": [fingerprint(p) for p in manuscript_files],
                "code_fingerprints": [fingerprint(p) for p in sorted(Path(__file__).parent.glob("*.py"))],
                "completed_steps": []}
    path = ctx.file("run_manifest.json")
    write_json(path, manifest)
    try:
        for step in args.steps:
            print(f"STEP {step:02d}: {STEPS[step].__name__}", flush=True)
            STEPS[step](ctx)
            manifest["completed_steps"].append(step)
            write_json(path, manifest)
        manifest["status"] = "complete"
    except Exception as exc:
        manifest["status"], manifest["error"] = "failed", repr(exc)
        raise
    finally:
        manifest["finished_at"] = datetime.now().astimezone().isoformat()
        write_json(path, manifest)


if __name__ == "__main__":
    run_cli()
