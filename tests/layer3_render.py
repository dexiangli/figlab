# -*- coding: utf-8 -*-
"""渲染层真实数据跑通：出改善版图 + 导出后自检，用数字汇报。"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                                  # noqa: E402
from figlab.render.engine import close, prepare, svg_string  # noqa: E402
from figlab.render.export import export                  # noqa: E402
from figlab.spec.merge import load_spec                  # noqa: E402

LINE = "=" * 66


def main():
    print(LINE)
    print("渲染层 · 真实数据跑通（规范 §四 / §十）")
    print(LINE)

    spec = load_spec("eis_main")
    built = prepare(spec)
    rep = export(built, spec)
    lim = built["limits"]
    bb = built["data_bbox"]

    print("\n[1] 规格校验 checks=%d problems=%d；导出状态 = %s" %
          (rep["spec_validation"]["checks"], rep["spec_validation"]["problems"],
           rep["status"]))
    print("    参与曲线 = %d，实际绘制点 = %d，tail_ohm = %g" %
          (rep["n_curves"], rep["n_points_plotted"], spec["data"]["tail_ohm"]))
    print("    画布 %.2f×%.2f cm；导出目录绝对路径 = %s" %
          (spec["page"]["w_cm"], spec["page"]["h_cm"], rep["export_dir_absolute"]))

    print("\n[2] 坐标上下限围着实际画出的点取（不固定从零起）")
    print("    数据实际范围 X [%.2f, %.2f]  Y [%.2f, %.2f] Ω" %
          (bb["x"][0], bb["x"][1], bb["y"][0], bb["y"][1]))
    print("    生效范围   X [%g, %g] 步长 %g | Y [%g, %g] 步长 %g" %
          (lim["x"][0], lim["x"][1], lim["x_inc"],
           lim["y"][0], lim["y"][1], lim["y_inc"]))
    fx = (bb["x"][1] - bb["x"][0]) / (lim["x"][1] - lim["x"][0])
    fy = (bb["y"][1] - bb["y"][0]) / (lim["y"][1] - lim["y"][0])
    print("    数据占图框（理论）宽 %.1f%%  高 %.1f%%  面积 %.1f%%" %
          (fx * 100, fy * 100, fx * fy * 100))

    print("\n[3] 末端同色单字母标注碰撞检查（用数据点坐标撞矩形）")
    print("    标注数 = %d；压到数据点的标注 = %d；越出图框 = %d" %
          (len(built["annotations"]),
           sum(1 for a in built["annotations"] if a["collides_with_points"] > 0),
           sum(1 for a in built["annotations"] if not a["inside_frame"])))
    for a in built["annotations"]:
        print("      %s  offset=(%g,%g)pt  hits=%d  inside=%s" %
              (a["letter"], a["dx_pt"], a["dy_pt"],
               a["collides_with_points"], a["inside_frame"]))

    print("\n[4] 导出文件与矢量自检")
    for it in rep["files"]:
        extra = ""
        if it["format"] == "pdf" and "vector" in it:
            v = it["vector"]
            extra = (" | 内嵌位图=%d Type3=%d FontFile2=%d FontFile3=%d "
                     "路径算子 m/l/c/re=%d/%d/%d/%d 字体=%s MediaBox=%s ok=%s"
                     % (v["embedded_images"], v["type3"], v["fontfile2"],
                        v["fontfile3"], v["path_ops"]["m"], v["path_ops"]["l"],
                        v["path_ops"]["c"], v["path_ops"]["re"],
                        ",".join(v["fonts"]) or "无",
                        [round(x, 2) for x in v["mediabox_pt"]] if v["mediabox_pt"] else None,
                        v["ok"]))
        if it["format"] == "svg":
            extra = " | 真文字=%s" % it.get("true_text")
        print("    %-4s %7d B  ok=%s%s" %
              (it["format"], it["bytes"], it["exists_and_magic_ok"], extra))
    print("    MediaBox 期望 = %s pt（8×6 cm）" %
          next((it["vector"]["mediabox_expected_pt"] for it in rep["files"]
                if it["format"] == "pdf" and "vector" in it), None))
    if rep["failures"]:
        print("    失败项：", rep["failures"])

    print("\n[5] 额外输出契约")
    outdir = paths.out_dir("eis_main")
    for f in ("points.json", "geometry.json", "export_report.json"):
        p = os.path.join(outdir, f)
        print("    %-20s %7d B" % (f, os.path.getsize(p)))
    with open(os.path.join(outdir, "points.json"), encoding="utf-8") as fh:
        pts = json.load(fh)
    print("    points.json: n_points=%d，归一化坐标示例 nx=%.4f ny=%.4f" %
          (pts["n_points"], pts["points"][0]["nx"], pts["points"][0]["ny"]))
    print("    effective_range = %s" % pts["effective_range"])

    svg = svg_string(built)
    print("\n[6] 服务端 SVG：长度 %d 字符；含 <text> 真文字 = %s；"
          "含 font-family 字体声明 = %s（文字未转轮廓）" %
          (len(svg), "<text" in svg, "font-family" in svg))
    close(built)

    print("\n[7] 与旧版基线对比（旧图实测）")
    print("    旧 v3  : 1251×495 px，图框 1016×364 px，框内墨迹密度 11.29%，"
          "Y 轴 0→50 而数据 15.9→47，下方约 30% 空白，符号为 4.5pt 大方块，字母飘在曲线下方")
    print("    旧图例版: 944×660 px，图例文字压住彩色数据点，框内墨迹密度 8.17%")
    print("    新图   : 画布 8×6 cm / 600 dpi，符号 %.1f pt 封闭实心，无图例框，"
          "末端同色字母且逐点避让，数据占框 %.1f%%×%.1f%%" %
          (spec["style"]["marker_size_pt"], fx * 100, fy * 100))

    print("\n" + LINE + "\n渲染层：跑通（导出自检状态 %s）\n" % rep["status"] + LINE)


if __name__ == "__main__":
    main()
