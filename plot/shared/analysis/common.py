"""Shared administrative joins, summaries and spatial statistics."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

COUNTY_EN = {
    "呈贡区": "Chenggong District", "晋宁区": "Jinning District", "西山区": "Xishan District",
    "东川区": "Dongchuan District", "官渡区": "Guandu District", "寻甸回族彝族自治县": "Xundian Hui and Yi Autonomous County",
    "嵩明县": "Songming County", "禄劝彝族苗族自治县": "Luquan Yi and Miao Autonomous County", "宜良县": "Yiliang County",
    "石林彝族自治县": "Shilin Yi Autonomous County", "富民县": "Fumin County", "盘龙区": "Panlong District",
    "五华区": "Wuhua District", "安宁市": "Anning City",
}
CLASS_ORDER = ["Very Low", "Low", "Moderate", "High", "Very High"]
CLASS_COLORS = ["#2C7BB6", "#ABD9E9", "#FFFFBF", "#FDAE61", "#D7191C"]


def english_street(value: object) -> str:
    text = str(value).strip()
    suffix = ""
    for ending, english in (("街道", "Subdistrict"), ("镇", "Town"), ("乡", "Township")):
        if text.endswith(ending):
            text, suffix = text[:-len(ending)], english
            break
    try:
        from pypinyin import lazy_pinyin
        words = lazy_pinyin(text, errors="ignore")
        name = " ".join(word.capitalize() for word in words if word)
    except ImportError:
        name = ""
    if not name:
        name = "Administrative Unit"
    return f"{name} {suffix}".strip()


def assign_admin(buildings: gpd.GeoDataFrame, polygon_path: str, level: str, value_field: str, class_field: str | None = None) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict]:
    admin = gpd.read_file(polygon_path)
    if admin.crs is None or buildings.crs is None:
        raise ValueError(f"Missing CRS for {level} administrative join")
    admin = admin.to_crs(buildings.crs).copy()
    admin = admin.loc[admin.geometry.notna() & ~admin.geometry.is_empty].reset_index(drop=True)
    invalid = int((~admin.geometry.is_valid).sum())
    if invalid:
        admin.geometry = admin.geometry.make_valid()
    if level == "county":
        if "name" not in admin:
            raise KeyError(f"County input does not contain 'name': {polygon_path}")
        admin["Admin_Unit_ID"] = admin.get("gb", pd.Series(range(len(admin)))).astype(str)
        admin["Admin_Name"] = admin["name"].astype(str).str.strip()
        admin["Admin_Name_EN"] = admin.Admin_Name.map(COUNTY_EN).fillna(admin.Admin_Name)
        admin["County_Name"] = admin.Admin_Name
        admin["County_Name_EN"] = admin.Admin_Name_EN
    elif level == "street":
        if not {"乡", "县"}.issubset(admin.columns):
            raise KeyError(f"Street input must contain '乡' and '县': {polygon_path}")
        admin["Admin_Unit_ID"] = admin["县"].astype(str).str.strip() + "_" + admin["乡"].astype(str).str.strip()
        admin["Admin_Name"] = admin["乡"].astype(str).str.strip()
        admin["Admin_Name_EN"] = admin.Admin_Name.map(english_street)
        admin["County_Name"] = admin["县"].astype(str).str.strip()
        admin["County_Name_EN"] = admin.County_Name.map(COUNTY_EN).fillna(admin.County_Name)
    else:
        raise ValueError(f"Unknown administrative level: {level}")

    attributes = ["Build_ID", value_field] + ([class_field] if class_field else [])
    points = gpd.GeoDataFrame(buildings[attributes].copy(), geometry=buildings.geometry.centroid, crs=buildings.crs)
    joined = gpd.sjoin(points, admin[["Admin_Unit_ID", "Admin_Name", "Admin_Name_EN", "County_Name", "County_Name_EN", "geometry"]], how="left", predicate="within")
    multi = int(joined.Build_ID.duplicated(keep=False).sum())
    if multi:
        # Centroids exactly on shared boundaries may match two polygons. Keep the first stable ID.
        joined = joined.sort_values(["Build_ID", "Admin_Unit_ID"]).drop_duplicates("Build_ID", keep="first")
    unmatched_ids = set(buildings.Build_ID) - set(joined.loc[joined.Admin_Unit_ID.notna(), "Build_ID"])
    unmatched_count = len(unmatched_ids)
    if unmatched_count:
        # Use nearest polygon only for outside/border slivers; retain the assignment method in metadata.
        missing_points = points.loc[points.Build_ID.isin(unmatched_ids)].copy()
        nearest = gpd.sjoin_nearest(missing_points, admin[["Admin_Unit_ID", "Admin_Name", "Admin_Name_EN", "County_Name", "County_Name_EN", "geometry"]], how="left", distance_col="admin_distance_m")
        nearest = nearest.sort_values(["Build_ID", "admin_distance_m", "Admin_Unit_ID"]).drop_duplicates("Build_ID", keep="first")
        joined = pd.concat([joined.loc[joined.Admin_Unit_ID.notna()], nearest], ignore_index=True)
        joined = gpd.GeoDataFrame(joined, geometry=points.geometry.name, crs=buildings.crs)
    if len(joined) != len(buildings) or joined.Build_ID.duplicated().any() or joined.Admin_Unit_ID.isna().any():
        raise ValueError(f"{level} allocation did not produce one administrative unit per building")
    summary = {
        "level": level, "building_count": int(len(buildings)), "administrative_unit_count": int(admin.Admin_Unit_ID.nunique()),
        "invalid_administrative_geometries_repaired": invalid, "duplicate_boundary_matches_resolved": multi,
        "centroids_outside_polygon_extent_assigned_to_nearest": unmatched_count,
        "maximum_nearest_assignment_distance_m": float(joined.get("admin_distance_m", pd.Series([0])).max()) if "admin_distance_m" in joined else 0.0,
    }
    return joined, admin, summary


def summarize_admin(joined: gpd.GeoDataFrame, admin: gpd.GeoDataFrame, value_field: str, class_field: str | None = None, level: str = "admin") -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    rows = []
    for unit_id, group in joined.groupby("Admin_Unit_ID", sort=True):
        values = pd.to_numeric(group[value_field], errors="coerce").dropna()
        row = {
            "Admin_Unit_ID": unit_id, "Admin_Name": group.Admin_Name.iloc[0], "Admin_Name_EN": group.Admin_Name_EN.iloc[0],
            "County_Name": group.County_Name.iloc[0], "County_Name_EN": group.County_Name_EN.iloc[0],
            "Building_Count": int(len(group)), f"Mean_{value_field}": float(values.mean()), f"Median_{value_field}": float(values.median()),
            f"P90_{value_field}": float(values.quantile(.90)), f"SD_{value_field}": float(values.std(ddof=1)) if len(values) > 1 else np.nan,
        }
        if class_field:
            counts = group[class_field].value_counts().reindex(CLASS_ORDER, fill_value=0)
            for name, count in counts.items():
                key = name.replace(" ", "_")
                row[f"{key}_Count"] = int(count)
                row[f"{key}_Pct"] = float(count / len(group) * 100) if len(group) else np.nan
            row["High_or_Very_High_Count"] = int(counts["High"] + counts["Very High"])
            row["High_or_Very_High_Pct"] = float(row["High_or_Very_High_Count"] / len(group) * 100) if len(group) else np.nan
        rows.append(row)
    summary = pd.DataFrame(rows)
    geo = admin.merge(summary.drop(columns=["Admin_Name", "Admin_Name_EN", "County_Name", "County_Name_EN"], errors="ignore"), on="Admin_Unit_ID", how="left", validate="one_to_one")
    count_fields = [field for field in summary if field.endswith("_Count") or field == "Building_Count"]
    if count_fields:
        geo[count_fields] = geo[count_fields].fillna(0).astype(int)
    return geo, summary








def describe(frame: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    rows = []
    for field in fields:
        if field not in frame:
            continue
        values = pd.to_numeric(frame[field], errors="coerce").replace([np.inf, -np.inf], np.nan)
        valid = values.dropna()
        row = {"indicator": field, "valid_count": int(len(valid)), "missing_count": int(values.isna().sum())}
        for label, q in [("min", None), ("p01", .01), ("p05", .05), ("p25", .25), ("mean", None), ("median", .5), ("p75", .75), ("p90", .9), ("p95", .95), ("p99", .99), ("max", None), ("std", None)]:
            if valid.empty:
                row[label] = np.nan
            elif label == "min":
                row[label] = float(valid.min())
            elif label == "max":
                row[label] = float(valid.max())
            elif label == "mean":
                row[label] = float(valid.mean())
            elif label == "median":
                row[label] = float(valid.median())
            elif label == "std":
                row[label] = float(valid.std(ddof=1)) if len(valid) > 1 else np.nan
            else:
                row[label] = float(valid.quantile(q))
        rows.append(row)
    return pd.DataFrame(rows)
