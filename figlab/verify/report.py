# -*- coding: utf-8 -*-
"""核验汇总：所有量化项落成 verify_report.json，判定合格 / 不合格。

规范 §四.4 与 §七：机器执行，不通过要报「不合格」，不得报「成功」。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from .. import paths
from .geometry import color_hit_rates, compare_frame, frame_from_png
from .vector import colors_seen, vector_check
from .visual import visual_metrics


def verify(spec: dict) -> dict:
    outdir = paths.absolute(spec["export"]["dir"])
    base = spec["export"]["base"]
    png = os.path.join(outdir, base + ".png")
    pts_path = os.path.join(outdir, "points.json")
    if not (os.path.isfile(png) and os.path.isfile(pts_path)):
        raise RuntimeError("缺少导出位图或 points.json，请先跑渲染层")
    with open(pts_path, encoding="utf-8") as fh:
        ptsdoc = json.load(fh)
    points, annotations = ptsdoc["points"], ptsdoc["annotations"]

    frame = frame_from_png(png, [spec["page"]["w_cm"], spec["page"]["h_cm"]])
    frame_cmp = compare_frame(frame, spec, tol_cm=0.05)
    hits = color_hit_rates(png, points, radii=(4, 12))
    vec = vector_check(outdir, base, spec)
    cols = colors_seen(png, spec)
    vis = visual_metrics(png, spec, points, annotations, frame)

    strict = hits["r4"]       # 点中心：只作为「局部遮挡」提示
    loose = hits["r12"]       # 符号邻域：规范 §七.1「该位置是否存在该曲线颜色」
    min_rate = min((v["rate"] for v in loose.values()), default=0.0)
    min_center_rate = min((v["rate"] for v in strict.values()), default=0.0)
    center_below = [c for c, v in strict.items() if v["rate"] < 0.5]
    checks = {
        "geometry_frame_within_0.05cm": frame_cmp["ok"],
        "vector_all_pass": vec["ok"],
        "no_annotation_covering_points": vis["annotation_total_hits"] == 0,
        "annotations_inside_frame": vis["annotation_outside_frame"] == 0,
        "data_fill_width_ge_70pct": vis["data_fill_width_frac"] >= 0.70,
        "data_fill_height_ge_70pct": vis["data_fill_height_frac"] >= 0.70,
        "all_curve_colors_present": cols["found"] == cols["expected"],
        # 「整段压住」按符号邻域判定（符号直径约 23 px，r=12 覆盖其半径）
        "no_curve_fully_occluded": min_rate >= 0.80,
        "ink_not_empty": vis["ink_density_in_frame"] > 0.005,
    }
    failures = [k for k, v in checks.items() if not v]
    status = "合格" if not failures else "不合格"

    report = {
        "figure": spec["id"], "at": datetime.now().isoformat(timespec="seconds"),
        "status": status, "checks": checks, "failures": failures,
        "geometry": {"measured": frame, "comparison": frame_cmp},
        "vector": vec,
        "color_hits": hits,
        "colors_seen": cols,
        "visual": vis,
        # 主判据：符号邻域命中率；点中心命中率如实保留，不做隐藏
        "min_color_hit_rate_symbol_neighborhood": min_rate,
        "min_strict_color_hit_rate": min_center_rate,
        "point_center_occlusion": {
            "min_rate": min_center_rate,
            "curves_below_50pct": center_below,
            "note": ("点中心被同材料平行重复曲线的符号盖住；符号邻域仍能检出该曲线颜色，"
                     "属于数据本身在高频段重叠，不是整段被压住。取舍需由使用者裁决。"),
        },
        "n_points": len(points),
        "n_curves": len({p["curve"] for p in points}),
    }
    with open(os.path.join(outdir, "verify_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report
