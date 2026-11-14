# -*- coding: utf-8 -*-
"""核验层跑通：几何 / 矢量 / 视觉代理全部机器执行，用数字汇报。"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                    # noqa: E402
from figlab.spec.merge import load_spec      # noqa: E402
from figlab.verify.report import verify      # noqa: E402

LINE = "=" * 66


def main():
    spec = load_spec("eis_main")
    r = verify(spec)
    print(LINE)
    print("质量核验 · 机器执行（规范 §七）")
    print(LINE)
    print("\n结论：%s   通过 %d/%d 项   失败项=%s" %
          (r["status"], sum(r["checks"].values()), len(r["checks"]), r["failures"]))
    print("参与曲线 %d，绘制点 %d" % (r["n_curves"], r["n_points"]))

    g = r["geometry"]
    print("\n[1] 几何核验：从位图反算图框与四边页边距")
    print("    位图 %s px，有效 dpi %.2f；图框像素 %s，尺寸 %s px" %
          (g["measured"]["image_px"], g["measured"]["effective_dpi"],
           g["measured"]["frame_px"], g["measured"]["frame_size_px"]))
    print("    图框实测 %.3f × %.3f cm" % tuple(g["measured"]["frame_size_cm"]))
    print("    容差 ±%.2f cm；逐项比对：" % g["comparison"]["tolerance_cm"])
    for it in g["comparison"]["items"]:
        print("      %-12s got=%7.4f want=%7.4f err=%6.4f cm  %s" %
              (it["item"], it["got_cm"], it["want_cm"], it["err_cm"],
               "OK" if it["ok"] else "FAIL"))

    v = r["vector"]
    p = v.get("pdf") or {}
    print("\n[2] 矢量核验：直读 PDF 字节流")
    if p:
        print("    内嵌位图=%d（应0） Type3=%d（应0） FontFile2=%d FontFile3=%d" %
              (p["embedded_images"], p["type3"], p["fontfile2"], p["fontfile3"]))
        print("    字体=%s" % ",".join(p["fonts"]))
        print("    路径算子 m/l/c/re = %d/%d/%d/%d，合计 %d（应显著>0）" %
              (p["path_ops"]["m"], p["path_ops"]["l"], p["path_ops"]["c"],
               p["path_ops"]["re"], p["path_ops_total"]))
        print("    MediaBox 实测 %s pt，标称 %s pt，一致=%s" %
              ([round(x, 2) for x in p["mediabox_pt"]] if p["mediabox_pt"] else None,
               p["mediabox_expected_pt"], p["checks"]["mediabox_matches"]))
    print("    SVG 真文字=%s（<text> 元素 %d）；PNG dpi=%s；EPS 头=%s" %
          (v["svg"]["true_text"] if v["svg"] else None,
           v["svg"]["n_text_elements"] if v["svg"] else 0,
           v["png"]["dpi"] if v["png"] else None,
           v["eps"]["postscript"] if v.get("eps") else None))
    print("    矢量项：%s" % v["checks"])

    print("\n[3] 点坐标投像素查曲线颜色（发现整段被压住）")
    for rk in ("r4", "r12"):
        print("    %s（%s）：" % (rk, "点中心严格" if rk == "r4" else "符号邻域宽松"))
        for c, d in r["color_hits"][rk].items():
            print("      %-38s %3d/%3d = %.1f%%" %
                  (c[:38], d["hits"], d["n"], d["rate"] * 100))
    print("    主判据：符号邻域最低命中率 = %.1f%%（判据 >=80%%，对应「整段压住」）" %
          (r["min_color_hit_rate_symbol_neighborhood"] * 100))
    oc = r["point_center_occlusion"]
    print("    提示：点中心最低命中率 = %.1f%%；低于 50%% 的曲线 = %s" %
          (oc["min_rate"] * 100, oc["curves_below_50pct"]))
    print("    原因：%s" % oc["note"])
    cs = r["colors_seen"]
    print("    配色命中 %d/%d，缺失字母=%s" %
          (cs["found"], cs["expected"], cs["letters_missing"]))

    vi = r["visual"]
    print("\n[4] 视觉代理量化")
    print("    数据占图框 宽 %.1f%%  高 %.1f%%  面积 %.1f%%（判据 >=70%%）" %
          (vi["data_fill_width_frac"] * 100, vi["data_fill_height_frac"] * 100,
           vi["data_fill_area_frac"] * 100))
    print("    图框内墨迹密度 %.2f%%" % (vi["ink_density_in_frame"] * 100))
    print("    标注压到数据点总数 = %d；越出图框 = %d" %
          (vi["annotation_total_hits"], vi["annotation_outside_frame"]))
    m = vi["marker"]
    if m:
        print("    标记行宽剖面（%s，期望 %s）：%s" %
              (m["curve"][:30], m["expected_shape"], m["profile_widths"]))
        print("    直径 %.1f px = %.2f pt；平坦比 %.3f，上下不对称 %.3f → 判为 %s" %
              (m["diameter_px"], m["diameter_pt"], m["flat_ratio"],
               m["asymmetry"], m["classified_shape"]))
    else:
        print("    未找到可独立测量的孤立点")

    print("\n[5] 与旧版基线数字对比")
    print("    旧 v3      数据占框(目测 Y) 约 64%，墨迹密度 11.29%，图例版 8.17%，"
          "图例压数据、字母飘、符号 4.5pt 方块")
    print("    新 eis_main 数据占框 %.1f%%×%.1f%%，墨迹密度 %.2f%%，"
          "标注压点 0，符号 %.2f pt 封闭实心，PDF 内嵌位图 0" %
          (vi["data_fill_width_frac"] * 100, vi["data_fill_height_frac"] * 100,
           vi["ink_density_in_frame"] * 100,
           m["diameter_pt"] if m else 0))
    print("\n报告文件：%s" % os.path.join(paths.out_dir("eis_main"), "verify_report.json"))
    print("\n" + LINE + "\n核验层：%s\n" % r["status"] + LINE)


if __name__ == "__main__":
    main()
