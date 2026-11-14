# -*- coding: utf-8 -*-
"""成品交接 + 项目文件：桌面只放成品，一张图一个文件夹。

用户提的三件事（2026-11-14）：

1. **文件要自己找得到**：不再按「日期/图片/pdf/报告/数据」分五层，
   改成 ``桌面\\FigLab\\<图名>\\``，文件夹名就是图名，文件名也是图名。
2. **单独导出的图不要混进自动保存的目录**：只有手动点「导出」才往桌面复制；
   改动后的后台重渲染只写 ``outputs/``（内部原件），一个字节都不进桌面。
3. **以后还能在这个基础上继续调整**：同一个文件夹里放一份 ``<图名>.figlab``，
   内含完整规格 + 工作副本，打开它就恢复成一张可继续改的图。

为什么报告 json / CSV 不往桌面放：那些是核验与追溯用的，图和 PPT 才是交付件。
它们留在 ``outputs/<图ID>/`` 里，需要时界面上的文件夹按钮能直接打开。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from . import paths, project
from .spec.merge import sanitize_base

OUTPUT_NAME = "FigLab"          # 桌面上的总文件夹（比「FigLab输出」短，一眼认得出）
PROJECT_EXT = ".figlab"
KIND = "figlab-project"
VERSION = 1


def out_root(spec: dict | None = None) -> str:
    """默认 ``桌面\\FigLab``；自测图可用 ``export.handoff_root`` 指到临时目录，
    不往用户桌面撒测试文件。"""
    if spec:
        p = str((spec.get("export") or {}).get("handoff_root") or "").strip()
        if p:
            return p
    return os.path.join(paths.desktop(), OUTPUT_NAME)


def figure_dir(base: str, spec: dict | None = None) -> str:
    """一张图一个文件夹；同名图（同一天的同一张）落在同一个文件夹里。"""
    return os.path.join(out_root(spec), sanitize_base(base))


def project_path(spec: dict) -> str:
    base = sanitize_base(spec["export"]["base"])
    return os.path.join(figure_dir(base, spec), base + PROJECT_EXT)


# ------------------------------------------------------------------ 成品交付
def _writable(path: str) -> None:
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def _copy(src: str, dst: str) -> dict:
    """复制成品；目标被占用时改用固定备用名，不按时间戳越堆越多。

    src 与 dst 是同一个文件时（PPT 本来就生成在成品文件夹里）直接返回：
    Windows 上对同一路径 copy2 会抛 PermissionError，白白多出一个 _locked 副本。
    """
    import shutil

    if os.path.abspath(src) == os.path.abspath(dst):
        return {"src": src, "path": dst,
                "bytes": os.path.getsize(dst) if os.path.isfile(dst) else 0,
                "renamed": False, "same_file": True}
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
        shutil.copy2(src, alt)
        _writable(alt)
        return {"src": src, "path": alt, "bytes": os.path.getsize(alt), "renamed": True}


def deliver(spec: dict, report: dict) -> dict:
    """把本次导出的**成品**复制到桌面\\FigLab\\<图名>\\。

    只复制 role=deliverable 的图件（PDF/EPS/SVG/PNG），报告与数据一律不进桌面。
    """
    base = sanitize_base(spec["export"]["base"])
    d = figure_dir(base, spec)
    items, errors = [], []
    try:
        os.makedirs(d, exist_ok=True)
    except Exception as e:
        return {"ok": False, "dir": d, "items": [], "n": 0,
                "errors": ["桌面不可写：%s: %s" % (type(e).__name__, e)]}

    for it in report.get("files", []):
        if not it.get("exists_and_magic_ok"):
            continue
        if it.get("role") != "deliverable":
            continue        # 600 dpi 预览只服务网页与核验，不算交付件
        fmt = it["format"]
        # 用户勾了 PNG 才给；文件名不加 _600dpi，桌面上就是「图名.png」
        dst = os.path.join(d, base + "." + fmt)
        try:
            got = _copy(it["path"], dst)
            if got.get("renamed"):
                errors.append("%s 被占用，已另存为 %s" % (fmt, os.path.basename(got["path"])))
            items.append(dict(got, format=fmt))
        except Exception as e:
            errors.append("%s 交付失败：%s: %s" % (fmt, type(e).__name__, e))
    return {"ok": True, "dir": d, "items": items, "n": len(items), "errors": errors}


def deliver_extra(spec: dict, src: str) -> dict:
    """额外成品（目前是 PPTX）也放进同一个图名文件夹，不另开子目录。"""
    base = sanitize_base(spec["export"]["base"])
    d = figure_dir(base, spec)
    ext = os.path.splitext(src)[1].lower()
    dst = os.path.join(d, base + ext)
    try:
        os.makedirs(d, exist_ok=True)
        got = _copy(src, dst)
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "path": dst}
    return dict(got, ok=True, dir=d)


# ------------------------------------------------------------------ 项目文件
def save_project(fig_id: str, spec: dict | None = None) -> dict:
    """把这张图存成 ``<图名>.figlab``：规格 + 工作副本，单文件，可直接搬走。"""
    from .spec.merge import load_spec

    spec = spec if spec is not None else load_spec(fig_id)
    base = sanitize_base(spec["export"]["base"])
    ds = spec["data"]["dataset"]
    work = paths.working(ds)
    if not os.path.isfile(work):
        return {"ok": False, "error": "工作副本不存在：%s" % work}
    with open(work, encoding="utf-8") as fh:
        working = fh.read()

    doc = {
        "kind": KIND, "version": VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "id": fig_id, "title": base,
        "spec": spec,
        "data": {
            "dataset": ds,
            "working_csv": working,
            "rows": max(0, len(working.strip().splitlines()) - 1),
        },
        "note": "figlab 项目文件：规格 + 工作副本。在图库里用「打开项目」选它就能继续改。",
    }
    p = project_path(spec)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return {"ok": True, "path": p, "dir": os.path.dirname(p),
            "bytes": os.path.getsize(p), "title": base, "rows": doc["data"]["rows"]}


def read_project(text: str) -> dict:
    """解析上传上来的项目文件；结构不对就直接报错，不吞。"""
    try:
        doc = json.loads(text)
    except Exception as e:
        return {"ok": False, "error": "不是有效的项目文件（JSON 解析失败）：%s" % e}
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        return {"ok": False, "error": "不是 figlab 项目文件（缺少 kind=%s）" % KIND}
    if int(doc.get("version") or 0) > VERSION:
        return {"ok": False, "error": "项目文件版本 %s 高于当前支持的 %s"
                                      % (doc.get("version"), VERSION)}
    if not isinstance(doc.get("spec"), dict):
        return {"ok": False, "error": "项目文件里没有规格（spec）"}
    if not (doc.get("data") or {}).get("working_csv"):
        return {"ok": False, "error": "项目文件里没有工作副本（data.working_csv）"}
    return {"ok": True, "doc": doc}


def _free_id(want: str) -> str:
    """不与现有图重名：打开同一个项目两次得到两张独立的图，互不覆盖。"""
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", str(want or "proj")) or "proj"
    data = project.load()
    used = {f["id"] for f in data["figures"]}
    if not os.path.isfile(paths.spec_file(base)) and base not in used:
        return base
    k = 2
    while True:
        cand = "%s_r%d" % (base, k)
        if not os.path.isfile(paths.spec_file(cand)) and cand not in used:
            return cand
        k += 1


def import_project(doc: dict, folder: str = "") -> dict:
    """把项目文件恢复成一张可继续改的图：数据 → datasets，规格 → specs，图 → 图库。"""
    from .spec.merge import save_spec

    new_id = _free_id(doc.get("id") or doc.get("title") or "proj")
    working = doc["data"]["working_csv"]
    old_ds = (doc["spec"].get("data") or {}).get("dataset") or "proj_data"

    # 数据：内容完全一样就复用原数据集，避免同一批数在 datasets 里复制好几份
    reused = None
    for name in sorted(os.listdir(paths.DATASETS)) if os.path.isdir(paths.DATASETS) else []:
        p = paths.working(name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                if fh.read() == working:
                    reused = name
                    break
    ds = reused or ("%s_数据" % new_id)

    if not reused:
        ddir = paths.dataset_dir(ds)
        paths.ensure_dirs(ddir)
        with open(paths.working(ds), "w", encoding="utf-8", newline="") as fh:
            fh.write(working)

    spec = json.loads(json.dumps(doc["spec"]))     # 深拷贝，不动上传的原文
    spec["id"] = new_id
    spec.setdefault("data", {})["dataset"] = ds
    if not (spec.get("export") or {}).get("base"):
        spec.setdefault("export", {})["base"] = sanitize_base(
            doc.get("title") or new_id)
    spec["export"]["dir"] = paths.out_dir(new_id)
    # 打开的项目沿用保存时的图名：resolve_name 只在缺 name_date 时按数据日期补一次，
    # 有了就冻住，所以同一份项目隔几天打开也不会变成另一个名字/另一个文件夹。
    if spec["export"].get("auto_name"):
        from .spec.merge import resolve_name
        spec, _ = resolve_name(spec)

    from .spec.merge import save_spec
    save_spec(spec)
    project.ensure(new_id, spec.get("preset", "inhouse"),
                   title=doc.get("title") or new_id, folder=folder)
    return {"ok": True, "id": new_id, "dataset": ds, "reused_dataset": bool(reused),
            "title": spec["export"]["base"], "n_rows": doc["data"].get("rows", 0)}
