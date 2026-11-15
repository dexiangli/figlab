"""Apparent Mott–Schottky coordinates and exploratory common-window fits."""
from itertools import groupby

import numpy as np

from .base import SpectrumProcessor, register

SCALE = 1e12


def inverse_capacitance_squared(row, model="series"):
    imag = float(row["Zpp_ohm"])
    if imag >= 0:
        raise ValueError("Negative imaginary impedance is required")
    impedance = imag
    if model == "parallel":
        impedance = (float(row["Zp_ohm"]) ** 2 + imag ** 2) / imag
    return (2 * np.pi * float(row["freq_Hz"]) * impedance) ** 2 / SCALE


def common_window(curves, model="series"):
    """Longest shared positive-slope window, >=8 points per curve and R²>=0.98."""
    by_curve = {name: {float(row["potential_V"]): row for row in rows}
                for name, rows in curves.items()}
    if not by_curve:
        return {}
    shared = set.intersection(*(set(rows) for rows in by_curve.values()))
    x = np.array(sorted(shared))
    valid = np.array([all(float(rows[v]["Zpp_ohm"]) < 0 for rows in by_curve.values())
                      for v in x], dtype=bool)
    y = np.array([[inverse_capacitance_squared(rows[v], model) if ok else np.nan
                   for v, ok in zip(x, valid)] for rows in by_curve.values()])
    # A missing or non-capacitive point must break a contiguous sweep window.
    steps = [abs(b - a) for rows in by_curve.values()
             for a, b in zip(sorted(rows), sorted(rows)[1:])]
    if not steps:
        return {}
    split = np.flatnonzero(np.diff(x) > min(steps) * 1.01) + 1
    runs = [list(indices) for sweep in np.split(np.arange(len(x)), split)
            for ok, indices in groupby(sweep, key=lambda i: valid[i]) if ok]
    for count in range(max(map(len, runs), default=0), 7, -1):
        candidates = []
        for run in runs:
            for start in range(len(run) - count + 1):
                window = run[start:start + count]
                voltage, values = x[window], y[:, window]
                slope, intercept = np.polyfit(voltage, values.T, 1)
                variance = ((values - values.mean(axis=1, keepdims=True)) ** 2).sum(axis=1)
                if np.any(slope <= 0) or np.any(variance <= 0):
                    continue
                residual = values - slope[:, None] * voltage - intercept[:, None]
                r2 = 1 - (residual ** 2).sum(axis=1) / variance
                if np.min(r2) >= 0.98:
                    candidates.append((float(np.min(r2)), voltage, slope, intercept, r2))
        if candidates:
            _, voltage, slopes, intercepts, r2s = max(candidates, key=lambda item: item[0])
            return {name: dict(kind="fit", disclaimer="Exploratory linear fit",
                               x_from=float(voltage[0]), x_to=float(voltage[-1]),
                               n=count, slope=float(slope), intercept=float(intercept),
                               zero_V=float(-intercept / slope), r2=float(r2))
                    for name, slope, intercept, r2 in zip(by_curve, slopes, intercepts, r2s)}
    return {}


def shared_intercept_window(curves, bounds):
    """Fit positive slopes with a common zero on an explicit sweep interval."""
    lo, hi = bounds
    sweeps = {
        name: {round(float(row["potential_V"]), 6): row for row in rows
               if lo - 1e-6 <= float(row["potential_V"]) <= hi + 1e-6}
        for name, rows in curves.items()
    }
    voltage = np.array(sorted(next(iter(sweeps.values()), {})))
    if (len(voltage) < 5 or abs(voltage[0] - lo) > 1e-6 or abs(voltage[-1] - hi) > 1e-6
            or not np.allclose(np.diff(voltage), np.diff(voltage)[0], atol=1e-6)
            or any(set(rows) != set(voltage) for rows in sweeps.values())):
        raise ValueError("Shared fit requires at least five matching consecutive voltages")
    values = np.array([[inverse_capacitance_squared(rows[v]) for v in voltage]
                       for rows in sweeps.values()])
    slopes, intercepts = np.polyfit(voltage, values.T, 1)
    variance = ((values - values.mean(axis=1, keepdims=True)) ** 2).sum(axis=1)
    if np.any(slopes <= 0) or np.any(variance <= 0):
        raise ValueError("Shared fit requires positive independent slopes")
    zeros = -intercepts / slopes
    if np.any(zeros >= voltage[0]):
        raise ValueError("Independent intercepts must precede the fit interval")

    def fit_at(zero):
        delta = voltage - zero
        slopes = (values @ delta) / (delta @ delta)
        residual = values - slopes[:, None] * delta
        return slopes, 1 - (residual ** 2).sum(axis=1) / variance

    lower, upper = min(zeros), max(zeros)
    for _ in range(60):
        a, b = (2 * lower + upper) / 3, (lower + 2 * upper) / 3
        if fit_at(a)[1].mean() < fit_at(b)[1].mean():
            lower = a
        else:
            upper = b
    zero = (lower + upper) / 2
    slopes, r2s = fit_at(zero)
    return {
        name: dict(kind="fit", disclaimer="Shared-intercept fit of series apparent capacitance",
                   x_from=float(voltage[0]), x_to=float(voltage[-1]), n=len(voltage),
                   slope=float(slope), intercept=float(-slope * zero), zero_V=float(zero),
                   independent_zero_V=float(independent), r2=float(r2))
        for name, slope, independent, r2 in zip(sweeps, slopes, zeros, r2s)
    }


@register
class MottSchottkyProcessor(SpectrumProcessor):
    name = "mott_schottky"

    def geometry(self, rows):
        return {"n_points": len(rows),
                "noncapacitive_points": sum(float(row["Zpp_ohm"]) >= 0 for row in rows)}

    def truncate(self, rows, geom, tail):
        return [row for row in rows if float(row["Zpp_ohm"]) < 0]
