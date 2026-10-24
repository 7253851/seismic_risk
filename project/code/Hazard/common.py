"""Paths, input checks and atomic outputs shared by the SCS hazard steps."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
from paths import DATA_ROOT, RESULT_ROOT, PROJECT_ROOT, WORKSPACE_ROOT, resolve_path

# Use the installed PROJ database rather than stale environment paths.
for _key in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
    if os.environ.get(_key) and not Path(os.environ[_key]).is_dir():
        os.environ.pop(_key)
from pyproj import datadir
os.environ["PROJ_DATA"] = datadir.get_data_dir()
os.environ["PROJ_LIB"] = datadir.get_data_dir()

import geopandas as gpd


def fingerprint(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def write_csv(frame, path):
    path = Path(path)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temp, index=False, encoding="utf-8-sig")
    os.replace(temp, path)


def write_vector(frame, path, layer):
    path = Path(path)
    temp = path.with_name(f".{path.stem}.{os.getpid()}.gpkg")
    try:
        frame.to_file(temp, layer=layer, driver="GPKG", index=False)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def read_vector(path, geometry_types, crs=None, allow_invalid=False):
    frame = gpd.read_file(path)
    if frame.empty or frame.crs is None:
        raise ValueError(f"Empty input or missing CRS: {path}")
    bad = (frame.geometry.isna() | frame.geometry.is_empty
           | ~frame.geometry.geom_type.isin(geometry_types))
    if bad.any():
        raise ValueError(f"{path}: {int(bad.sum())} empty or wrong-type geometries")
    invalid = ~frame.geometry.is_valid
    if invalid.any() and not allow_invalid:
        raise ValueError(f"{path}: {int(invalid.sum())} invalid geometries; "
                         "enable allow_invalid only when preserving the source workflow")
    if invalid.any():
        print(f"  WARNING: preserving {int(invalid.sum())} invalid geometries unchanged: {path}",
              flush=True)
    return frame.to_crs(crs) if crs else frame


def building_keys(frame, field):
    if field not in frame:
        raise KeyError(f"Missing explicit building ID field: {field}")
    keys = frame[field].astype("string").str.strip()
    if keys.isna().any() or keys.eq("").any() or not keys.is_unique:
        raise ValueError("Building IDs must be unique, nonempty and non-null")
    return keys.astype(str)


class Context:
    def __init__(self, config=None, output=None):
        self.config_path = Path(config or Path(__file__).with_name("config.json")).resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.data_root = resolve_path(self.config["data_root"])
        if self.data_root != DATA_ROOT.resolve():
            raise ValueError("Base inputs must use the workspace data root")
        self.results_root = RESULT_ROOT.resolve()
        self.output = (Path(output).expanduser().resolve() if output else
                       resolve_path(self.config["outputs"]["results_dir"]))
        if not self.output.is_relative_to(self.results_root):
            raise ValueError(f"Calculation outputs must be inside {self.results_root}")
        self.statistics = resolve_path(self.config["outputs"]["statistics_dir"])
        if not self.statistics.is_relative_to(self.results_root):
            raise ValueError(f"Statistics outputs must be inside {self.results_root}")
        self.output.mkdir(parents=True, exist_ok=True)
        self.statistics.mkdir(parents=True, exist_ok=True)
        self.model = self.config["model"]
        self.id_field = self.config["inputs"]["buildings"]["id_field"]

    def input(self, name):
        path = resolve_path(self.config["inputs"][name]["path"])
        if not any(path.is_relative_to(base) for base in (DATA_ROOT, RESULT_ROOT)) or not path.is_file():
            raise FileNotFoundError(f"Invalid/missing calculation input: {path}")
        return path

    def file(self, name):
        return self.output / name

    def statistic_file(self, name):
        return self.statistics / name

    def report(self, number, value):
        write_json(self.file(f"step_{number:02d}_report.json"), value)

    def check_inputs(self):
        records = {}
        for name in self.config["inputs"]:
            path = self.input(name)
            files = [path]
            if path.suffix.lower() == ".shp":
                files = [path.with_suffix(ext) for ext in (".shp", ".shx", ".dbf", ".prj")]
                if path.with_suffix(".cpg").exists():
                    files.append(path.with_suffix(".cpg"))
            records[name] = [fingerprint(p) for p in files]
        return records


def inventory_normalize(values):
    """S1 Eq. S10: full hazard inventory, without trimming or logarithms."""
    minimum, maximum = float(values.min()), float(values.max())
    result = ((values - minimum) / (maximum - minimum)
              if maximum > minimum else values * 0.0)
    return result, {"minimum_g": minimum, "maximum_g": maximum,
                    "sample": "full_hazard_inventory", "count": len(values)}
