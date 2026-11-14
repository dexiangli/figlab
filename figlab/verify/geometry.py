# -*- coding: utf-8 -*-
"""几何核验（规范 §七.1）：从导出位图反算图框像素位置，换算厘米与四边页边距，
与规格逐项比对；再把每个数据点按坐标映射投到像素，检查该位置是否存在该曲线
颜色，以发现某条曲线被后画曲线整段压住的情况。
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from PIL import Image


def hex2rgb(s: str) -> np.ndarray:
    s = s.lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def _match(patch: np.ndarray, target: np.ndarray, cos_thr: float = 0.96,
           sat_thr: float = 25.0) -> np.ndarray:
    """抗锯齿鲁棒的颜色匹配：方向余弦 + 饱和度，而不是精确 RGB 相等。"""
    t = target / (np.linalg.norm(target) + 1e-9)
    v = patch / 255.0
    n = np.linalg.norm(v, axis=2)
    cos = (v @ t) / (n + 1e-9)
    sat = patch.max(2) - patch.min(2)
    return (cos > cos_thr) & (sat > sat_thr)


def frame_from_png(path: str, page_cm: list[float]) -> dict:
    """找四边框的长直线 → 反算图框像素位置与四边页边距（单位 cm）。"""
    im = np.array(Image.open(path).convert("RGB"))
    h, w = im.shape[:2]
    dpi_x = w / (page_cm[0] / 2.54)
    dpi_y = h / (page_cm[1] / 2.54)
    dpi = (dpi_x + dpi_y) / 2.0
    dark = im.sum(2) < 200
    rows = np.where(dark.sum(1) > 0.5 * w)[0]
    cols = np.where(dark.sum(0) > 0.5 * h)[0]
    if len(rows) < 2 or len(cols) < 2:
        raise RuntimeError("位图中未检出四边框长直线，无法反算图框")
    fx0, fx1 = int(cols.min()), int(cols.max())
    fy0, fy1 = int(rows.min()), int(rows.max())
    return {
        "image_px": [w, h], "effective_dpi": round(dpi, 2),
        "frame_px": [fx0, fy0, fx1, fy1],
        "frame_size_px": [fx1 - fx0, fy1 - fy0],
        "margins_cm": {
            "left": fx0 / dpi * 2.54,
            "top": fy0 / dpi * 2.54,
            "right": (w - 1 - fx1) / dpi * 2.54,
            "bottom": (h - 1 - fy1) / dpi * 2.54,
        },
        "frame_size_cm": [(fx1 - fx0) / dpi * 2.54,
                          (fy1 - fy0) / dpi * 2.54],
    }


def compare_frame(measured: dict, spec: dict, tol_cm: float = 0.05) -> dict:
    w, h = spec["page"]["w_cm"], spec["page"]["h_cm"]
    L = spec["layer"]
    want_m = {
        "left": w * L["left"] / 100, "top": h * L["top"] / 100,
        "right": w * (100 - L["left"] - L["width"]) / 100,
        "bottom": h * (100 - L["top"] - L["height"]) / 100,
    }
    want_f = [w * L["width"] / 100, h * L["height"] / 100]
    rows, ok = [], True
    for k, want in want_m.items():
        got = measured["margins_cm"][k]
        err = abs(got - want)
        passed = err <= tol_cm
        ok &= passed
        rows.append({"item": "margin_" + k, "got_cm": round(got, 4),
                     "want_cm": round(want, 4), "err_cm": round(err, 4),
                     "tol_cm": tol_cm, "ok": passed})
    for i, k in enumerate(("frame_w", "frame_h")):
        got, want = measured["frame_size_cm"][i], want_f[i]
        err = abs(got - want)
        passed = err <= tol_cm
        ok &= passed
        rows.append({"item": k, "got_cm": round(got, 4),
                     "want_cm": round(want, 4), "err_cm": round(err, 4),
                     "tol_cm": tol_cm, "ok": passed})
    return {"ok": ok, "tolerance_cm": tol_cm, "items": rows}


def color_hit_rates(path: str, points: list[dict], radii=(4, 12)) -> dict:
    """每个数据点投到像素，检查该位置是否存在本曲线颜色。

    radius=4 严格（点中心是否被后画曲线盖住），radius=12 宽松（符号邻域）。
    """
    im = np.array(Image.open(path).convert("RGB")).astype(float)
    H, W = im.shape[:2]
    out = {r: defaultdict(lambda: [0, 0]) for r in radii}
    for p in points:
        px = int(round(p["nx"] * W))
        py = int(round(p["ny"] * H))
        target = hex2rgb(p["color"])
        for r in radii:
            y0, y1 = max(0, py - r), min(H, py + r + 1)
            x0, x1 = max(0, px - r), min(W, px + r + 1)
            patch = im[y0:y1, x0:x1]
            hit = bool(_match(patch, target).any()) if patch.size else False
            out[r][p["curve"]][1] += 1
            if hit:
                out[r][p["curve"]][0] += 1
    summary = {}
    for r in radii:
        summary["r%d" % r] = {
            c: {"n": v[1], "hits": v[0], "rate": round(v[0] / v[1], 4)}
            for c, v in sorted(out[r].items())
        }
    return summary
