#!/usr/bin/env python3
"""Bin existing merged PS v_vertical values into a metre-based GeoTIFF.

Run with the seismic Python environment (numpy, pandas, scipy, pyproj, rasterio).
The source CSV is read only. No velocity conversion, filtering by coherence,
geometric expansion, or interpolation into unobserved cells is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = ROOT / "data/TSX_PS/tsx_merged.csv"
NODATA = -9999.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def grid(x: np.ndarray, y: np.ndarray, resolution: float):
    left = np.floor(x.min() / resolution) * resolution
    top = (np.floor(y.max() / resolution) + 1) * resolution
    width = int(np.floor((x.max() - left) / resolution)) + 1
    height = int(np.floor((top - y.min()) / resolution)) + 1
    col = np.floor((x - left) / resolution).astype(np.int64)
    row = np.floor((top - y) / resolution).astype(np.int64)
    assert ((0 <= col) & (col < width) & (0 <= row) & (row < height)).all()
    return width, height, from_origin(left, top, resolution, resolution), row * width + col


def quantiles(values: np.ndarray, levels=(0, .01, .05, .25, .5, .75, .95, .99, 1)):
    return {str(q): float(v) for q, v in zip(levels, np.quantile(values, levels))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--resolution", type=float, default=20.0, help="Pixel size in metres")
    parser.add_argument("--crs", default="EPSG:4543")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--history", type=Path)
    args = parser.parse_args()
    crs = CRS.from_user_input(args.crs)
    if not crs.is_projected or any(a.unit_name != "metre" for a in crs.axis_info):
        parser.error("Use a projected CRS with metre units.")
    if not np.isfinite(args.resolution) or args.resolution <= 0:
        parser.error("Resolution must be a positive finite number.")
    stamp = datetime.now(ZoneInfo("Asia/Shanghai"))
    output = args.output or args.source.with_name(
        f"TSX_merged_v_vertical_{args.resolution:g}m.tif"
    )
    history = args.history or ROOT / "history/changes" / (
        stamp.strftime("%Y-%m-%d_%H%M%S") + "_tsx_vertical_raster"
    )
    if output.exists():
        raise FileExistsError(f"Existing raster will not be overwritten: {output}")
    if history.exists():
        raise FileExistsError(f"Existing history directory: {history}")
    history.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(__file__, history / Path(__file__).name)
    before_hash = sha256(args.source)
    frame = pd.read_csv(args.source, usecols=["lon", "lat", "v_vertical", "source"])
    rows = len(frame)
    numbers = frame[["lon", "lat", "v_vertical"]].to_numpy()
    valid = (
        np.isfinite(numbers).all(axis=1)
        & frame.lon.between(-180, 180).to_numpy()
        & frame.lat.between(-90, 90).to_numpy()
    )
    frame = frame.loc[valid]
    if frame.empty:
        raise ValueError("No valid coordinate/velocity observations.")
    x, y = Transformer.from_crs(4326, crs, always_xy=True).transform(
        frame.lon.to_numpy(), frame.lat.to_numpy()
    )
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("Non-finite projected coordinates.")
    velocity = frame.v_vertical.to_numpy()
    if (velocity == NODATA).any():
        raise ValueError("The selected NoData value collides with source values.")
    report = {
        "created_at": stamp.isoformat(),
        "source": str(args.source.resolve()),
        "source_sha256": before_hash,
        "source_field": "v_vertical",
        "coordinate_fields": ["lon", "lat"],
        "coordinate_crs": "EPSG:4326",
        "ignored_coordinate_field": "geometry (legacy projected WKT)",
        "crs": crs.to_string(),
        "crs_name": crs.name,
        "resolution_m": args.resolution,
        "rows": rows,
        "valid_points": len(frame),
        "excluded_invalid_records": int((~valid).sum()),
        "source_counts": {str(k): int(v) for k, v in frame.source.value_counts().items()},
        "bbox_lonlat": [float(frame.lon.min()), float(frame.lat.min()),
                        float(frame.lon.max()), float(frame.lat.max())],
        "v_vertical_quantiles": quantiles(velocity),
        "point_velocity_mean": float(velocity.mean()),
        "method": "Arithmetic mean of all finite source v_vertical values per occupied cell",
        "empty_cells": "NoData; no interpolation",
        "velocity_recalculated": False,
        "coherence_filter_applied": False,
        "units": "Source field units retained, not independently confirmed",
        "unit_context": "Existing project analysis/plotting code labels this field mm/year",
        "sign_convention": "Original field sign retained, not independently confirmed",
        "candidate_resolutions": [],
    }
    for resolution in [5, 10, 20, 30, 50]:
        w, h, _, indices = grid(x, y, resolution)
        _, counts = np.unique(indices, return_counts=True)
        report["candidate_resolutions"].append({
            "resolution_m": resolution, "width": w, "height": h,
            "occupied_cells": len(counts),
            "bbox_occupancy_pct": float(len(counts) / (w * h) * 100),
            "points_per_occupied_cell_quantiles": quantiles(counts, (.1, .5, .9, .99)),
            "single_point_cells_pct": float((counts == 1).mean() * 100),
        })
    del indices, counts
    xy = np.column_stack((x, y))
    sample = np.random.default_rng(42).choice(len(frame), min(50000, len(frame)), replace=False)
    if len(frame) >= 2:
        distances, _ = cKDTree(xy).query(xy[sample], k=2, workers=2)
        report["nearest_neighbor_sample"] = {
            "n": len(sample), "seed": 42,
            "distance_m_quantiles": quantiles(distances[:, 1]),
        }
    del xy
    width, height, transform, indices = grid(x, y, args.resolution)
    cells = width * height
    counts = np.bincount(indices, minlength=cells)
    sums = np.bincount(indices, weights=velocity, minlength=cells)
    occupied = counts > 0
    means = sums[occupied] / counts[occupied]
    image = np.full(cells, NODATA, dtype=np.float32)
    image[occupied] = means
    # Check conservation and Float32 rounding before writing.
    weighted_mean = float(np.dot(image[occupied].astype(np.float64), counts[occupied]) / len(frame))
    mean_error = abs(weighted_mean - float(velocity.mean()))
    assert int(counts.sum()) == len(frame)
    assert np.isfinite(means).all()
    assert means.min() >= velocity.min() - 1e-10 and means.max() <= velocity.max() + 1e-10
    assert mean_error < 1e-6
    assert np.allclose(image[occupied], means, rtol=1e-7, atol=1e-6)
    image = image.reshape(height, width)
    temporary = output.with_name(output.stem + ".pending.tif")
    if temporary.exists():
        raise FileExistsError(temporary)
    with rasterio.open(
        temporary, "w", driver="GTiff", width=width, height=height, count=1,
        dtype="float32", crs=crs, transform=transform, nodata=NODATA,
        tiled=True, blockxsize=256, blockysize=256, compress="deflate", predictor=3,
        BIGTIFF="IF_SAFER",
    ) as dst:
        dst.write(image, 1)
        dst.set_band_description(1, "Mean v_vertical of merged PS observations")
        dst.update_tags(
            AREA_OR_POINT="Area", SOURCE_FILE=args.source.name, SOURCE_SHA256=before_hash,
            SOURCE_FIELD="v_vertical", AGGREGATION="arithmetic_mean_per_cell",
            POINT_COUNT=str(len(frame)), INTERPOLATION="none", SOURCE_CRS="EPSG:4326",
            VELOCITY_UNITS="original_field_units_not_independently_confirmed",
            UNIT_CONTEXT="Existing project scripts use mm/year; source unit metadata unavailable",
            SIGN_CONVENTION="unchanged_from_source", CREATED_AT=stamp.isoformat(),
        )
        dst.build_overviews([2, 4, 8, 16], Resampling.average)
        dst.update_tags(ns="rio_overview", resampling="average")
    with rasterio.open(temporary) as src:
        reread = src.read(1)
        assert np.array_equal(reread, image)
        assert src.crs.to_epsg() == crs.to_epsg()
        assert src.transform == transform and src.nodata == NODATA
        assert src.res == (args.resolution, args.resolution)
        assert int((src.read_masks(1) > 0).sum()) == int(occupied.sum())
        report.update({
            "output": str(output.resolve()), "width": width, "height": height,
            "bounds": list(src.bounds), "dtype": src.dtypes[0], "nodata": NODATA,
            "overviews": src.overviews(1), "occupied_cells": int(occupied.sum()),
            "empty_cells_count": int((~occupied).sum()),
            "raster_value_quantiles": quantiles(image.ravel()[occupied]),
            "weighted_raster_mean": weighted_mean,
            "global_mean_error_after_float32_rounding": mean_error,
            "all_valid_points_accounted_for": True, "full_raster_readback_exact": True,
            "pixel_mean_error_max": float(np.max(np.abs(image.ravel()[occupied] - means))),
            "grid_points_per_occupied_cell_quantiles": quantiles(counts[occupied], (.1, .5, .9, .99)),
        })
    after_hash = sha256(args.source)
    assert before_hash == after_hash, "Source changed while the raster was being made"
    report["source_unchanged"] = True
    if output.exists():
        raise FileExistsError(output)
    temporary.rename(output)
    report["output_bytes"] = output.stat().st_size
    report["output_sha256"] = sha256(output)
    report["history"] = str(history.resolve())
    dump(history / "raster_verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
