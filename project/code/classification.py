"""Shared deterministic five-class Jenks classification for H, E, V and R.

Jenks dynamic programming minimizes within-class squared deviations on up to
2,000 equally spaced probability-quantile representatives. Breaks are then
applied to every original observation; class population shares are not fixed.
All intervals are upper-inclusive, with the first also including its minimum.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CLASS_NAMES = ["Very Low", "Low", "Moderate", "High", "Very High"]
CLASS_COLORS = ["#FFF7BC", "#FEE391", "#FEC44F", "#FC4E2A", "#BD0026"]
JENKS_METHOD = "Deterministic Jenks dynamic programming on up to 2,000 probability-quantile representatives, applied to all observations; upper-inclusive intervals."


def jenks_breaks(values, classes: int = 5, max_values: int = 2000) -> list[float]:
    data = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(float)
    data = np.sort(data[np.isfinite(data)])
    if classes < 1 or max_values < classes or len(np.unique(data)) < classes:
        raise ValueError("Jenks requires at least one distinct value per class and enough representatives")
    if len(data) > max_values:
        data = np.quantile(data, np.linspace(0, 1, max_values))
    if len(np.unique(data)) < classes:
        raise ValueError("Too few distinct Jenks representatives")
    # Centering reduces cancellation without changing squared-deviation costs.
    centered = data - data.mean()
    n = len(data)
    sums = np.r_[0.0, np.cumsum(centered)]
    squares = np.r_[0.0, np.cumsum(centered * centered)]
    previous = np.full(n + 1, np.inf)
    previous[0] = 0.0
    back = np.zeros((classes + 1, n + 1), dtype=np.int32)
    for group in range(1, classes + 1):
        current = np.full(n + 1, np.inf)
        for end in range(group, n + 1):
            starts = np.arange(group - 1, end)
            cost = squares[end] - squares[starts] - (sums[end] - sums[starts]) ** 2 / (end - starts)
            scores = previous[starts] + np.maximum(cost, 0.0)
            best = int(np.argmin(scores))
            current[end] = scores[best]
            back[group, end] = starts[best]
        previous = current
    end = n
    cuts = []
    for group in range(classes, 1, -1):
        start = int(back[group, end])
        cuts.append(float(data[start - 1]))
        end = start
    breaks = [float(data[0]), *reversed(cuts), float(data[-1])]
    if not np.all(np.diff(breaks) > 0):
        raise ValueError("Jenks did not produce distinct class boundaries")
    return breaks


def classify(values, breaks: list[float], names: list[str] | None = None) -> pd.Series:
    values = pd.Series(values)
    names = CLASS_NAMES if names is None else names
    if len(breaks) != len(names) + 1 or not np.all(np.diff(breaks) > 0):
        raise ValueError("Invalid class boundaries")
    numeric = pd.to_numeric(values, errors="coerce")
    labels = pd.Series("Invalid", index=values.index, dtype=object)
    finite = np.isfinite(numeric) & numeric.between(breaks[0], breaks[-1])
    indices = np.searchsorted(breaks[1:-1], numeric.loc[finite], side="left")
    labels.loc[finite] = np.asarray(names)[indices]
    return labels


def range_labels(breaks: list[float], precision: int = 3, unit: str = "") -> list[str]:
    suffix = f" {unit}" if unit else ""
    return [f"≤ {breaks[1]:.{precision}f}{suffix}",
            *[f"{low:.{precision}f}–{high:.{precision}f}{suffix}"
              for low, high in zip(breaks[1:-2], breaks[2:-1])],
            f"> {breaks[-2]:.{precision}f}{suffix}"]
