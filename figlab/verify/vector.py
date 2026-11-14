# -*- coding: utf-8 -*-
"""矢量核验（规范 §七.2）：直接读 PDF 字节流，统计内嵌位图数量（应为 0）、
路径算子数量（应显著大于 0）、内嵌字体名与类型（TrueType 子集、无 Type3）、
MediaBox 与标称尺寸是否一致。顺带确认 SVG 真文字、PNG 仅 600 dpi 预览。
"""
from __future__ import annotations

import os
import re

from PIL import Image

from ..render.export import pdf_vector_report
from .geometry import _match, hex2rgb


def vector_check(outdir: str, base: str, spec: dict) -> dict:
    w, h = spec["page"]["w_cm"], spec["page"]["h_cm"]
    out = {"pdf": None, "svg": None, "png": None, "checks": {}}
    pdf = os.path.join(outdir, base + ".pdf")
    if os.path.isfile(pdf):
        out["pdf"] = pdf_vector_report(pdf, w, h)
        c = out["pdf"]["checks"]
        out["checks"].update({
            "embedded_images_zero": c["embedded_images_zero"],
            "path_ops_positive": c["path_ops_positive"],
            "truetype_subset": c["truetype_subset_present"],
            "no_type3": c["no_type3"],
            "no_fontfile3": c["no_fontfile3"],
            "mediabox_matches": c["mediabox_matches"],
        })
    else:
        out["checks"]["pdf_exists"] = False

    svgp = os.path.join(outdir, base + ".svg")
    if os.path.isfile(svgp):
        s = open(svgp, "r", encoding="utf-8", errors="ignore").read()
        out["svg"] = {
            "bytes": os.path.getsize(svgp),
            "true_text": ("<text" in s) or ("font-family" in s),
            "n_text_elements": len(re.findall(r"<text\b", s)),
        }
        out["checks"]["svg_true_text"] = out["svg"]["true_text"]

    pngp = os.path.join(outdir, base + ".png")
    if os.path.isfile(pngp):
        im = Image.open(pngp)
        dpi = im.info.get("dpi", (None, None))
        out["png"] = {"size_px": list(im.size), "dpi": list(dpi),
                      "bytes": os.path.getsize(pngp),
                      "preview_only": True}
        out["checks"]["png_600dpi"] = bool(dpi[0] and abs(dpi[0] - 600) < 1)

    epsp = os.path.join(outdir, base + ".eps")
    if os.path.isfile(epsp):
        out["eps"] = {"bytes": os.path.getsize(epsp),
                      "postscript": open(epsp, "rb").read(8).startswith(b"%!PS")}
        out["checks"]["eps_vector"] = out["eps"]["postscript"]

    out["ok"] = all(out["checks"].values()) and len(out["checks"]) >= 7
    return out


def colors_seen(path: str, spec: dict) -> dict:
    """配色命中数：图框内每种「参与绘制」的曲线颜色是否真的出现在像素里。

    曲线列表的整体显隐是合法操作（§五.4），被隐藏的曲线本来就不该出现在图上，
    不能拿它去判「配色缺失」——否则用户一隐藏曲线，核验就误报不合格。
    """
    import numpy as np
    im = np.array(Image.open(path).convert("RGB")).astype(float)
    drawn = [s for s in spec["series"] if s.get("include", True)]
    hidden = [s["letter"] for s in spec["series"] if not s.get("include", True)]
    found, missing = [], []
    for s in drawn:
        if _match(im, hex2rgb(s["color"])).any():
            found.append(s["letter"])
        else:
            missing.append(s["letter"])
    return {"expected": len(drawn), "found": len(found),
            "letters_found": found, "letters_missing": missing,
            "hidden_not_counted": hidden}
