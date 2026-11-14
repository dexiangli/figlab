# -*- coding: utf-8 -*-
"""处理层 + 规格层真实数据跑通：四几何量、固定欧姆数截尾、三预设、一次报全问题。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                                   # noqa: E402
from figlab.data.dataset import read_long                  # noqa: E402
from figlab.process import get_processor                   # noqa: E402
from figlab.spec.merge import (build_spec, list_figures, load_preset,  # noqa: E402
                               save_spec)
from figlab.spec.schema import validate                    # noqa: E402

LINE = "=" * 66


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def main():
    print(LINE)
    print("处理层 + 规格层 · 真实数据跑通（规范 §二 / §三 / §十）")
    print(LINE)

    # ---------------- 处理层
    rows = read_long(paths.working("eis_20261107"), "eis")
    groups = defaultdict(list)
    for r in rows:
        groups[r["curve"]].append(r)
    proc = get_processor("eis")
    print("\n[1] 处理层四几何量（频率由高到低扫描；tail_ohm=60 固定欧姆数截尾）")
    print("    %-38s %5s %8s %8s %8s %8s %7s %7s" %
          ("曲线", "n", "Rs", "弧顶i", "Rct", "鞍点i", "截尾后", "尾段Ω"))
    geoms = {}
    for c, rs in sorted(groups.items()):
        g = proc.geometry(rs)
        kept = proc.truncate(rs, g, tail_ohm=60.0)
        geoms[c] = (g, kept)
        z_last = float(kept[-1]["Zp_ohm"])
        tail_len = z_last - g["saddle_Zp_ohm"] if g["saddle_Zp_ohm"] else 0
        print("    %-38s %5d %8.2f %8d %8.2f %8d %7d %7.1f" %
              (c[:38], g["n_points"], g["Rs_ohm"], g["apex_index"], g["Rct_ohm"],
               g["saddle_index"] if g["saddle_index"] is not None else -1,
               len(kept), tail_len))
    apex_y = [g["apex_y_ohm"] for g, _ in geoms.values()]
    gmax_y = [g["global_max_y_ohm"] for g, _ in geoms.values()]
    gmax_at_end = sum(1 for g, _ in geoms.values()
                      if g["global_max_index"] == g["n_points"] - 1)
    print("    首局部极大 y 范围 = %.1f ~ %.1f Ω；全局最大 y 范围 = %.1f ~ %.1f Ω"
          % (min(apex_y), max(apex_y), min(gmax_y), max(gmax_y)))
    print("    全局最大落在最后一个点的曲线 = %d/%d → 用全局最大取弧顶必然取到低频第二弧末端"
          % (gmax_at_end, len(geoms)))
    print("    截尾后各曲线点数 = %s（固定欧姆数，不是固定比例）" %
          [len(k) for _, k in geoms.values()])
    g_ito = geoms["ITO 1-1"][0]
    fit = proc.fit(groups["ITO 1-1"], g_ito)
    print("    圆拟合（可选）kind=%s，R=%.2f Ω，RMS=%.3f Ω；声明=%s" %
          (fit["kind"], fit["radius_ohm"], fit["rms_residual_ohm"], fit["disclaimer"]))

    # ---------------- 规格层：三预设
    print("\n[2] 三套预设加载")
    for n in ("inhouse", "generic", "dark_outline"):
        p = load_preset(n)
        print("    %-13s 画布 %.1f×%.1f cm | 图层 %s | %s %g/%g pt | 等比=%s | 图例=%s" %
              (n, p["page"]["w_cm"], p["page"]["h_cm"],
               "/".join(str(p["layer"][k]) for k in ("left", "top", "width", "height")),
               p["style"]["font"], p["style"]["tick_pt"], p["style"]["title_pt"],
               p["style"]["equal_aspect"], p["legend"]["show"]))
    inh = load_preset("inhouse")
    w, h = inh["page"]["w_cm"], inh["page"]["h_cm"]
    L = inh["layer"]
    margins = (w * L["left"] / 100, h * L["top"] / 100,
               w * (100 - L["left"] - L["width"]) / 100,
               h * (100 - L["top"] - L["height"]) / 100)
    frame = (w * L["width"] / 100, h * L["height"] / 100)
    print("    默认预设换算：页边距 左%.2f 上%.2f 右%.2f 下%.2f cm；图框 %.2f×%.2f cm" %
          (margins[0], margins[1], margins[2], margins[3], frame[0], frame[1]))

    # ---------------- 规格层：主图规格 + 校验
    curves = sorted(groups)
    spec = build_spec("eis_main", "eis_20261107", curves, preset="inhouse",
                      note="全部 8 条文本曲线进图，不替使用者做实验取舍；固定欧姆数截尾",
                      tail_ohm=60.0)
    v = validate(spec)
    print("\n[3] 主图规格校验：checks=%d，problems=%d，warnings=%d，ok=%s" %
          (v["checks"], v["problem_count"], v["warning_count"], v["ok"]))
    for w_ in v["warnings"]:
        print("    warn:", w_)
    print("    series = %d 条，字母 %s，符号 %s" %
          (len(spec["series"]), [s["letter"] for s in spec["series"]],
           sorted({s["marker"] for s in spec["series"]})))
    print("    export.dir 绝对路径 = %s" % os.path.isabs(spec["export"]["dir"]))

    # ---------------- 规格层：一次报出全部结构性问题
    bad = copy.deepcopy(spec)
    bad["page"]["w_cm"] = -1
    bad["layer"]["width"] = 95
    bad["style"]["grid"] = True
    bad["style"]["tick_dir"] = "out"
    bad["style"]["spines"] = "bottom"
    bad["style"]["equal_aspect"] = True      # 与 fill_frame 互斥
    bad["style"]["fill_frame"] = True
    bad["axis"]["zero_origin"] = True
    bad["series"][0]["marker"] = "x"
    bad["series"][0]["color"] = "blue"
    bad["series"][1]["letter"] = bad["series"][0]["letter"]
    bad["series"][2]["curve"] = "不存在的曲线"
    bad["legend"]["show"] = True
    bad["export"]["dir"] = "outputs/relative"
    bad["export"]["dpi"] = 300
    bad["data"]["fit_arc"] = True
    bad["data"]["fit_disclaimer"] = ""
    vb = validate(bad)
    print("\n[4] 故意注入 15 处结构性问题 → 一次报出 %d 条（不是画到一半才失败）"
          % vb["problem_count"])
    for p in vb["problems"]:
        print("      -", p)

    # ---------------- 规格层：单图覆盖不改预设
    pf = os.path.join(paths.PRESETS, "inhouse.json")
    before = sha(pf)
    ov = {"page": {"w_cm": 10.0}, "style": {"tick_pt": 10.0}}
    spec2 = build_spec("eis_wide", "eis_20261107", curves[:6], preset="inhouse",
                       overrides=ov, note="演示单图覆盖：10 cm 宽、刻度 10 pt",
                       tail_ohm=60.0)
    save_spec(spec)
    save_spec(spec2)
    after = sha(pf)
    print("\n[5] 单图覆盖：overrides=%s" % spec2["overrides"])
    print("    生效：page.w_cm=%.1f, style.tick_pt=%.1f；预设文件 sha256 %s → %s（未改）"
          % (spec2["page"]["w_cm"], spec2["style"]["tick_pt"], before, after))
    print("    覆盖项写入该图规格 spec['overrides'] = %s" % (spec2["overrides"] == ov))
    print("    页签注册表 = %s" % [f["id"] for f in list_figures()])
    print("    覆盖图校验 ok=%s problems=%d" %
          (validate(spec2)["ok"], validate(spec2)["problem_count"]))

    print("\n" + LINE + "\n处理层 + 规格层：跑通\n" + LINE)


if __name__ == "__main__":
    main()
