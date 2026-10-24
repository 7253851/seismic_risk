"""Repair invalid building polygons into a derived GeoPackage.

The source Shapefile is never modified. Invalid geometries are repaired with
Shapely make_valid; this script fails if repair creates empty or non-polygonal
features so potentially lossy cases can be reviewed rather than discarded.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = WORKSPACE_ROOT / "data"
RESULT_ROOT = WORKSPACE_ROOT / "result"
DEFAULT_SOURCE = DATA_ROOT / "buildings/height/building_height_extracted.shp"
DEFAULT_OUTPUT = RESULT_ROOT / "intermediate/buildings/building_height_repaired.gpkg"
ID_FIELD = "Build_ID"


def type_counts(geometries):
    return dict(sorted(Counter(geometries.geom_type).items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true",
                        help="replace an existing derived output")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_relative_to(DATA_ROOT.resolve()):
        raise ValueError(f"Source must remain inside data: {source}")
    if not output.is_relative_to(RESULT_ROOT.resolve()):
        raise ValueError(f"Output must remain inside result: {output}")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists; pass --overwrite to replace: {output}")

    frame = gpd.read_file(source)
    if frame.empty or frame.crs is None:
        raise ValueError("Source is empty or has no CRS")
    if ID_FIELD not in frame or frame[ID_FIELD].isna().any() or not frame[ID_FIELD].is_unique:
        raise ValueError(f"{ID_FIELD} must exist, be non-null and unique")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("Source contains null or empty geometries")
    if not frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Source contains non-polygon geometries")

    invalid = ~frame.geometry.is_valid
    invalid_count = int(invalid.sum())
    reasons = shapely.is_valid_reason(frame.geometry.array)
    reason_counts = Counter(str(reason) for reason, bad in zip(reasons, invalid) if bad)

    repaired = frame.copy()
    if invalid_count:
        repaired.loc[invalid, repaired.geometry.name] = frame.loc[invalid].geometry.make_valid()

    bad_type = ~repaired.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if bad_type.any() or repaired.geometry.is_empty.any():
        counts = type_counts(repaired.loc[bad_type].geometry)
        raise ValueError(f"Repair produced empty/non-polygon geometries: {counts}")
    remaining_invalid = int((~repaired.geometry.is_valid).sum())
    if remaining_invalid:
        raise ValueError(f"{remaining_invalid} invalid geometries remain after repair")
    if len(repaired) != len(frame) or not repaired[ID_FIELD].equals(frame[ID_FIELD]):
        raise AssertionError("Repair changed feature count or building ID order")

    before = frame.geometry
    after = repaired.geometry
    old_area = before.area.to_numpy(dtype=float)
    new_area = after.area.to_numpy(dtype=float)
    area_abs = np.abs(new_area - old_area)
    area_rel = area_abs / np.maximum(np.abs(old_area), np.finfo(float).tiny)
    old_centroids, new_centroids = before.centroid, after.centroid
    centroid_shift = np.hypot(new_centroids.x - old_centroids.x,
                              new_centroids.y - old_centroids.y).to_numpy(dtype=float)
    hausdorff = np.asarray([a.hausdorff_distance(b) for a, b in zip(before, after)], dtype=float)

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.gpkg")
    try:
        repaired.to_file(temp, layer=output.stem, driver="GPKG", index=False)
        check = gpd.read_file(temp, layer=output.stem)
        if (len(check) != len(frame) or check.crs != frame.crs
                or int((~check.geometry.is_valid).sum()) != 0
                or check[ID_FIELD].astype(str).tolist() != frame[ID_FIELD].astype(str).tolist()):
            raise AssertionError("GeoPackage read-back validation failed")
        os.replace(temp, output)
    finally:
        if temp.exists():
            temp.unlink()

    report = {
        "source": str(source),
        "output": str(output),
        "method": "Shapely make_valid applied only to invalid features",
        "source_crs": frame.crs.to_string(),
        "feature_count": int(len(frame)),
        "repaired_feature_count": invalid_count,
        "invalid_reasons": dict(sorted(reason_counts.items())),
        "remaining_invalid_count": remaining_invalid,
        "empty_geometry_count": int(repaired.geometry.is_empty.sum()),
        "geometry_type_counts_before": type_counts(frame.geometry),
        "geometry_type_counts_after": type_counts(repaired.geometry),
        "area_absolute_difference_m2_max": float(area_abs.max(initial=0.0)),
        "area_relative_difference_max": float(area_rel.max(initial=0.0)),
        "centroid_shift_m_max": float(centroid_shift.max(initial=0.0)),
        "hausdorff_distance_m_max": float(hausdorff.max(initial=0.0)),
        "source_modified": False,
        "readback_validation": "PASS",
    }
    report_path = output.with_name(f"{output.stem}_repair_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
