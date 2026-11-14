# -*- coding: utf-8 -*-
"""【已停用，仅保留读旧数据】桌面\\FigLab输出\\<日期>\\<类别>\\...

2026-11-14 起下线。原因：文件名里带的是「导出当天」，同一批数据 11-07 的图，
11-13 导出得 20261113阻抗作图，11-14 再导出得 20261114阻抗作图，桌面上
同一份数据攒出两个日期目录——用户原话「同一个数据，两天都有不同的保存」。

现在的口径在 ``handoff.py``：``桌面\\FigLab\\<数据日期><类别>作图\\``，日期取
数据自身的日期并冻结在 ``export.name_date`` 里，隔天再导还是同一个名字。
本模块的写入函数已无调用点，只留 ``archive_index()`` 让旧的「归档」列表还能
读出历史文件；不要再增加新的调用。
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime

from . import paths

KIND_IMAGE = "图片"
KIND_DATA = "数据"
KIND_REPORT = "报告"

README = """FigLab 导出归档
================

目录约定：<日期>\\<类别>\\...

  图片\\pdf   默认交付：投稿用矢量件，字体已内嵌 TrueType 子集，无位图
  图片\\eps   EPS 矢量件（导出面板勾选后才有）
  图片\\svg   真文字 SVG（勾选后才有，可在 Illustrator / Inkscape 里继续改）
  图片\\png   600 dpi 位图（勾选后才有；仅贴图用，不用于投稿）
  图片\\pptx  一键生成的幻灯片，图带超链接，可点回 figlab 继续改
  数据\\原始  源文件解析出的长表快照（只读，永不改写）
  数据\\处理后 绘图实际用的工作副本（含人工改值与排除）
  报告     导出自检、机器核验、每点坐标与几何量

文件名 = <日期><类别>作图，例如 20261113阻抗作图.pdf。
同一天重复导出会覆盖同名文件，保留的是当天最新一版。
"""


def _writable(path: str) -> None:
    """归档件必须可覆盖。原始快照是只读的，copy2 会把只读权限一起带过去，
    下次导出就写不进去、只能另存时间戳副本，越堆越多。"""
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def _copy(src: str, dst: str) -> dict:
    """复制到归档位；目标被别的程序占用时改写到固定备用名，绝不静默失败。

    备用名固定为 <名>_locked.<ext>，反复导出只会覆盖同一个文件，不会按时间
    戳越堆越多（用户常见情形：在 Excel / WPS 里开着桌面那份 CSV）。
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        _writable(dst)
    try:
        shutil.copy2(src, dst)
        _writable(dst)
        return {"src": src, "path": dst, "bytes": os.path.getsize(dst), "renamed": False}
    except PermissionError:
        stem, ext = os.path.splitext(dst)
        alt = "%s_locked%s" % (stem, ext)
        if os.path.exists(alt):
            _writable(alt)
        try:
            shutil.copy2(src, alt)
            _writable(alt)
        except PermissionError:
            # 连备用名也被占：退回时间戳，保证这次归档不丢
            alt = "%s_%s%s" % (stem, datetime.now().strftime("%H%M%S"), ext)
            shutil.copy2(src, alt)
            _writable(alt)
        return {"src": src, "path": alt, "bytes": os.path.getsize(alt), "renamed": True}


def _ensure_readme(root: str) -> None:
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, "_说明.txt")
    # 每次都重写：归档规则变了以后，旧的说明不能留在那儿误导人
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(README)


def archive_figure(spec: dict, report: dict, at: datetime | None = None) -> dict:
    """把一次导出的成品复制进桌面归档，返回清单；失败项如实记进 errors。"""
    at = at or datetime.now()
    day = at.strftime("%Y-%m-%d")
    ds = spec["data"]["dataset"]
    base = spec["export"]["base"]
    items, errors = [], []
    # 归档根可被规格覆盖：自测图写到临时目录，不污染用户桌面归档
    root = str(spec.get("export", {}).get("archive_root") or "").strip() \
        or paths.archive_root()

    try:
        _ensure_readme(root)
    except Exception as e:                                  # 桌面不可写时不能静默
        errors.append("归档目录不可用：%s: %s" % (type(e).__name__, e))
        return {"day": day, "root": root, "items": [], "errors": errors, "n": 0}

    for it in report.get("files", []):
        if not it.get("exists_and_magic_ok"):
            continue
        if it.get("role") == "preview":
            continue        # PNG 预览只服务网页缩略图与机器核验，不当作交付件
        fmt = it["format"]
        if fmt == "png":
            dst = os.path.join(os.path.join(root, day, KIND_IMAGE, "png"),
                               base + "_600dpi.png")
        else:
            dst = os.path.join(os.path.join(root, day, KIND_IMAGE, fmt),
                               base + "." + fmt)
        try:
            item = _copy(it["path"], dst)
            if item.get("renamed"):
                errors.append("%s 归档时目标文件被占用，已另存为 %s"
                              % (fmt, os.path.basename(item["path"])))
            items.append(dict(item, kind=KIND_IMAGE, format=fmt))
        except Exception as e:
            errors.append("%s 归档失败：%s: %s" % (fmt, type(e).__name__, e))

    # ---- 原始 / 处理后分别落一份 CSV，文件名用图名（日期+类别+作图）
    for kind, src, name in (
        ("原始", paths.raw_long(ds), "%s_原始.csv" % base),
        ("处理后", paths.working(ds), "%s_处理后.csv" % base),
    ):
        if not os.path.isfile(src):
            errors.append("%s 数据缺失：%s" % (kind, src))
            continue
        dst = os.path.join(os.path.join(root, day, KIND_DATA, kind), name)
        try:
            item = _copy(src, dst)
            if item.get("renamed"):
                errors.append("%s 数据被其他程序占用，已另存为 %s"
                              % (kind, os.path.basename(item["path"])))
            items.append(dict(item, kind=KIND_DATA, format="csv", label=kind))
        except Exception as e:
            errors.append("%s 数据归档失败：%s: %s" % (kind, type(e).__name__, e))

    # ---- 报告：导出自检 / 核验 / 几何量 / 每点坐标
    outdir = paths.absolute(spec["export"]["dir"])
    for name in ("export_report.json", "verify_report.json",
                 "geometry.json", "points.json"):
        src = os.path.join(outdir, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(os.path.join(root, day, KIND_REPORT, base), name)
        try:
            items.append(dict(_copy(src, dst), kind=KIND_REPORT, format="json"))
        except Exception as e:
            errors.append("%s 报告归档失败：%s: %s" % (name, type(e).__name__, e))

    return {"day": day, "root": root,
            "dir": os.path.join(root, day),
            "items": items, "errors": errors, "n": len(items)}


def archive_extra(spec: dict, src: str, sub: str, at: datetime | None = None) -> dict:
    """额外成品（目前是 PPTX）也进桌面归档：图片\\<sub>\\<图名>.<ext>。

    PPT 是给汇报用的交付件，和分析图放同一层「图片」下按格式分目录，
    找的时候不用记它到底是哪一类。
    """
    at = at or datetime.now()
    day = at.strftime("%Y-%m-%d")
    base = spec["export"]["base"]
    root = str(spec.get("export", {}).get("archive_root") or "").strip() \
        or paths.archive_root()
    ext = os.path.splitext(src)[1].lower()
    dst = os.path.join(os.path.join(root, day, KIND_IMAGE, sub), base + ext)
    try:
        _ensure_readme(root)
        item = _copy(src, dst)
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "dst": dst}
    return dict(item, ok=True, kind=KIND_IMAGE, format=ext.lstrip("."), day=day)


def archive_index(limit_days: int = 8) -> dict:
    """给界面用：列出归档根目录下最近几天的成品，按日期倒序。"""
    root = paths.archive_root()
    out = {"root": root, "exists": os.path.isdir(root), "days": []}
    if not out["exists"]:
        return out
    days = sorted((d for d in os.listdir(root)
                   if os.path.isdir(os.path.join(root, d))), reverse=True)[:limit_days]
    for d in days:
        files = []
        for dirpath, _dirs, names in os.walk(os.path.join(root, d)):
            for n in names:
                p = os.path.join(dirpath, n)
                files.append({"name": n,
                              "rel": os.path.relpath(p, root).replace("\\", "/"),
                              "bytes": os.path.getsize(p)})
        files.sort(key=lambda x: x["rel"])
        out["days"].append({"day": d, "n": len(files), "files": files})
    return out
