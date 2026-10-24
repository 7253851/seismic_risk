"""PS-InSAR line-of-sight to vertical displacement-rate conversion.

The TerraSAR-X PS products store the incidence angle `inc` in radians
(TSX1 about 0.52-0.56, TSX2 about 0.82-0.83). Vertical rates follow main-text
Eq. 3, v_vertical = v_LOS / cos(inc), with horizontal motion neglected.

Run as a script to rebuild the stored `v_vertical` field from `v_los` and `inc`
in the merged PS table and in the building-associated PS layer.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np

from paths import DATA_ROOT, RESULT_ROOT

# Radian bounds that exclude degree-valued input (a 30-48 degree angle would
# exceed the upper bound) and grazing geometries.
INCIDENCE_RAD_RANGE = (0.1, 1.4)
MERGED_PS_CSV = DATA_ROOT / "TSX_PS/tsx_merged.csv"
BUILDING_PS_GPKG = RESULT_ROOT / "intermediate/vulnerability_inputs/building_ps_points.gpkg"
BUILDING_PS_LAYER = "building_ps_points"


def check_incidence_radians(incidence):
    angle = np.asarray(incidence, dtype=float)
    low, high = INCIDENCE_RAD_RANGE
    if not np.isfinite(angle).all():
        raise ValueError("Incidence angles contain missing or non-finite values")
    if angle.min() < low or angle.max() > high:
        raise ValueError(f"Incidence angles span {angle.min():.4f}-{angle.max():.4f}; "
                         f"expected radians within {low}-{high}")
    return angle


def vertical_rate(v_los, incidence_rad):
    """Project LOS rates to vertical rates; `incidence_rad` must be in radians."""
    return np.asarray(v_los, dtype=float) / np.cos(check_incidence_radians(incidence_rad))


def rebuild_merged_csv(path=MERGED_PS_CSV, chunk_rows=500_000):
    """Rewrite only the `v_vertical` column; all other fields keep their original text."""
    temporary = path.with_suffix(".csv.tmp")
    rows, low, high = 0, np.inf, -np.inf
    with path.open(newline="", encoding="utf-8") as source, temporary.open("w", newline="", encoding="utf-8") as target:
        reader, writer = csv.reader(source), csv.writer(target, lineterminator="\n")
        header = next(reader)
        writer.writerow(header)
        i_vertical, i_los, i_inc = (header.index(name) for name in ("v_vertical", "v_los", "inc"))
        while True:
            chunk = [row for _, row in zip(range(chunk_rows), reader)]
            if not chunk:
                break
            los = np.array([row[i_los] for row in chunk], dtype=float)
            inc = np.array([row[i_inc] for row in chunk], dtype=float)
            vertical = vertical_rate(los, inc)
            for row, value in zip(chunk, vertical):
                row[i_vertical] = repr(float(value))
            writer.writerows(chunk)
            rows += len(chunk)
            low, high = min(low, inc.min()), max(high, inc.max())
    temporary.replace(path)
    return {"path": str(path), "rows": rows, "incidence_range_rad": [float(low), float(high)]}


def rebuild_building_gpkg(path=BUILDING_PS_GPKG, layer=BUILDING_PS_LAYER):
    with sqlite3.connect(path) as connection:
        los, inc = map(np.asarray, zip(*connection.execute(f'SELECT v_los, inc FROM "{layer}"').fetchall()))
        check_incidence_radians(inc)
        connection.create_function("cos", 1, math.cos, deterministic=True)
        # GeoPackage R-tree triggers reference GDAL's ST_* functions; they only fire when
        # fid or geom change, which this attribute update never does.
        def geometry_function_guard(*_):
            raise sqlite3.OperationalError("Geometry changed during an attribute-only update")
        for name in ("ST_IsEmpty", "ST_MinX", "ST_MaxX", "ST_MinY", "ST_MaxY"):
            connection.create_function(name, 1, geometry_function_guard)
        connection.execute(f'UPDATE "{layer}" SET v_vertical = v_los / cos(inc)')
        rows = connection.execute(f'SELECT count(*) FROM "{layer}"').fetchone()[0]
    return {"path": str(path), "layer": layer, "rows": int(rows),
            "incidence_range_rad": [float(inc.min()), float(inc.max())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, default=RESULT_ROOT / "intermediate/vulnerability_inputs/vertical_rate_rebuild.json")
    args = parser.parse_args()
    report = {"formula": "v_vertical = v_los / cos(inc), inc in radians",
              "run_time": datetime.now().astimezone().isoformat(timespec="seconds"),
              "merged_csv": rebuild_merged_csv(), "building_layer": rebuild_building_gpkg()}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
