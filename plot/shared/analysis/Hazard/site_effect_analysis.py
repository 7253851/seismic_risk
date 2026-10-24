#!/usr/bin/env python3
"""Versioned, direct-GMPE site response at fixed magnitude and Rrup distances.

The earlier building-stratified analysis remains available via --mode stratified.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "project/code"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "plot/shared"))
import sqlite3
import sys
import tempfile
from textwrap import fill
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/seismic-site-effects-mpl")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp/seismic-site-effects-cache")
SCRIPT_ROOT = Path(__file__).resolve().parents[4] / "project/code"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as effects
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from scipy import stats

from paths import DATA_ROOT, RESULT_ROOT, STATISTICS_ROOT, WORKSPACE_ROOT, PLOT_CODE_ROOT, PLOT_OUTPUT_ROOT
from Hazard import model as gmpe

DEFAULT_INPUT = RESULT_ROOT / "hazard/scs_pipeline/06_building_hazard.gpkg"
DEFAULT_OUTPUT = STATISTICS_ROOT / "Hazard/site_effects"
REFERENCE_VS30 = 760.0
FIXED_MAGNITUDE = 6.0
RESPONSE_DISTANCES_KM = (10.0, 15.0, 20.0, 30.0)
RESPONSE_VS30_RANGE = (180.0, 760.0)
URBAN_VS30_RANGE = (190.0, 350.0)
# SCS Supplementary Note S1, section S1.3.2 (not enforced by predict_pga).
OVERALL_MAGNITUDE_RANGE = (4.2, 7.9)
MECHANISM_MAGNITUDE_RANGES = {"strike-slip": (4.2, 6.1), "reverse": (4.2, 7.9), "normal": (4.2, 6.5)}
APPLICABILITY_SOURCE = WORKSPACE_ROOT / "manuscript/tex/Supplementary_material.tex"
RESPONSE_COLORS = ("#8F1635", "#CC3D3D", "#E47B30", "#B99A28")
STYLES = [("#B2182B", "-", "o"), ("#E05A70", "--", "s")]
STYLE = {
    "font.family": "Arial", "font.weight": "bold", "font.size": 16,
    "axes.labelsize": 24, "axes.labelweight": "bold", "axes.linewidth": 2.8,
    "xtick.labelsize": 16, "ytick.labelsize": 16, "legend.fontsize": 24,
    "xtick.major.width": 2.8, "ytick.major.width": 2.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "svg.fonttype": "path", "pdf.fonttype": 42,
    "mathtext.fontset": "custom", "mathtext.rm": "Arial:weight=bold",
    "mathtext.bf": "Arial:weight=bold", "mathtext.default": "regular",
}


def fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def new_run_directory(root: Path) -> Path:
    directory = root / "current"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def display_name(value: object) -> str:
    return str(value).replace("Westen brach", "Western branch").replace("Eastern brach", "Eastern branch")


def load_model_configuration(input_path: Path) -> tuple[dict, Path]:
    manifest = input_path.parent / "run_manifest.json"
    if manifest.exists():
        return json.loads(manifest.read_text(encoding="utf-8"))["config"]["model"], manifest
    config = SCRIPT_ROOT / "Hazard/config.json"
    return json.loads(config.read_text(encoding="utf-8"))["model"], config


def read_buildings(path: Path) -> pd.DataFrame:
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
        tables = [row[0] for row in connection.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
        if "building_hazard" not in tables:
            raise ValueError("Expected the building_hazard feature layer in the input GeoPackage")
        fields = [row[1] for row in connection.execute('PRAGMA table_info("building_hazard")') if row[1] not in {"geom", "fid"}]
        selected = [field for field in fields if field in {
            "Build_ID", "building_id", "PGA_Final_g", "Dom_Scenario", "Dom_Fault", "Dom_Mw", "Dom_Rrup", "Dom_Vs30", "Dom_Model",
            "Vs30", "Vs30_raw", "is_vs30_imputed", "is_vs30_clipped", "is_mw_out_of_range", "is_mechanism_extrapolated", "is_rrup_out_of_range",
        }]
        columns = ", ".join('"' + field + '"' for field in selected)
        return pd.read_sql_query(f'SELECT {columns} FROM "building_hazard"', connection)


def prepare_buildings(raw: pd.DataFrame, model_config: dict, width: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not np.isfinite(width) or width <= 0:
        raise ValueError("Distance-bin width must be finite and positive")
    required = {"Build_ID", "PGA_Final_g", "Vs30", "Dom_Fault", "Dom_Scenario", "Dom_Mw", "Dom_Rrup"}
    if required - set(raw):
        raise KeyError(f"Missing site-analysis fields: {sorted(required - set(raw))}")
    frame = raw.drop(columns="geometry", errors="ignore").copy()
    if frame.Build_ID.isna().any() or frame.Build_ID.duplicated().any():
        raise ValueError("Building IDs must be present and unique")
    for field in ("PGA_Final_g", "Vs30", "Dom_Mw", "Dom_Rrup"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    limits = model_config["vs30_range"]
    frame["Vs30_Used_m_s"] = pd.to_numeric(frame["Dom_Vs30"], errors="coerce") if "Dom_Vs30" in frame else frame.Vs30.clip(*limits)
    depth = float(model_config["equivalent_depth_km"])
    squared = frame.Dom_Rrup ** 2 - depth ** 2
    valid = (
        np.isfinite(frame[["PGA_Final_g", "Dom_Mw", "Dom_Rrup", "Vs30_Used_m_s"]]).all(axis=1)
        & frame.PGA_Final_g.gt(0) & frame.Vs30_Used_m_s.gt(0)
        & frame.Dom_Rrup.gt(0) & squared.ge(-1e-8)
        & frame.Dom_Fault.notna() & frame.Dom_Scenario.notna()
    )
    excluded = frame.loc[~valid].copy()
    excluded["Exclusion_Reason"] = "Missing/invalid PGA, Vs30, controlling scenario, or distance proxy"
    frame = frame.loc[valid].copy()
    if frame.empty:
        raise ValueError("No valid buildings for site-effect analysis")
    frame["Horizontal_Distance_km"] = np.sqrt(squared.loc[valid].clip(lower=0))
    frame["Distance_Bin_Index"] = np.floor(frame.Horizontal_Distance_km / width).astype(int)
    frame["Distance_Lower_km"] = frame.Distance_Bin_Index * width
    frame["Distance_Upper_km"] = frame.Distance_Lower_km + width
    frame["Fault_Name_Display"] = frame.Dom_Fault.map(display_name)
    return frame, excluded


def spearman_summary(frame: pd.DataFrame, y: str = "PGA_Final_g") -> dict:
    x_values, y_values = frame.Vs30_Used_m_s.to_numpy(float), frame[y].to_numpy(float)
    finite = np.isfinite(x_values) & np.isfinite(y_values)
    x_values, y_values = x_values[finite], y_values[finite]
    n = len(x_values)
    reason = "OK"
    if n < 3:
        reason = "Fewer than three observations"
    elif len(np.unique(x_values)) < 2:
        reason = "Constant Vs30"
    elif len(np.unique(y_values)) < 2:
        reason = "Constant response"
    if reason == "OK":
        result = stats.spearmanr(x_values, y_values)
        rho, p_value = float(result.statistic), float(result.pvalue)
    else:
        rho, p_value = np.nan, np.nan
    return {
        "Building_Count": n, "Unique_Vs30_Count": len(np.unique(x_values)),
        "Spearman_rho": rho, "Spearman_p": p_value, "Correlation_Status": reason,
        "Small_Sample_Flag": n < 30,
    }


def quantile_summary(frame: pd.DataFrame, y: str, n_quantiles: int) -> pd.DataFrame:
    work = frame[["Vs30_Used_m_s", y]].dropna().copy()
    unique = work.Vs30_Used_m_s.nunique()
    if not len(work):
        return pd.DataFrame()
    if unique == 1:
        work["Quantile"] = 0
    else:
        work["Quantile"] = pd.qcut(work.Vs30_Used_m_s, q=min(n_quantiles, unique), duplicates="drop", labels=False)
    result = work.groupby("Quantile", observed=True).agg(
        Building_Count=(y, "size"), Vs30_Median_m_s=("Vs30_Used_m_s", "median"),
        Vs30_Min_m_s=("Vs30_Used_m_s", "min"), Vs30_Max_m_s=("Vs30_Used_m_s", "max"),
        Response_Mean=(y, "mean"), Response_Median=(y, "median"),
        Response_P05=(y, lambda values: values.quantile(0.05)), Response_P95=(y, lambda values: values.quantile(0.95)),
    ).reset_index()
    result["Response_Field"] = y
    if int(result.Building_Count.sum()) != len(work):
        raise ValueError("Vs30 quantile grouping lost observations")
    return result


def matched_amplification(frame: pd.DataFrame, model_config: dict) -> tuple[pd.DataFrame, dict]:
    audit = {
        "gmpe_source": str(Path(gmpe.__file__).resolve()),
        "gmpe_description": inspect.getdoc(gmpe),
        "predict_signature": str(inspect.signature(gmpe.predict_pga)),
        "reference_vs30_m_s": REFERENCE_VS30, "supported": False,
        "reference_policy": "Freeze each building's original controlling scenario, Mw, Rrup proxy, mechanism, and all non-site terms; do not reselect the controlling scenario at reference Vs30.",
    }
    if not model_config["vs30_range"][0] <= REFERENCE_VS30 <= model_config["vs30_range"][1]:
        audit["reason"] = "Reference Vs30 is outside the configured model range"
        return frame, audit
    if "vs30" not in inspect.signature(gmpe.predict_pga).parameters:
        audit["reason"] = "The existing GMPE does not expose a Vs30 argument"
        return frame, audit
    actual, actual_terms = gmpe.predict_pga(frame.Dom_Mw, frame.Dom_Rrup, frame.Vs30_Used_m_s)
    reference, reference_terms = gmpe.predict_pga(frame.Dom_Mw, frame.Dom_Rrup, REFERENCE_VS30)
    error = float(np.max(np.abs(actual - frame.PGA_Final_g.to_numpy())))
    audit["stored_pga_replay_max_absolute_error_g"] = error
    audit["stored_pga_replay_rtol"] = 1e-6
    if not np.allclose(actual, frame.PGA_Final_g, rtol=1e-6, atol=1e-9):
        audit["reason"] = "Current GMPE does not reproduce stored PGA; AF withheld to avoid mixing model versions"
        return frame, audit
    if not np.isfinite(reference).all() or not (reference > 0).all():
        raise ValueError("Reference PGA must be finite and positive")
    frame = frame.copy()
    frame["PGA_Recomputed_g"] = actual
    frame["PGA_Reference_760_g"] = reference
    frame["AF_760"] = actual / reference
    independent_ratio = np.exp(gmpe.site_term(frame.Vs30_Used_m_s, actual_terms["A1100_zero_site_g"]) - gmpe.site_term(REFERENCE_VS30, actual_terms["A1100_zero_site_g"]))
    audit.update({
        "supported": True, "reason": "Reference calculation supported and stored PGA replay passed",
        "coefficients": gmpe.COEFFICIENTS,
        "zero_site_a1100_invariance_max_error": float(np.max(np.abs(actual_terms["A1100_zero_site_g"] - reference_terms["A1100_zero_site_g"]))),
        "af_site_term_identity_max_error": float(np.max(np.abs(frame.AF_760 - independent_ratio))),
        "reference_unity_max_error": float(np.max(np.abs(reference / reference - 1))),
        "af_definition": "PGA(Mw_i, Rrup_i, Vs30_i) / PGA(Mw_i, Rrup_i, 760 m/s)",
        "interpretation": "Model-derived relative site response; AF below one denotes deamplification relative to this reference and is retained.",
    })
    if audit["zero_site_a1100_invariance_max_error"] > 1e-12 or audit["af_site_term_identity_max_error"] > 1e-10:
        raise ValueError("Matched-reference invariants failed: non-site terms must remain fixed")
    return frame, audit


def figure_directory(directory: Path) -> Path:
    if directory.is_relative_to(STATISTICS_ROOT):
        directory = PLOT_OUTPUT_ROOT / "05_distance_site_response/output/fixed_response" / directory.relative_to(DEFAULT_OUTPUT) if directory.is_relative_to(DEFAULT_OUTPUT) else PLOT_OUTPUT_ROOT / "05_distance_site_response/output" / directory.relative_to(STATISTICS_ROOT)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_plot(fig: plt.Figure, directory: Path, stem: str, dpi: int, *, transparent: bool = False) -> list[str]:
    directory = figure_directory(directory)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axis_labels = [label for ax in fig.axes for label in (ax.xaxis.label, ax.yaxis.label) if label.get_text()]
    legends = [*fig.legends, *(ax.get_legend() for ax in fig.axes if ax.get_legend() is not None)]
    for legend in legends:
        if any(legend.get_window_extent(renderer).overlaps(label.get_window_extent(renderer)) for label in axis_labels):
            raise ValueError(f"Legend overlaps an axis label in {stem}")
    paths = []
    for suffix in ("png", "pdf", "svg"):
        path = directory / f"{stem}.{suffix}"
        fig.savefig(path, dpi=dpi, transparent=transparent,
                    facecolor="none" if transparent else "white",
                    bbox_inches="tight", pad_inches=0.08)
        paths.append(str(path))
    plt.close(fig)
    return paths


def density(ax, frame: pd.DataFrame, response: str):
    return ax.hexbin(frame.Vs30_Used_m_s, frame[response], gridsize=45, mincnt=1, bins="log", cmap="YlOrRd")


def mean_line(ax, table: pd.DataFrame, style: tuple, label: str | None = None):
    color, linestyle, marker = style
    return ax.plot(
        table.Vs30_Median_m_s, table.Response_Mean, color=color,
        linestyle=linestyle, marker=marker, linewidth=2.5, markersize=4.5,
        label=label, path_effects=[effects.withStroke(linewidth=4.5, foreground="white")], zorder=4,
    )[0]


def plot_overview(frame: pd.DataFrame, response: str, tables: dict, directory: Path, dpi: int) -> list[str]:
    with matplotlib.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(14, 9), constrained_layout=True)
        hb = density(ax, frame, response)
        for index, (name, _) in enumerate(frame.groupby("Dom_Fault", sort=True)):
            mean_line(ax, tables[name], STYLES[index % len(STYLES)], fill(display_name(name), 35))
        ax.set(xlabel="Vs30 (m/s)", ylabel="Final PGA (g)" if response == "PGA_Final_g" else "Site amplification factor, AF")
        if response == "AF_760":
            ax.axhline(1, color="#666666", linestyle="--", linewidth=1.2, zorder=2)
            ax.text(0.03, 0.97, "Reference Vs30 = 760 m/s", transform=ax.transAxes, va="top", fontsize=16)
        lower, upper = ax.get_ylim()
        ax.set_ylim(lower, upper + 0.30 * (upper - lower))
        fig.colorbar(hb, ax=ax, label="Building count (log scale)")
        ax.legend(frameon=False, fontsize=24, loc="upper right", handlelength=2.5)
        stem = "pga_vs_vs30_by_controlling_fault" if response == "PGA_Final_g" else "af760_vs_vs30_hexbin"
        return save_plot(fig, directory, stem, dpi)


def plot_distance_panels(frame: pd.DataFrame, correlations: pd.DataFrame, quantiles: pd.DataFrame, directory: Path, dpi: int) -> list[str]:
    paths = []
    with matplotlib.rc_context(STYLE):
        for fault_index, (fault, sample) in enumerate(frame.groupby("Dom_Fault", sort=True)):
            groups = list(sample.groupby("Distance_Bin_Index", sort=True))
            columns = min(3, len(groups))
            rows = int(np.ceil(len(groups) / columns))
            height = 6.5 * rows + 2.6
            bottom = 2.4 / height
            fig, axes = plt.subplots(rows, columns, figsize=(7 * columns, height), sharex=True, squeeze=False)
            fig.subplots_adjust(left=0.07, right=0.88, bottom=bottom, top=0.97, hspace=0.29, wspace=0.26)
            collections, used_axes = [], []
            for ax, (bin_index, group) in zip(axes.flat, groups):
                collections.append(density(ax, group, "PGA_Final_g"))
                used_axes.append(ax)
                table = quantiles.loc[quantiles.Dom_Fault.eq(fault) & quantiles.Distance_Bin_Index.eq(bin_index)]
                mean_line(ax, table, STYLES[fault_index % len(STYLES)])
                row = correlations.loc[correlations.Dom_Fault.eq(fault) & correlations.Distance_Bin_Index.eq(bin_index)].iloc[0]
                ax.text(0.04, 0.97, f"{row.Distance_Lower_km:g}–{row.Distance_Upper_km:g} km", transform=ax.transAxes, va="top", fontsize=24)
                rho = f"{row.Spearman_rho:.3f}" if np.isfinite(row.Spearman_rho) else "not estimable"
                ax.text(0.04, 0.86, f"n = {len(group):,}\nSpearman ρ = {rho}" + ("\nSmall sample (n < 30)" if len(group) < 30 else ""), transform=ax.transAxes, va="top", fontsize=16)
                lower, upper = float(group.PGA_Final_g.min()), float(group.PGA_Final_g.max())
                span = max(upper - lower, 0.005)
                ax.set(xlabel="Vs30 (m/s)", ylabel="Final PGA (g)", ylim=(lower - 0.06 * span, upper + 0.55 * span))
            for index, ax in enumerate(axes.flat):
                if index >= len(groups):
                    ax.set_axis_off()
            low_v, high_v = float(sample.Vs30_Used_m_s.min()), float(sample.Vs30_Used_m_s.max())
            pad = max((high_v - low_v) * 0.05, 1)
            used_axes[0].set_xlim(low_v - pad, high_v + pad)
            maximum = max(2, max(float(hb.get_array().max()) for hb in collections))
            for hb in collections:
                hb.set_clim(1, maximum)
            color_ax = fig.add_axes([0.91, bottom + 0.02, 0.012, 0.93 - bottom])
            fig.colorbar(collections[0], cax=color_ax, label="Building count (log scale)")
            color, linestyle, marker = STYLES[fault_index % len(STYLES)]
            handle = Line2D(
                [], [], color=color, linestyle=linestyle, marker=marker, linewidth=2.5,
                label=display_name(fault).replace(" (middle segment)", "\n(middle segment)"),
            )
            fig.legend(handles=[handle], loc="lower center", bbox_to_anchor=(0.48, 0.005), frameon=False, fontsize=24)
            scenario = int(sample.Dom_Scenario.min())
            paths.extend(save_plot(fig, directory, f"pga_vs_vs30_fault_{scenario:03d}_distance_groups", dpi))
    return paths


def fixed_gmpe_response(model_config: dict, *, magnitude: float = FIXED_MAGNITUDE,
                        distances_km=RESPONSE_DISTANCES_KM, vs30_values=None) -> tuple[pd.DataFrame, dict]:
    """Evaluate the existing predictor with DIRECT Rrup input, with no fitting/clipping.

    The production building pipeline constructs an Rrup proxy from horizontal
    distance. This controlled sweep instead fixes the predictor's Rrup argument;
    applying that proxy conversion here would change the requested distances.
    """
    expected = {"gmpe": "Zhang2022_SWChina_PGA_simplified", "site_reference": "zero_site_term_S1_eq_S8",
                "mechanism": "strike-slip", "hanging_wall": False, "pga_units": "g"}
    for name, value in expected.items():
        if model_config.get(name) != value:
            raise ValueError(f"Existing predictor does not support configured {name}={model_config.get(name)!r}")
    if "rrup_km" not in inspect.signature(gmpe.predict_pga).parameters:
        raise ValueError("The GMPE must expose the checked Rrup distance argument")
    if not np.isfinite(magnitude):
        raise ValueError("Magnitude must be finite")
    distances = np.asarray(distances_km, dtype=float)
    velocities = np.arange(180.0, 760.25, 0.5) if vs30_values is None else np.asarray(vs30_values, dtype=float)
    if distances.ndim != 1 or not len(distances) or np.any(~np.isfinite(distances)) or np.any(distances <= 0) or len(np.unique(distances)) != len(distances):
        raise ValueError("Rrup distances must be unique, finite and positive")
    if velocities.ndim != 1 or len(velocities) < 2 or np.any(~np.isfinite(velocities)) or np.any(velocities <= 0) or np.any(np.diff(velocities) <= 0):
        raise ValueError("Vs30 values must be finite, positive and strictly increasing")
    v_min, v_max = model_config["vs30_range"]
    if not v_min <= REFERENCE_VS30 <= v_max:
        raise ValueError(f"Reference Vs30={REFERENCE_VS30:g} m/s is outside the GMPE range [{v_min:g}, {v_max:g}]; AF not computed and no extrapolation allowed")
    if velocities.min() < v_min or velocities.max() > v_max:
        raise ValueError("Requested Vs30 lies outside the configured GMPE range; no clipping or extrapolation allowed")
    r_min, r_max = model_config["rrup_range_km"]
    m_min, m_max = MECHANISM_MAGNITUDE_RANGES[model_config["mechanism"]]
    magnitude_out = not OVERALL_MAGNITUDE_RANGE[0] <= magnitude <= OVERALL_MAGNITUDE_RANGE[1]
    mechanism_out = not m_min <= magnitude <= m_max
    if magnitude_out or mechanism_out:
        raise ValueError(f"Mw={magnitude:g} is outside the supported {model_config['mechanism']} range [{m_min:g}, {m_max:g}]; no extrapolation allowed")
    if np.any((distances < r_min) | (distances > r_max)):
        raise ValueError(f"Requested Rrup is outside the GMPE range [{r_min:g}, {r_max:g}] km; no clipping or extrapolation allowed")
    ztor = float(model_config["rupture_top_depth_km"])
    if not np.isfinite(ztor) or not 0 <= ztor <= 25:
        raise ValueError("Configured rupture-top depth is outside the documented range [0, 25] km")
    frames, checks = [], []
    for distance in distances:
        # Do not call distance_proxy: R is already the GMPE's Rrup input in km.
        pga, terms = gmpe.predict_pga(magnitude, distance, velocities)
        reference, reference_terms = gmpe.predict_pga(magnitude, distance, REFERENCE_VS30)
        reference = float(reference)
        if not np.isfinite(reference) or reference <= 0 or np.any(pga <= 0):
            raise ValueError("PGA must be finite and positive")
        a1100 = terms["A1100_zero_site_g"]
        f_site = gmpe.site_term(velocities, a1100)
        f_reference = gmpe.site_term(REFERENCE_VS30, reference_terms["A1100_zero_site_g"])
        af = pga / reference
        identity_error = float(np.max(np.abs(af - np.exp(f_site - f_reference))))
        amplitude_error = float(np.max(np.abs(a1100 - reference_terms["A1100_zero_site_g"])))
        unity = float(gmpe.predict_pga(magnitude, distance, REFERENCE_VS30)[0] / reference)
        if identity_error > 1e-10 or amplitude_error > 1e-12 or abs(unity - 1) > 1e-12:
            raise ValueError("Fixed non-site terms and reference-unity checks failed")
        distance_out = not r_min <= distance <= r_max
        frames.append(pd.DataFrame({
            "Mw": magnitude, "Rrup_Input_km": distance, "Vs30_m_s": velocities,
            "PGA_g": pga, "PGA_Reference_760_g": reference, "AF_760": af,
            "A1100_Zero_Site_g": a1100, "Site_Term_ln": f_site,
            "Reference_Site_Term_ln": float(f_reference),
            "is_rrup_out_of_range": distance_out, "is_mw_out_of_range": magnitude_out,
            "is_mechanism_extrapolated": mechanism_out,
            "is_any_extrapolation": distance_out or magnitude_out or mechanism_out,
        }))
        checks.append({
            "Rrup_Input_km": float(distance), "is_rrup_out_of_range": bool(distance_out),
            "reference_pga_g": reference, "reference_AF": unity,
            "zero_site_a1100_invariance_max_error": amplitude_error,
            "af_site_term_identity_max_error": identity_error,
        })
    audit = {
        "analysis": "Controlled direct-GMPE site response, not a regression of building observations",
        "gmpe_source": str(Path(gmpe.__file__).resolve()), "gmpe_description": inspect.getdoc(gmpe),
        "predict_signature": str(inspect.signature(gmpe.predict_pga)),
        "model_configuration": model_config, "coefficients": gmpe.COEFFICIENTS,
        "fixed_magnitude_Mw": float(magnitude), "distances_Rrup_km": distances.tolist(),
        "vs30_range_m_s": [float(velocities.min()), float(velocities.max())],
        "vs30_sample_count_per_distance": len(velocities), "reference_vs30_m_s": REFERENCE_VS30,
        "distance_definition": "Rrup: closest distance to the rupture surface, in km; passed directly to rrup_km in the existing simplified predictor. No finite-rupture geometry is reconstructed.",
        "distance_policy": "Direct in-range Rrup inputs; no horizontal-distance/depth conversion, clipping or extrapolation. The building pipeline's sqrt(d_horizontal^2 + 10^2) proxy is not applied to this fixed-Rrup sweep.",
        "internal_distance_term": "(c4 + c5 * Mw) * ln(sqrt(Rrup^2 + c6^2)); existing c6=7.4 km retained",
        "applicability": {
            "source": str(APPLICABILITY_SOURCE), "section": "S1.3",
            "published_model_url": "https://doi.org/10.1016/j.soildyn.2022.107297",
            "overall_Mw_range": list(OVERALL_MAGNITUDE_RANGE), "mechanism": model_config["mechanism"],
            "mechanism_specific_Mw_range": [m_min, m_max], "Rrup_range_km": [r_min, r_max],
            "Vs30_range_m_s": [v_min, v_max], "ZTOR_range_km": [0, 25],
            "is_mw_out_of_range": magnitude_out, "is_mechanism_extrapolated": mechanism_out,
            "ZTOR_km": model_config["rupture_top_depth_km"],
            "ZTOR_in_range": 0 <= model_config["rupture_top_depth_km"] <= 25,
            "Vs30_and_reference_in_range": True,
            "all_requested_inputs_in_range": True, "out_of_range_policy": "Abort before GMPE evaluation; never clip or extrapolate",
        },
        "fixed_other_parameters": {
            "mechanism": "strike-slip", "reverse_and_normal_flags": [0, 0],
            "hanging_wall": False, "rupture_top_depth_km": model_config["rupture_top_depth_km"],
            "ZTOR_effect": "Inactive for the retained strike-slip / no-hanging-wall configuration",
            "dip_and_rupture_geometry": "Not exposed or used by the simplified predictor; no new values invented",
            "site_input_amplitude": "Existing zero-site-term A1100 approximation; constant across Vs30 at each fixed Mw/Rrup",
            "far_distance_term": "Existing rule retained; zero for all four requested distances",
            "residual": "None: median deterministic PGA in g",
        },
        "af_definition": f"PGA(Mw={magnitude:g}, Rrup=R, Vs30=V) / PGA(Mw={magnitude:g}, Rrup=R, Vs30=760 m/s)",
        "af_clipping_or_fitting": False, "per_distance_checks": checks,
    }
    return pd.concat(frames, ignore_index=True), audit


def urban_vs30_context(input_path: Path) -> dict:
    """Describe the displayed urban-site band using the project's building samples."""
    buildings = read_buildings(input_path)
    field = "Dom_Vs30" if "Dom_Vs30" in buildings else "Vs30"
    values = pd.to_numeric(buildings[field], errors="coerce").to_numpy(float)
    values = values[np.isfinite(values) & (values > 0)]
    if not len(values):
        raise ValueError("No valid building-site Vs30 samples for the urban-range annotation")
    lower, upper = URBAN_VS30_RANGE
    inside = (values >= lower) & (values <= upper)
    return {
        "source": str(input_path), "sample_field": field,
        "display_range_m_s": [lower, upper], "divider_vs30_m_s": upper,
        "observed_range_m_s": [float(values.min()), float(values.max())],
        "valid_building_count": len(values), "buildings_in_display_range": int(inside.sum()),
        "building_coverage_percent": float(inside.mean() * 100),
        "excluded_invalid_samples": len(buildings) - len(values),
        "interpretation": "Rounded descriptive band for urban building-site Vs30 samples; coverage is building-count-weighted, not land-area-weighted. Samples provide annotations only and do not alter GMPE response curves.",
    }


def draw_fixed_gmpe_response(axes, frame: pd.DataFrame, *, urban_context: dict,
                             panel_labels=("(a)", "(b)")) -> list:
    """Shared vector renderer for standalone and combined response panels."""
    lower, upper = urban_context["display_range_m_s"]
    for ax in axes:
        ax.axvspan(lower, upper, facecolor="#B8B8B8", alpha=0.16, edgecolor="none", zorder=-1)
        ax.axvline(upper, color="#62676C", linestyle=(0, (5, 4)), linewidth=1.8, zorder=1)
    for ax, label_y in zip(axes, (0.75, 0.18)):
        ax.text((lower + upper) / 2, label_y, f"Urban building sites\nVs30: {lower:g}–{upper:g} m/s",
                transform=ax.get_xaxis_transform(), ha="center", va="center", fontsize=16,
                color="#34383C", linespacing=1.35)
    handles = []
    for index, (distance, group) in enumerate(frame.groupby("Rrup_Input_km", sort=False)):
        label = f"Rrup = {distance:g} km"
        for ax, response in zip(axes, ("PGA_g", "AF_760")):
            line, = ax.plot(group.Vs30_m_s, group[response], color=RESPONSE_COLORS[index % len(RESPONSE_COLORS)],
                            linestyle="-", linewidth=3.0, label=label)
        handles.append(line)
    axes[1].axhline(1, color="#555555", linestyle=(0, (2, 3)), linewidth=1.7, zorder=0)
    axes[1].text(0.98, 0.992, "AF = 1", transform=axes[1].get_yaxis_transform(), ha="right", va="top", fontsize=16, color="#555555")
    for ax, panel in zip(axes, panel_labels):
        ax.set(xlabel="Vs30 (m/s)", xlim=(180, 760), xticks=[180, 300, upper, 400, 500, 600, 760])
        ax.text(0.035, 0.96, panel, transform=ax.transAxes, va="top", fontsize=24)
        ax.tick_params(axis="both", length=6, pad=7)
        ax.margins(y=0.12)
    axes[0].set_ylabel("PGA (g)")
    axes[1].set_ylabel("Amplification factor, AF")
    return handles


def plot_fixed_gmpe_response(frame: pd.DataFrame, audit: dict, directory: Path, dpi: int, *, urban_context: dict) -> list[str]:
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(1, 2, figsize=(20, 7.8), sharex=True)
        fig.subplots_adjust(left=0.065, right=0.985, bottom=0.28, top=0.96, wspace=0.23)
        handles = draw_fixed_gmpe_response(axes, frame, urban_context=urban_context)
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.52, 0.065),
                   ncol=4, columnspacing=1.5, handlelength=2.2, frameon=False, fontsize=24)
        note = f"Mw={audit['fixed_magnitude_Mw']:.1f}, strike-slip, reference Vs30=760 m/s"
        fig.text(0.52, 0.022, note, ha="center", va="bottom", fontsize=16)
        magnitude_tag = f"{audit['fixed_magnitude_Mw']:.1f}".replace(".", "p")
        return save_plot(fig, directory, f"gmpe_fixed_M{magnitude_tag}_vs30_pga_af_response", dpi)


def run_fixed_gmpe_response(*, input_path: Path | None = None, output_root: Path | None = None, dpi: int = 300) -> dict:
    if dpi < 100:
        raise ValueError("Use an export DPI of at least 100")
    input_path = Path(input_path or DEFAULT_INPUT).resolve()
    output_root = Path(output_root or DEFAULT_OUTPUT).resolve()
    model_config, config_source = load_model_configuration(input_path)
    protected = {Path(gmpe.__file__).resolve(), config_source, SCRIPT_ROOT / "Hazard/config.json", APPLICABILITY_SOURCE}
    if input_path.exists():
        protected.add(input_path)
    for root in (STATISTICS_ROOT / "Hazard/analysis",):
        if root.exists():
            protected.update(path for path in root.rglob("*") if path.is_file() and not path.name.startswith("."))
    before = {str(path): fingerprint(path) for path in sorted(protected) if path.exists()}
    frame, audit = fixed_gmpe_response(model_config)
    urban_context = urban_vs30_context(input_path)
    directory = new_run_directory(output_root)
    figures = figure_directory(directory / "figures")
    paths = plot_fixed_gmpe_response(frame, audit, figures, dpi, urban_context=urban_context)
    write_json(directory / "urban_vs30_context.json", urban_context)
    frame.to_csv(directory / "gmpe_fixed_response_grid.csv", index=False, encoding="utf-8-sig")
    summaries, examples = [], []
    for distance, group in frame.groupby("Rrup_Input_km", sort=False):
        peak = group.loc[group.PGA_g.idxmax()]
        soft = group.loc[group.Vs30_m_s.between(190, 350)]
        summaries.append({
            "Rrup_Input_km": distance, "PGA_Reference_760_g": float(group.PGA_Reference_760_g.iloc[0]),
            "A1100_Zero_Site_g": float(group.A1100_Zero_Site_g.iloc[0]),
            "AF_Min": float(group.AF_760.min()), "AF_Max": float(group.AF_760.max()),
            "Vs30_At_Sampled_PGA_Max_m_s": float(peak.Vs30_m_s),
            "AF_Min_Within_Vs30_190_350": float(soft.AF_760.min()),
            "AF_Max_Within_Vs30_190_350": float(soft.AF_760.max()),
            "is_rrup_out_of_range": bool(group.is_rrup_out_of_range.iloc[0]),
            "is_mechanism_extrapolated": bool(group.is_mechanism_extrapolated.iloc[0]),
        })
        for velocity in (190., 200., 350., 760.):
            row = group.loc[group.Vs30_m_s.eq(velocity)].iloc[0]
            examples.append({field: float(row[field]) for field in ("Mw", "Rrup_Input_km", "Vs30_m_s", "PGA_g", "PGA_Reference_760_g", "AF_760")})
    summary = pd.DataFrame(summaries)
    summary.to_csv(directory / "gmpe_fixed_response_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(examples).to_csv(directory / "gmpe_response_examples.csv", index=False, encoding="utf-8-sig")
    write_json(directory / "gmpe_response_audit.json", audit)
    changed = [name for name, old in before.items() if not Path(name).exists() or fingerprint(Path(name))["sha256"] != old["sha256"]]
    write_json(directory / "preservation_check.json", {
        "protected_file_count": len(before), "all_original_results_unchanged": not changed,
        "changed_existing_files": changed, "fingerprints": list(before.values()),
    })
    manifest = {
        "status": "complete" if not changed else "existing_files_changed_during_run",
        "analysis_mode": "fixed-response", "run_directory": str(directory),
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "analysis_code": fingerprint(Path(__file__).resolve()), "gmpe_code": before[str(Path(gmpe.__file__).resolve())],
        "model_configuration_source": str(config_source), "model_configuration": model_config,
        "building_data_used_for_response_or_fitting": False,
        "building_data_used_for_annotation_only": True, "urban_vs30_context": urban_context,
        "fixed_magnitude_Mw": FIXED_MAGNITUDE, "Rrup_distances_km": list(RESPONSE_DISTANCES_KM),
        "vs30_range_m_s": list(RESPONSE_VS30_RANGE), "vs30_step_m_s": 0.5,
        "grid_row_count": len(frame), "reference_vs30_m_s": REFERENCE_VS30, "af_supported": True,
        "figure_paths": paths, "dpi": dpi, "summary": summaries,
        "style": {"background": "white", "font": "Arial Bold", "axis_labels_pt": 24, "ticks_pt": 16,
                  "legend_pt": 24, "panel_labels_pt": 24, "condition_notes_pt": 16, "figure_title": None,
                  "distance_colors": list(RESPONSE_COLORS), "curve_linestyle": "solid",
                  "parameter_note": "Mw=6.0, strike-slip, reference Vs30=760 m/s",
                  "urban_range_band": "Light gray; 190–350 m/s", "urban_range_divider": "Vertical dashed line at 350 m/s",
                  "urban_range_label_pt": 16},
        "all_requested_inputs_in_range": audit["applicability"]["all_requested_inputs_in_range"],
        "preservation_check_passed": not changed, "protected_existing_file_count": len(before),
    }
    write_json(directory / "analysis_metadata.json", manifest)
    report = [
        "# Fixed-magnitude GMPE site response", "",
        "The existing Hazard/model.py predictor was evaluated directly at Mw = 6.0 and Rrup = 10, 15, 20 and 30 km over Vs30 = 180–760 m/s in 0.5 m/s increments. No building scatter, fitted curve, quantile mean or interpolation model was used to calculate PGA.", "",
        "AF(V, R) = PGA(6.0, R, V) / PGA(6.0, R, 760 m/s). Each distance has its own matched reference PGA. All curves equal one at Vs30 = 760 m/s; AF values below one are retained.", "",
        "## Urban building-site Vs30 context", "",
        f"A light-gray band marks the rounded interval 190–350 m/s in both panels; a vertical dashed divider marks its upper boundary at 350 m/s. This interval contains {urban_context['buildings_in_display_range']:,} of {urban_context['valid_building_count']:,} valid building-site samples ({urban_context['building_coverage_percent']:.2f}%). The complete observed range is {urban_context['observed_range_m_s'][0]:.1f}–{urban_context['observed_range_m_s'][1]:.1f} m/s. Coverage is measured by building count, not land area. The building samples supply only this descriptive annotation; the GMPE response calculation remains unchanged. Source, field and exact coverage are saved in urban_vs30_context.json.", "",
        "## Distance and applicability", "",
        "R is the GMPE Rrup argument (closest distance to the rupture surface, km), not epicentral distance, hypocentral distance, Joyner–Boore distance or horizontal fault-trace distance. The existing simplified predictor retains its internal sqrt(Rrup^2 + 7.4^2) distance-saturation term. This response sweep does not reconstruct finite ruptures.", "",
        "The building workflow uses sqrt(d_horizontal^2 + 10^2) as an Rrup proxy, with a 10 km lower bound. This controlled sweep passes the specified Rrup values directly; it applies neither a horizontal-distance conversion nor clipping. The previous 5 km curve is excluded from this new figure. Earlier result files remain preserved.", "",
        f"Documented ranges: Rrup {model_config['rrup_range_km'][0]:g}–{model_config['rrup_range_km'][1]:g} km; Vs30 {model_config['vs30_range'][0]:g}–{model_config['vs30_range'][1]:g} m/s; overall Mw 4.2–7.9; strike-slip Mw 4.2–6.1; ZTOR 0–25 km. Mw = 6.0, all four Rrup distances, all scanned Vs30 values, the 760 m/s reference, and configured ZTOR = 1 km are within these ranges. The retained strike-slip and disabled-hanging-wall settings are supported by the existing simplified predictor. Dip and finite-rupture geometry are not exposed inputs. These checks establish range compliance for this implementation, not independent validation of the model.", "",
        "The calculation aborts before GMPE evaluation if the reference Vs30, swept Vs30, magnitude, Rrup or configured ZTOR falls outside its documented range. No reference extrapolation is permitted.", "",
        f"The applicability ranges are recorded in {APPLICABILITY_SOURCE}, section S1.3. The published model is [Zhang et al. (2022)](https://doi.org/10.1016/j.soildyn.2022.107297).", "",
        "## Why AF can be below one", "",
        "For all velocities used here V < VLIN = 865.095 m/s. The existing nonlinear branch is:", "",
        "f_site(V, A) = c10 ln(V/VLIN) + k2 {ln[A + c (V/VLIN)^n] − ln(A + c)}.", "",
        "AF = exp[f_site(V, A) − f_site(760, A)], with c10 = 1.071, k2 = −1.186, n = 1.18 and c = 1.88. A is the existing zero-site-term A1100 amplitude, determined by magnitude and Rrup; it remains fixed while Vs30 varies at each distance. The log-velocity slope is c10 + k2 n c (V/VLIN)^n / [A + c (V/VLIN)^n]. This slope depends on A, so the response need not increase monotonically as Vs30 decreases. Under stronger input, the nonlinear term can produce a lower predicted PGA at soft Vs30 than at the 760 m/s reference. AF is a relative PGA ratio, not a guarantee of amplification above one.", "",
        "The model retains the manuscript's zero-site-term A1100 approximation. The curves explain this implementation's behavior; they do not independently demonstrate the response of actual buildings or validate the full published model.", "",
        "## Direct model examples", "",
        "| Rrup (km) | PGA at Vs30=200 (g) | PGA at Vs30=760 (g) | AF at Vs30=200 | Distance range |", "|---:|---:|---:|---:|---|",
    ]
    for row in examples:
        if row["Vs30_m_s"] == 200:
            status = "Inside"
            report.append(f"| {row['Rrup_Input_km']:g} | {row['PGA_g']:.6f} | {row['PGA_Reference_760_g']:.6f} | {row['AF_760']:.6f} | {status} |")
    report += ["", "All rows use strike-slip Mw = 6.0, inside the mechanism-specific magnitude range.", "",
               "## Reproducibility and preservation", "",
               "Strike-slip mechanism, disabled hanging wall, configured ZTOR = 1 km, zero residuals, PGA units g, the A1100 approximation, and all existing coefficients are retained. ZTOR is inactive for this mechanism. The simplified predictor does not expose dip or finite-rupture geometry. Source hashes, full configuration, per-distance reference/site-term checks and applicability flags are saved in the JSON audits and grid CSV.", "",
               f"SHA-256 checks covered {len(before)} pre-existing files, including the model/configuration, available input data and other current analysis outputs. Numeric results update the fixed current directory; figures update the corresponding plot/shared/output directory. Preservation passed: {not changed}.", "",
               "The 1×2 figure has no overall title. Panel (a) is Vs30–PGA; panel (b) is Vs30–AF with AF=1. English labels, white background, bold Arial, 24 pt axis/legend/panel labels and 16 pt ticks/notes are used. A single-row distance legend and one short parameter note replace the earlier long annotations: Mw=6.0, strike-slip, reference Vs30=760 m/s. PNG, PDF and SVG copies are provided."]
    (directory / "analysis_summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if changed:
        raise RuntimeError(f"Existing inputs/results changed during execution; inspect {directory / 'preservation_check.json'}")
    return manifest


def run_site_effect_analysis(buildings: pd.DataFrame | None = None, *, input_path: Path | None = None, output_root: Path | None = None, distance_bin_km: float = 5.0, quantiles: int = 20, dpi: int = 300, mode: str = "fixed-response") -> dict:
    if mode == "fixed-response":
        return run_fixed_gmpe_response(input_path=input_path, output_root=output_root, dpi=dpi)
    if mode != "stratified":
        raise ValueError(f"Unknown site-analysis mode: {mode}")
    if quantiles < 2 or dpi < 100:
        raise ValueError("Use at least two quantiles and an export DPI of at least 100")
    input_path = Path(input_path or DEFAULT_INPUT).resolve()
    model_config, config_source = load_model_configuration(input_path)
    legacy = STATISTICS_ROOT / "Hazard/analysis"
    protected = [input_path, *sorted(path for path in legacy.rglob("*") if path.is_file() and not path.name.startswith("."))]
    before = {str(path): fingerprint(path) for path in protected}
    frame, excluded = prepare_buildings(read_buildings(input_path) if buildings is None else buildings, model_config, distance_bin_km)
    frame, audit = matched_amplification(frame, model_config)
    directory = new_run_directory(Path(output_root or DEFAULT_OUTPUT / "stratified").resolve())
    figures = figure_directory(directory / "figures")
    correlations, grouped_quantiles = [], []
    for (fault, index), group in frame.groupby(["Dom_Fault", "Distance_Bin_Index"], sort=True):
        identifiers = {
            "Dom_Fault": fault, "Fault_Name_Display": display_name(fault), "Distance_Bin_Index": int(index),
            "Distance_Lower_km": float(group.Distance_Lower_km.iloc[0]), "Distance_Upper_km": float(group.Distance_Upper_km.iloc[0]),
        }
        correlations.append({**identifiers, **spearman_summary(group), "Vs30_Min_m_s": float(group.Vs30_Used_m_s.min()), "Vs30_Max_m_s": float(group.Vs30_Used_m_s.max())})
        grouped_quantiles.append(quantile_summary(group, "PGA_Final_g", quantiles).assign(**identifiers))
    correlations = pd.DataFrame(correlations)
    grouped_quantiles = pd.concat(grouped_quantiles, ignore_index=True)
    if int(correlations.Building_Count.sum()) != len(frame):
        raise ValueError("Distance groups must partition the valid building inventory")
    raw_tables = {fault: quantile_summary(group, "PGA_Final_g", quantiles) for fault, group in frame.groupby("Dom_Fault", sort=True)}
    paths = plot_overview(frame, "PGA_Final_g", raw_tables, figures, dpi)
    paths.extend(plot_distance_panels(frame, correlations, grouped_quantiles, figures, dpi))
    tables = {
        "building_site_effects.csv": frame, "excluded_buildings.csv": excluded,
        "pga_vs30_fault_distance_spearman.csv": correlations,
        "pga_vs30_fault_distance_quantiles.csv": grouped_quantiles,
        "pga_vs30_fault_quantiles.csv": pd.concat([table.assign(Dom_Fault=fault) for fault, table in raw_tables.items()], ignore_index=True),
        "pga_vs30_fault_spearman.csv": pd.DataFrame([{ "Dom_Fault": fault, **spearman_summary(group)} for fault, group in frame.groupby("Dom_Fault", sort=True)]),
    }
    af_summary = pd.DataFrame()
    if audit["supported"]:
        af_tables = {fault: quantile_summary(group, "AF_760", quantiles) for fault, group in frame.groupby("Dom_Fault", sort=True)}
        paths.extend(plot_overview(frame, "AF_760", af_tables, figures, dpi))
        tables["af760_vs30_fault_quantiles.csv"] = pd.concat([table.assign(Dom_Fault=fault) for fault, table in af_tables.items()], ignore_index=True)
        af_summary = frame.groupby("Fault_Name_Display").AF_760.agg(Building_Count="size", AF_Min="min", AF_Median="median", AF_Mean="mean", AF_Max="max").reset_index()
        tables["af760_fault_summary.csv"] = af_summary
    for name, table in tables.items():
        table.to_csv(directory / name, index=False, encoding="utf-8-sig", na_rep="NA")
    write_json(directory / "gmpe_reference_audit.json", audit)
    after = {str(path): fingerprint(path) for path in protected}
    changed = [path for path in before if before[path]["sha256"] != after[path]["sha256"]]
    preservation = {"protected_file_count": len(protected), "changed_existing_files": changed, "all_original_results_unchanged": not changed, "fingerprints": list(before.values())}
    write_json(directory / "preservation_check.json", preservation)
    limitations = [
        "The existing SCS GMPE uses the manuscript's zero-site-term A1100 approximation, not a full finite-rupture Zhang2022 implementation.",
        "AF is a paired model counterfactual under the original controlling scenario, not an independently observed or causally identified amplification.",
        "The 760 m/s reference is inside the configured GMPE Vs30 range; its position relative to the observed inventory range is recorded in the metadata.",
        "Distance stratification reduces source-distance mixing but does not fully adjust for distance variation inside each bin or other spatial covariates.",
        "The nonlinear site term also depends on source/distance-dependent input amplitude; the quantile curves describe this inventory rather than a universal Vs30 transfer function.",
        "Spearman p-values are unadjusted descriptive values; buildings share coarse Vs30 samples and are spatially dependent.",
        "Undefined constant-Vs30 correlations and small samples are flagged; AF values below one are not clipped.",
        "Original GMPE magnitude, mechanism, distance, Vs30 imputation and clipping flags are retained in the building table.",
    ]
    manifest = {
        "status": "complete" if not changed else "input_or_legacy_files_changed_during_run",
        "run_directory": str(directory), "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "input": before[str(input_path)], "model_configuration_source": str(config_source),
        "analysis_code": fingerprint(Path(__file__).resolve()), "gmpe_code": fingerprint(Path(gmpe.__file__).resolve()),
        "valid_building_count": len(frame), "excluded_building_count": len(excluded),
        "fault_count": frame.Dom_Fault.nunique(), "distance_bin_width_km": distance_bin_km,
        "distance_definition": "Horizontal building-to-fault distance recovered from the stored sqrt(d^2 + depth^2) Rrup proxy", "equivalent_depth_km": model_config["equivalent_depth_km"],
        "distance_interval_rule": "Left closed, right open, with shared fixed-width physical bins starting at zero",
        "quantile_count_requested": quantiles, "quantile_policy": "Within each fault/distance group; duplicate edges dropped and constant Vs30 represented by one bin",
        "af_supported": audit["supported"], "reference_vs30_m_s": REFERENCE_VS30,
        "observed_vs30_range_m_s": [float(frame.Vs30_Used_m_s.min()), float(frame.Vs30_Used_m_s.max())],
        "reference_outside_observed_vs30_range": not float(frame.Vs30_Used_m_s.min()) <= REFERENCE_VS30 <= float(frame.Vs30_Used_m_s.max()),
        "figure_paths": paths, "tables": list(tables), "dpi": dpi,
        "style": {"palette": "YlOrRd", "background": "white", "font": "Arial Bold", "axis_and_colorbar_labels_pt": 24, "ticks_pt": 16, "legend_pt": 24, "figure_titles": None, "distance_panel_axes": "Shared Vs30 axes within each fault; individual PGA axes to resolve within-group variation"},
        "correlation_groups": json.loads(correlations.to_json(orient="records")),
        "af_fault_summary": json.loads(af_summary.to_json(orient="records")),
        "original_model_flags": {column: int(pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(bool).sum()) for column in frame if column.startswith("is_")},
        "limitations": limitations, "preservation_check_passed": not changed,
    }
    write_json(directory / "analysis_metadata.json", manifest)
    report = ["# PGA–Vs30 site-effect analysis", "", f"Valid buildings: {len(frame):,}; controlling faults: {frame.Dom_Fault.nunique()}; distance-bin width: {distance_bin_km:g} km.", "", "## Matched reference calculation", "", audit["reason"], "", audit["reference_policy"], "", "AF = PGA(Mw_i, Rrup_i, Vs30_i) / PGA(Mw_i, Rrup_i, 760 m/s).", "", "## Interpretation limits", "", *["- " + item for item in limitations]]
    report += ["", "## Fault and distance strata", "", "| Controlling fault | Horizontal distance (km) | Buildings | Spearman rho | Status |", "|---|---:|---:|---:|---|"]
    for row in correlations.itertuples():
        rho = f"{row.Spearman_rho:.3f}" if np.isfinite(row.Spearman_rho) else "NA"
        report.append(f"| {row.Fault_Name_Display} | [{row.Distance_Lower_km:g}, {row.Distance_Upper_km:g}) | {row.Building_Count:,} | {rho} | {row.Correlation_Status} |")
    if audit["supported"]:
        report += ["", "## Model-derived AF by controlling fault", "", "| Controlling fault | Buildings | Minimum AF | Median AF | Maximum AF |", "|---|---:|---:|---:|---:|"]
        for row in af_summary.itertuples():
            report.append(f"| {row.Fault_Name_Display} | {row.Building_Count:,} | {row.AF_Min:.4f} | {row.AF_Median:.4f} | {row.AF_Max:.4f} |")
        report += ["", f"Stored PGA replay maximum absolute error: {audit['stored_pga_replay_max_absolute_error_g']:.3g} g."]
    report += ["", "## Reproducibility", "", "The source GeoPackage and all pre-existing analysis outputs passed SHA-256 preservation checks. See gmpe_reference_audit.json, analysis_metadata.json and preservation_check.json for the model, source hashes, plotting settings and inherited flags.", "", "Figures are available as PNG, PDF and SVG in the figures directory. Distance panels use individual PGA limits; their Vs30 axes and count color scale are shared within each controlling fault."]
    (directory / "analysis_summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if changed:
        raise RuntimeError(f"Existing inputs/results changed during execution; inspect {directory / 'preservation_check.json'}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--distance-bin-km", type=float, default=5.0)
    parser.add_argument("--quantiles", type=int, default=20)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--mode", choices=("fixed-response", "stratified"), default="fixed-response",
                        help="Direct GMPE response (default), or the earlier building-stratified analysis.")
    args = parser.parse_args()
    manifest = run_site_effect_analysis(input_path=args.input, output_root=args.output_root, distance_bin_km=args.distance_bin_km, quantiles=args.quantiles, dpi=args.dpi, mode=args.mode)
    print(json.dumps({key: manifest[key] for key in ("run_directory", "analysis_mode", "valid_building_count", "fault_count", "grid_row_count", "af_supported", "preservation_check_passed", "figure_paths") if key in manifest}, indent=2))


if __name__ == "__main__":
    main()
