# -*- coding: utf-8 -*-
"""阻抗谱处理层（规范 §二）。

四个几何量，按频率由高到低扫描：
  Rs      溶液电阻 = 高频端第一个点的实部
  apex    弧顶     = 虚部（-Z''）首次出现局部极大的位置
  Rct     电荷转移电阻 = 2 × (弧顶实部 - Rs)
  saddle  鞍点     = 弧顶之后虚部首次出现局部极小的位置

**禁止**用虚部全局最大值取弧顶（会取到低频段第二个大弧的末端），
**禁止**用显著性阈值筛选（会把真弧顶滤掉）。本机实测：8 条曲线的全局最大
全部落在最后一个点，y=128.8~762.4 Ω；真弧顶在 i=4~8，y=19.9~92.5 Ω。

截尾采用固定欧姆数，不是固定比例：保留到鞍点之后再走 tail_ohm 欧姆，
使多条曲线尾段等长、视觉可比。
"""
from __future__ import annotations

import math

from .base import SpectrumProcessor, register


def _ordered(rows: list[dict]) -> list[dict]:
    """扫描方向：频率由高到低。原始 point_index 原样保留，不改写工作副本。"""
    return sorted(rows, key=lambda r: -float(r["freq_Hz"]))


def _y(rows: list[dict]) -> list[float]:
    return [-float(r["Zpp_ohm"]) for r in rows]     # 虚部取负，Nyquist 纵轴


def _z(rows: list[dict]) -> list[float]:
    return [float(r["Zp_ohm"]) for r in rows]


@register
class EISProcessor(SpectrumProcessor):
    name = "eis"

    def geometry(self, rows: list[dict]) -> dict:
        o = _ordered(rows)
        if len(o) < 4:
            raise ValueError("点数不足 4，无法判定弧顶与鞍点")
        y, z = _y(o), _z(o)
        rs = z[0]

        # 频率下降方向上第一个局部极大；无阈值、无平滑、无全局搜索
        apex = None
        for i in range(1, len(y) - 1):
            if y[i] > y[i - 1] and y[i] >= y[i + 1]:
                apex = i
                break
        if apex is None:
            raise ValueError("未找到弧顶（虚部沿频率下降方向单调，无局部极大）")

        rct = 2.0 * (z[apex] - rs)

        # 弧顶之后第一个局部极小
        saddle = None
        for i in range(apex + 1, len(y) - 1):
            if y[i] < y[i - 1] and y[i] <= y[i + 1]:
                saddle = i
                break

        global_max = max(range(len(y)), key=lambda i: y[i])
        return {
            "n_points": len(o),
            "Rs_ohm": rs,
            "apex_index": apex, "apex_point_index": o[apex].get("point_index"),
            "apex_freq_Hz": float(o[apex]["freq_Hz"]),
            "apex_Zp_ohm": z[apex], "apex_y_ohm": y[apex],
            "Rct_ohm": rct,
            "saddle_index": saddle,
            "saddle_point_index": o[saddle].get("point_index") if saddle is not None else None,
            "saddle_Zp_ohm": z[saddle] if saddle is not None else None,
            "saddle_y_ohm": y[saddle] if saddle is not None else None,
            "global_max_index": global_max,
            "global_max_y_ohm": y[global_max],
            "freq_first_Hz": float(o[0]["freq_Hz"]),
            "freq_last_Hz": float(o[-1]["freq_Hz"]),
            "kind": "measured",
        }

    def truncate(self, rows: list[dict], geom: dict, tail_ohm: float = 60.0) -> list[dict]:
        """保留到鞍点之后再走固定欧姆数；tail_ohm=0 表示只到鞍点。"""
        o = _ordered(rows)
        s = geom["saddle_index"]
        if s is None:
            s = geom["apex_index"]
        z_end = float(geom["saddle_Zp_ohm"] if geom["saddle_Zp_ohm"] is not None
                      else _z(o)[s]) + float(tail_ohm)
        keep = [r for r in o if float(r["Zp_ohm"]) <= z_end]
        if not keep:
            keep = o[:s + 1]
        return keep

    def fit(self, rows: list[dict], geom: dict) -> dict | None:
        """首弧参考圆：Kasa 代数最小二乘（纯 numpy 版算式，不依赖 scipy）。

        返回带 kind="fit" 与 disclaimer；渲染层必须把它画成参考弧并声明，
        不得与实测点混同（规范 §二.4 / §八.7）。
        """
        import numpy as np
        o = _ordered(rows)
        s = geom["saddle_index"] or geom["apex_index"]
        seg = o[:max(s, 3) + 1]
        x = np.array([float(r["Zp_ohm"]) for r in seg])
        y = np.array([-float(r["Zpp_ohm"]) for r in seg])
        # (x-a)^2+(y-b)^2 = R^2  ->  2a*x + 2b*y + c = x^2+y^2
        A = np.column_stack([2 * x, 2 * y, np.ones(len(x))])
        b = x * x + y * y
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        a, bb, c = sol
        radius = math.sqrt(max(c + a * a + bb * bb, 0.0))
        resid = np.sqrt((x - a) ** 2 + (y - bb) ** 2) - radius
        return {
            "kind": "fit", "model": "algebraic_circle (Kasa, least squares)",
            "center_Zp_ohm": float(a), "center_y_ohm": float(bb),
            "radius_ohm": float(radius),
            "rms_residual_ohm": float(np.sqrt(np.mean(resid ** 2))),
            "n_points_used": len(seg),
            "disclaimer": "参考圆拟合弧（fit），非实测数据；由首弧实测点经最小二乘算出",
        }
