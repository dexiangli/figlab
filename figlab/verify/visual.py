# -*- coding: utf-8 -*-
"""视觉代理核验（规范 §七.3）：把「图好不好看」拆成可量化的量。

图框尺寸与页边距、数据占据图框的宽高比例、标记直径与形状（按行宽剖面区分
圆、方、三角）、配色命中数、墨迹密度、标注是否压到数据点（用坐标撞矩形，
不数像素 —— 图例/标注里本来就有同色样本，数像素必然误报）。
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

from .geometry import _match, hex2rgb


def visual_metrics(png_path: str, spec: dict, points: list[dict],
                   annotations: list[dict], frame: dict) -> dict:
    im = np.array(Image.open(png_path).convert("RGB")).astype(float)
    H, W = im.shape[:2]
    fx0, fy0, fx1, fy1 = frame["frame_px"]
    dpi = frame["effective_dpi"]

    # 1) 墨迹密度（图框内非白像素占比）
    ink = im.sum(2) < 720
    ink_density = float(ink[fy0:fy1 + 1, fx0:fx1 + 1].mean())

    # 2) 数据占据图框的宽高比例（按归一化的实测点坐标，不数像素）
    L = spec["layer"]
    nx0, nx1 = L["left"] / 100, (L["left"] + L["width"]) / 100
    ny0, ny1 = L["top"] / 100, (L["top"] + L["height"]) / 100
    xs = [p["nx"] for p in points]
    ys = [p["ny"] for p in points]
    frac_w = (max(xs) - min(xs)) / (nx1 - nx0)
    frac_h = (max(ys) - min(ys)) / (ny1 - ny0)

    # 3) 标注压到数据点：数据点坐标去撞标注矩形（§八.6）
    all_pts = [(p["Zp_ohm"], p["Zpp_neg_ohm"]) for p in points]
    ann = []
    for a in annotations:
        x0, y0, x1, y1 = a["rect_data"]
        hits = sum(1 for px, py in all_pts
                   if x0 <= px <= x1 and y0 <= py <= y1)
        ann.append({"letter": a["letter"], "hits": hits,
                    "inside_frame": a["inside_frame"]})

    # 4) 标记直径与形状：找一个孤立点，按行宽剖面分类
    coords = [(p["nx"] * W, p["ny"] * H, p) for p in points]
    marker = None
    for i, (x, y, p) in enumerate(coords):
        dmin = min((math.hypot(x - x2, y - y2)
                    for j, (x2, y2, _) in enumerate(coords) if j != i),
                   default=1e9)
        if dmin > 30:
            r = 16
            xi, yi = int(round(x)), int(round(y))
            patch = im[max(0, yi - r):yi + r + 1, max(0, xi - r):xi + r + 1]
            if patch.size == 0:
                continue
            mask = _match(patch, hex2rgb(p["color"]))
            widths = mask.sum(1)
            nz = widths[widths > 0]
            if len(nz) < 3:
                continue
            mx = float(nz.max())
            flat = float((nz >= 0.75 * mx).mean())
            half = len(nz) // 2
            slope = abs(float(nz[half:].mean()) - float(nz[:half].mean())) / mx
            shape = "square" if flat > 0.65 else ("triangle" if slope > 0.35 else "circle")
            marker = {
                "curve": p["curve"], "expected_shape": p["marker"],
                "profile_widths": [int(v) for v in nz],
                "diameter_px": mx, "diameter_pt": round(mx / dpi * 72, 2),
                "flat_ratio": round(flat, 3), "asymmetry": round(slope, 3),
                "classified_shape": shape,
            }
            break

    return {
        "ink_density_in_frame": round(ink_density, 5),
        "data_fill_width_frac": round(frac_w, 4),
        "data_fill_height_frac": round(frac_h, 4),
        "data_fill_area_frac": round(frac_w * frac_h, 4),
        "annotations": ann,
        "annotation_total_hits": sum(a["hits"] for a in ann),
        "annotation_outside_frame": sum(1 for a in ann if not a["inside_frame"]),
        "marker": marker,
    }
