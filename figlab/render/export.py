# -*- coding: utf-8 -*-
"""导出 + 导出后自检（规范 §四.3 / §四.4）。

自检不通过必须报「不合格」，不得报「成功」。直接读 PDF 字节流统计内嵌位图、
路径算子、字体类型与 MediaBox；位图仅在需要时以 600 dpi 另存，不得用于投稿。
"""
from __future__ import annotations

import json
import os
import re
import zlib
from datetime import datetime

from .. import paths
from ..data.edit import record_export
from .curve import CONNECT_NOTE

MAGIC = {
    ".pdf": (b"%PDF",),
    ".eps": (b"%!PS",),
    ".svg": (b"<?xml", b"<svg"),
    ".png": (b"\x89PNG",),
}


def _ok_file(path: str) -> bool:
    if not os.path.isfile(path) or os.path.getsize(path) < 64:
        return False
    with open(path, "rb") as fh:
        head = fh.read(16)
    return any(head.startswith(m) for m in MAGIC.get(os.path.splitext(path)[1].lower(), ()))


def pdf_vector_report(path: str, w_cm: float, h_cm: float) -> dict:
    """直接读 PDF 字节流；内容流若是 FlateDecode，解压后再数路径算子。"""
    raw = open(path, "rb").read()
    txt = raw.decode("latin-1")
    images = len(re.findall(r"/Subtype\s*/Image", txt))
    type3 = len(re.findall(r"/Type3\b", txt))
    fontfile2 = len(re.findall(r"/FontFile2\b", txt))
    fontfile3 = len(re.findall(r"/FontFile3\b", txt))
    fonts = sorted(set(re.findall(r"/BaseFont\s*/([A-Za-z0-9+\-]+)", txt)))

    mb = re.findall(r"/MediaBox\s*\[([^\]]+)\]", txt)
    mb_vals = None
    if mb:
        nums = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", mb[0])]
        if len(nums) >= 4:
            mb_vals = [nums[2] - nums[0], nums[3] - nums[1]]
    want = [w_cm / 2.54 * 72.0, h_cm / 2.54 * 72.0]
    mb_ok = bool(mb_vals) and all(abs(a - b) <= 0.6 for a, b in zip(mb_vals, want))

    content = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            content.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except Exception:
            continue
    allc = "\n".join(content)
    ops = {
        "m": len(re.findall(r"(?:[-+]?[\d.]+ ){2}m\b", allc)),
        "l": len(re.findall(r"(?:[-+]?[\d.]+ ){2}l\b", allc)),
        "c": len(re.findall(r"(?:[-+]?[\d.]+ ){6}c\b", allc)),
        "re": len(re.findall(r"(?:[-+]?[\d.]+ ){4}re\b", allc)),
    }
    op_total = sum(ops.values())
    checks = {
        "embedded_images_zero": images == 0,
        "no_type3": type3 == 0,
        "truetype_subset_present": fontfile2 > 0,
        "no_fontfile3": fontfile3 == 0,
        "mediabox_matches": mb_ok,
        "path_ops_positive": op_total > 20,
    }
    return {"embedded_images": images, "type3": type3,
            "fontfile2": fontfile2, "fontfile3": fontfile3, "fonts": fonts,
            "mediabox_pt": mb_vals, "mediabox_expected_pt": [round(x, 3) for x in want],
            "path_ops": ops, "path_ops_total": op_total,
            "checks": checks, "ok": all(checks.values())}


def export(built: dict, spec: dict) -> dict:
    outdir = paths.absolute(spec["export"]["dir"])   # 绝对路径，缺陷清单第 2 条
    paths.ensure_dirs(outdir)
    base = spec["export"]["base"]
    fig = built["fig"]
    w, h = spec["page"]["w_cm"], spec["page"]["h_cm"]

    results, files = [], []
    # 交付格式由用户勾选（默认只有 PDF）；PNG 永远生成一份 600 dpi 预览，
    # 因为网页缩略图与机器核验都要读它。预览件不算交付件，也不进「图片」归档。
    jobs = [(str(f).lower(), "deliverable") for f in spec["export"]["formats"]]
    if "png" not in [j[0] for j in jobs]:
        jobs.append(("png", "preview"))
    for f, role in jobs:
        path = os.path.join(outdir, base + "." + f)
        # 不先删旧文件：savefig 本身覆盖写。原先的 os.remove 在受限环境里会被
        # 安全钩子拦截（累计删除达到阈值后直接拒绝），表现为导出莫名中断。
        err = ""
        try:
            if f == "png":
                fig.savefig(path, format="png", dpi=600)
            else:
                fig.savefig(path, format=f)   # 不传 pdf={...}，见缺陷清单第 1 条
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
        ok = _ok_file(path)
        item = {"format": f, "role": role, "path": path,
                "bytes": os.path.getsize(path) if os.path.isfile(path) else 0,
                "exists_and_magic_ok": ok, "error": err}
        if f == "pdf" and ok:
            item["vector"] = pdf_vector_report(path, w, h)
        if f == "svg" and ok:
            s = open(path, "r", encoding="utf-8", errors="ignore").read()
            item["true_text"] = ("<text" in s) or ("font-family" in s)
        if f == "eps" and ok:
            item["postscript_vector"] = "%!PS" in open(path, "rb").read(64).decode("latin-1", "ignore")
        results.append(item)
        if ok:
            files.append(path)

    # ---- 额外两项输出（规范 §四.1）
    offsets = {s["curve"]: {"off_x": float(s.get("off_x") or 0.0),
                            "off_y": float(s.get("off_y") or 0.0)}
               for s in spec.get("series", [])
               if abs(float(s.get("off_x") or 0.0)) > 1e-12
               or abs(float(s.get("off_y") or 0.0)) > 1e-12}
    segs = {pd["curve"]: pd.get("n_runs", 1) for pd in built["plotted"]}
    split = {c: n for c, n in segs.items() if n > 1}
    connect = built.get("connect", "segment")
    line_pts = {pd["curve"]: pd.get("n_line_pts", 0) for pd in built["plotted"]}
    points_doc = {
        "figure": spec["id"], "page_cm": [w, h], "layer_pct": spec["layer"],
        "effective_range": built["limits"],
        "data_bbox": built["data_bbox"],
        "n_points": len(built["points_norm"]),
        "points": built["points_norm"],
        "annotations": built["annotations"],
        "texts": built.get("texts", []),
        # 整条曲线的显示平移：图上位置 ≠ 实测值，必须留痕，不能让人误读
        "display_offsets": offsets,
        "offset_note": ("以下曲线在图上做了整体平移（只改显示位置，工作副本未改）："
                        + "、".join("%s Δ(%.3f, %.3f)" % (k, v["off_x"], v["off_y"])
                                    for k, v in offsets.items())) if offsets else "",
        # 剔除处断线：>1 表示这条曲线在剔除点处断开，图上是几段而不是一条连续线
        "segments": segs,
        "segment_note": ("以下曲线在剔除点处断开（不跨断点连线）："
                         + "、".join("%s 分 %d 段" % (c, n) for c, n in split.items()))
                        if split else "",
        # 连线画法：散点 / 折线 / 平滑。平滑的中间点是插值算出来的，必须留痕
        "connect": connect,
        "connect_note": CONNECT_NOTE[connect],
        "line_vertices": line_pts,
        "interpolated": connect == "smooth",
    }
    with open(os.path.join(outdir, "points.json"), "w", encoding="utf-8") as fh:
        json.dump(points_doc, fh, ensure_ascii=False, indent=2)

    geom_doc = {
        "figure": spec["id"], "dataset": spec["data"]["dataset"],
        "spectrum": spec["data"].get("spectrum", "eis"),
        "tail_ohm": spec["data"].get("tail_ohm", 0),
        "connect": connect,
        "curves": {c: {"geometry": v["geometry"], "n_plotted": v["n_plotted"],
                       "n_segments": v.get("n_segments", 1),
                       "n_line_pts": v.get("n_line_pts", 0)}
                   for c, v in built["geometry"].items()},
        "fit": built["fit"],
        "fit_disclaimer": (spec["data"].get("fit_disclaimer", "")
                           if spec["data"].get("fit_arc") else ""),
        "note": "geometry 中的量均来自实测点；fit 为处理结果，不是实测数据",
    }
    with open(os.path.join(outdir, "geometry.json"), "w", encoding="utf-8") as fh:
        json.dump(geom_doc, fh, ensure_ascii=False, indent=2)

    # ---- 自检汇总：任一不通过即「不合格」
    failures = []
    for it in results:
        if not it["exists_and_magic_ok"]:
            failures.append("%s 文件缺失/魔数不符 %s" % (it["format"], it["error"]))
        if it["format"] == "pdf":
            if "vector" not in it:
                failures.append("PDF 未生成，无法做矢量自检")
            elif not it["vector"]["ok"]:
                failures.append("PDF 矢量自检未过：%s" %
                                [k for k, v in it["vector"]["checks"].items() if not v])
        if it["format"] == "svg" and not it.get("true_text"):
            failures.append("SVG 未见 <text>，疑似文字被转轮廓")
    status = "合格" if not failures else "不合格"
    report = {
        "figure": spec["id"], "at": datetime.now().isoformat(timespec="seconds"),
        "export_dir_absolute": os.path.isabs(outdir), "outdir": outdir,
        "page_cm": [w, h], "status": status, "failures": failures,
        "files": results,
        "display_offsets": offsets,
        "connect": connect,
        "connect_note": CONNECT_NOTE[connect],
        "spec_validation": {"checks": built["validation"]["checks"],
                            "problems": built["validation"]["problem_count"]},
        "n_points_plotted": len(built["points_norm"]),
        "n_curves": len(built["plotted"]),
    }
    with open(os.path.join(outdir, "export_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    record_export(spec["data"]["dataset"], spec["id"],
                  [i["format"] for i in results], files,
                  reason="导出投稿级图件并自检，状态=" + status)
    return report
