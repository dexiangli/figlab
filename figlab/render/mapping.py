# -*- coding: utf-8 -*-
"""坐标映射：归一化的点坐标 + 实际生效的坐标范围（规范 §四.1）。

坐标上下限围着「实际画出来的点」取，留少量余量后归整到整刻度，不固定从零起
（规范 §四.2）。输出的 nx/ny 是相对整张画布 0~1 的坐标，y 从上往下，
供前端直接铺点击热区。
"""
from __future__ import annotations

import math

# 允许 4 倍刻度，让 8×6 cm 小图也能把数据铺得更满，而不是只剩中间六成
_NICE = (1, 2, 2.5, 4, 5, 10)


def nice_step(span: float, target_ticks: int = 8) -> float:
    if span <= 0 or not math.isfinite(span):
        return 1.0
    raw = span / max(target_ticks, 2)
    mag = 10 ** math.floor(math.log10(raw))
    for m in _NICE:
        if raw <= m * mag + 1e-12:
            return m * mag
    return 10 * mag


def nice_limits(values: list[float], pad_frac: float = 0.05,
                target_ticks: int = 8) -> tuple[float, float, float]:
    lo0, hi0 = min(values), max(values)
    span = hi0 - lo0
    if span <= 0:
        span = abs(hi0) * 0.1 or 1.0
    pad = span * pad_frac
    a, b = lo0 - pad, hi0 + pad
    inc = nice_step(b - a, target_ticks)
    lo = math.floor(a / inc) * inc
    hi = math.ceil(b / inc) * inc
    if hi <= lo:
        hi = lo + inc
    return float(lo), float(hi), float(inc)


def normalize_points(plotted: list[dict], limits: dict, layer: dict) -> list[dict]:
    """把每个实测点投到整张画布的归一化坐标（0~1，y 从上往下）。"""
    lx0, lx1 = limits["x"][:2]
    ly0, ly1 = limits["y"][:2]
    left = layer["left"] / 100.0
    top = layer["top"] / 100.0
    width = layer["width"] / 100.0
    height = layer["height"] / 100.0
    out = []
    for pd in plotted:
        ox, oy = float(pd.get("off_x") or 0.0), float(pd.get("off_y") or 0.0)
        for x, y, row in pd["points"]:
            nx = left + (x - lx0) / (lx1 - lx0) * width
            ny = top + (1.0 - (y - ly0) / (ly1 - ly0)) * height
            out.append({
                "curve": pd["curve"], "letter": pd["letter"],
                "color": pd["color"], "marker": pd["marker"],
                "point_index": row.get("point_index"),
                "freq_Hz": float(row["freq_Hz"]),
                # Zp_ohm / Zpp_ohm 是**图上画出来**的位置（含整条曲线的平移）；
                # *_data 才是工作副本里的实测值，拖动与提示都按这两个字段讲清楚
                "Zp_ohm": x, "Zpp_ohm": -y,
                "Zpp_neg_ohm": y,
                "off_x": ox, "off_y": oy,
                "Zp_data": x - ox, "Zpp_data": -y + oy,
                "nx": round(nx, 6), "ny": round(ny, 6),
            })
    return out


def annotation_rect_data(ax, x, y, dx_pt, dy_pt, font_pt, dpi):
    """把末端字母标注的包围框换算成数据坐标（§八.6：用坐标撞点，不数像素）。"""
    import numpy as np
    anchor = ax.transData.transform((x, y))
    w_px = 0.62 * font_pt / 72.0 * dpi
    h_px = 1.00 * font_pt / 72.0 * dpi
    x0 = anchor[0] + dx_pt / 72.0 * dpi
    y0 = anchor[1] + dy_pt / 72.0 * dpi
    corners = np.array([[x0, y0], [x0 + w_px, y0 + h_px]])
    d = ax.transData.inverted().transform(corners)
    return [float(d[:, 0].min()), float(d[:, 1].min()),
            float(d[:, 0].max()), float(d[:, 1].max())]
