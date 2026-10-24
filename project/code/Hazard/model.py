"""SCS Supplementary Note S1, Eqs. S3–S9; PGA in g, natural logarithms.

This implements the manuscript's disclosed zero-site-term A1100 approximation.
It is not a finite-rupture or full Zhang2022 implementation.
"""

import numpy as np

COEFFICIENTS = {
    "c0": .766, "c1": .143, "c2": .885, "c3": -.877,
    "c4": -2.129, "c5": .100, "c6": 7.400, "c7": .404,
    "c8": -.260, "c9": 1.021, "c10": 1.071, "c11": .0003,
    "VLIN": 865.095, "k2": -1.186, "n": 1.18, "c": 1.88,
    "V1": 1100.,
}


def magnitude_term(magnitude):
    m, c = np.asarray(magnitude, dtype=float), COEFFICIENTS
    return (c["c0"] + c["c1"] * m + c["c2"] * np.maximum(m - 5.5, 0.)
            + c["c3"] * np.maximum(m - 6.5, 0.))


def distance_proxy(horizontal_km, depth_km=10., minimum_km=10.):
    d = np.asarray(horizontal_km, dtype=float)
    if np.any(~np.isfinite(d)) or np.any(d < 0) or depth_km <= 0 or minimum_km <= 0:
        raise ValueError("Invalid horizontal distance/depth/lower bound")
    raw = np.sqrt(d ** 2 + depth_km ** 2)
    return raw, np.maximum(raw, minimum_km)


def site_term(velocity, a1100):
    c = COEFFICIENTS
    v = np.asarray(velocity, dtype=float) / c["VLIN"]
    nonlinear = (c["c10"] * np.log(v) + c["k2"] *
                 (np.log(a1100 + c["c"] * v ** c["n"])
                  - np.log(a1100 + c["c"])))
    linear = (c["c10"] + c["k2"] * c["n"]) * np.log(v)
    saturated = (c["c10"] + c["k2"] * c["n"]) * np.log(c["V1"] / c["VLIN"])
    return np.where(v < 1., nonlinear,
                    np.where(np.asarray(velocity) < c["V1"], linear, saturated))


def predict_pga(magnitude, rrup_km, vs30):
    m, r, v = np.broadcast_arrays(np.asarray(magnitude, dtype=float),
                                   np.asarray(rrup_km, dtype=float),
                                   np.asarray(vs30, dtype=float))
    if np.any(~np.isfinite(m)) or np.any(~np.isfinite(r)) or np.any(r <= 0):
        raise ValueError("Magnitude/distance must be finite; distance must be positive")
    if np.any(~np.isfinite(v)) or np.any(v <= 0):
        raise ValueError("Vs30 must be finite and positive")
    c = COEFFICIENTS
    f_mag = magnitude_term(m)
    f_dis = (c["c4"] + c["c5"] * m) * np.log(np.sqrt(r ** 2 + c["c6"] ** 2))
    f_atn = np.where((r > 80.) & (m >= 6.5), c["c11"] * (r - 80.), 0.)
    # S1: all scenarios strike slip, hanging wall disabled; both terms are zero.
    a1100 = np.exp(f_mag + f_dis + f_atn)
    f_site = site_term(v, a1100)
    ln_pga = f_mag + f_dis + f_site + f_atn
    pga = np.exp(ln_pga)
    if np.any(~np.isfinite(pga)):
        raise ValueError("GMPE produced non-finite PGA")
    return pga, {"lnPGA_Zhang2022": ln_pga, "A1100_zero_site_g": a1100}
