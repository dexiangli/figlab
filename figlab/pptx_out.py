# -*- coding: utf-8 -*-
"""一键出 PPT：把当前图直接放进 .pptx 幻灯片，不必先导 PDF 再手动插图。

两个要点（都是用户提的）：

1. 图按版面等比放大到整页（留标题和脚注的位置），用 1200 dpi 渲染件嵌入，
   投影和打印都够清；PPT 里再放大也不糊。
2. 图片挂上超链接，指回 ``http://127.0.0.1:8778/?fig=<图ID>``：放映时点一下、
   编辑时 Ctrl+单击，就回到绘图平台接着改数据。图片名也写成 ``figlab:<图ID>``，
   以后想批量找回来（或写 VBA 遍历）有稳定抓手。

不自动打开 PowerPoint（本机可能没有装；有 WPS 也能打开）。
"""
from __future__ import annotations

import os
from datetime import datetime

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches, Pt

PAGE_W_IN = 13.333          # 16:9
PAGE_H_IN = 7.5
MARGIN_IN = 0.62
TITLE_H_IN = 0.78
FOOT_H_IN = 0.40
INK = RGBColor(0x26, 0x26, 0x2A)
MUTED = RGBColor(0x86, 0x84, 0x7F)
ACCENT = RGBColor(0x2F, 0x6D, 0xAE)


def _blank(prs):
    # 第 7 个版式是「空白」；取不到就用最后一个，保证不往上叠占位符
    try:
        return prs.slide_layouts[6]
    except IndexError:
        return prs.slide_layouts[len(prs.slide_layouts) - 1]


def _fit(img_w: int, img_h: int, box_w: float, box_h: float):
    """等比缩放进 box（英寸）；返回 (宽, 高)。"""
    s = min(box_w / img_w, box_h / img_h)
    return img_w * s, img_h * s


def _text(slide, left, top, width, height, text, size, color, bold=False,
          align=None):
    box = slide.shapes.add_textbox(Inches(left), Inches(top),
                                   Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = text
    if align is not None:
        p.alignment = align
    for r in p.runs:
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = "等线"
        r.font.color.rgb = color
    return box


def _add_slide(prs, spec, png, url, caption, subtitle=""):
    """在一份 Presentation 末尾加一页：标题 + 图（带超链接）+ 脚注。"""
    from PIL import Image

    with Image.open(png) as im:
        iw, ih = im.size

    W = prs.slide_width / 914400.0
    H = prs.slide_height / 914400.0
    slide = prs.slides.add_slide(_blank(prs))

    top_pad = 0.34
    if caption:
        _text(slide, MARGIN_IN, top_pad, W - 2 * MARGIN_IN, TITLE_H_IN,
              caption, 26, INK, bold=True)
        top_pad += TITLE_H_IN
    if subtitle:
        _text(slide, MARGIN_IN, top_pad - 0.10, W - 2 * MARGIN_IN, 0.34,
              subtitle, 13, MUTED)
        top_pad += 0.26

    box_w = W - 2 * MARGIN_IN
    box_h = H - top_pad - FOOT_H_IN - 0.30
    pw, ph = _fit(iw, ih, box_w, box_h)
    left = (W - pw) / 2.0
    top = top_pad + max(0.0, (box_h - ph) / 2.0)

    pic = slide.shapes.add_picture(png, Inches(left), Inches(top),
                                   width=Inches(pw), height=Inches(ph))
    pic.name = "figlab:%s" % spec["id"]
    # 双击/单击回到绘图平台改数据：链接指向本机服务，服务开着就能进
    if url:
        pic.click_action.hyperlink.address = url
    try:
        pic._element.nvPicPr.cNvPr.set(
            "descr", "figlab 图 %s｜在 figlab 中编辑：%s" % (spec["id"], url))
    except Exception:
        pass

    if url:
        _text(slide, MARGIN_IN, H - FOOT_H_IN - 0.10, W - 2 * MARGIN_IN, 0.30,
              "放映时单击图、编辑时 Ctrl+单击图 → 回到 figlab 改数据：%s" % url,
              10.5, MUTED)
    try:
        slide.notes_slide.notes_text_frame.text = (
            "figlab 图 ID：%s\n导出时间：%s\n编辑入口：%s\n"
            "操作：放映时单击图片、编辑状态下 Ctrl+单击图片即可打开绘图平台。"
            % (spec["id"], datetime.now().strftime("%Y-%m-%d %H:%M"), url))
    except Exception:
        pass
    return {"slide_index": len(prs.slides._sldIdLst),
            "pic_in": [round(pw, 3), round(ph, 3)],
            "left_in": round(left, 3), "top_in": round(top, 3)}


def build(spec: dict, png: str, url: str, out_path: str,
          caption: str = "", subtitle: str = "") -> dict:
    """新建一份 16:9 的 PPTX，只放这一页。"""
    prs = Presentation()
    prs.slide_width = Inches(PAGE_W_IN)
    prs.slide_height = Inches(PAGE_H_IN)
    info = _add_slide(prs, spec, png, url, caption, subtitle)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    prs.save(out_path)
    return dict(info, ok=True, path=out_path, bytes=os.path.getsize(out_path),
                url=url, picture="figlab:%s" % spec["id"],
                mode="new", slide_w_in=PAGE_W_IN, slide_h_in=PAGE_H_IN)


def append(spec: dict, png: str, url: str, existing: str,
           caption: str = "", subtitle: str = "") -> dict:
    """往已有 PPT 末尾追加一页；文件被 PowerPoint/WPS 打开时会失败，如实报错。"""
    if not os.path.isfile(existing):
        return {"ok": False, "error": "找不到要追加的 PPT：%s" % existing}
    prs = Presentation(existing)
    info = _add_slide(prs, spec, png, url, caption, subtitle)
    try:
        prs.save(existing)
    except PermissionError:
        return {"ok": False,
                "error": "这份 PPT 正被 PowerPoint/WPS 打开，先关掉再追加：%s" % existing}
    return dict(info, ok=True, path=existing, bytes=os.path.getsize(existing),
                url=url, picture="figlab:%s" % spec["id"], mode="append",
                slide_w_in=prs.slide_width / 914400.0,
                slide_h_in=prs.slide_height / 914400.0)


def inspect(path: str) -> dict:
    """读回一份 PPTX 做自检：页数、每页图片名、超链接地址（供核验与测试用）。"""
    prs = Presentation(path)
    slides = []
    for i, s in enumerate(prs.slides, 1):
        pics = []
        for sh in s.shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    h = sh.click_action.hyperlink.address or ""
                except Exception:
                    h = ""
                pics.append({"name": sh.name, "hyperlink": h,
                             "w_in": round(sh.width / 914400.0, 3),
                             "h_in": round(sh.height / 914400.0, 3)})
        slides.append({"index": i, "n_pics": len(pics), "pics": pics,
                       "notes": (s.notes_slide.notes_text_frame.text
                                 if s.has_notes_slide else "")})
    return {"slides": slides, "n": len(slides),
            "slide_w_in": round(prs.slide_width / 914400.0, 3),
            "slide_h_in": round(prs.slide_height / 914400.0, 3),
            "bytes": os.path.getsize(path)}
