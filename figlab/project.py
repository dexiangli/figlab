# -*- coding: utf-8 -*-
"""项目管理器：一张图一个「窗口」，窗口归到文件夹里（仿 Origin 的 Project Explorer）。

用户要的是「一个项目里装很多任务」：同一天做的阻抗、光热、CV 各自成窗，
按课题/日期分文件夹摆好，随时点开继续改，而不是一个对话只管一张图。

存储就一个文件 figures.json（保持「无数据库、文件即契约」）：

    {"version": 2,
     "folders": [{"id": "f1", "name": "Folder1", "open": true, "order": 1}],
     "figures": [{"id": "eis_main", "preset": "inhouse", "spec": "...",
                  "folder": "f1", "title": "20261113阻抗作图", "order": 1}]}

老版本只有 {"figures": [{id,preset,spec}]}：读的时候自动补默认文件夹，
不丢原有页签。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from . import paths

VERSION = 2
ROOT_NAME = "figlab 项目"
DEFAULT_FOLDER = "f_default"


def _empty() -> dict:
    return {"version": VERSION, "folders": [], "figures": []}


def load() -> dict:
    data = _empty()
    if os.path.isfile(paths.FIGURES):
        try:
            with open(paths.FIGURES, encoding="utf-8") as fh:
                data = json.load(fh) or _empty()
        except Exception:
            data = _empty()
    data.setdefault("folders", [])
    data.setdefault("figures", [])
    data["version"] = VERSION
    # 老格式迁移：没有文件夹就补一个，现有图全部放进去
    if not data["folders"]:
        data["folders"].append({"id": DEFAULT_FOLDER, "name": "Folder1",
                                "open": True, "order": 1})
    ids = {f["id"] for f in data["folders"]}
    for i, fig in enumerate(data["figures"]):
        if fig.get("folder") not in ids:
            fig["folder"] = data["folders"][0]["id"]
        fig.setdefault("title", fig.get("id", ""))
        fig.setdefault("order", i + 1)
    return data


def save(data: dict) -> str:
    paths.ensure_dirs(os.path.dirname(paths.FIGURES))
    tmp = paths.FIGURES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, paths.FIGURES)          # 原子替换：写一半崩掉也不会毁掉项目
    return paths.FIGURES


def _folder(data: dict, fid: str) -> dict | None:
    return next((f for f in data["folders"] if f["id"] == fid), None)


def _figure(data: dict, fig_id: str) -> dict | None:
    return next((f for f in data["figures"] if f["id"] == fig_id), None)


def _next_order(items: list[dict]) -> int:
    return max([int(x.get("order", 0)) for x in items] or [0]) + 1


# ------------------------------------------------------------------ 图（窗口）
def ensure(fig_id: str, preset: str = "inhouse", title: str = "",
           folder: str = "") -> dict:
    """注册/更新一张图；已有条目的 folder、title 不被覆盖（重绘不该挪位置）。"""
    data = load()
    fig = _figure(data, fig_id)
    if fig is None:
        fig = {"id": fig_id, "preset": preset, "spec": paths.spec_file(fig_id),
               "folder": folder or data["folders"][0]["id"],
               "title": title or fig_id, "order": _next_order(data["figures"]),
               "created": datetime.now().isoformat(timespec="seconds")}
        data["figures"].append(fig)
    else:
        fig["preset"] = preset or fig.get("preset", "")
        fig["spec"] = paths.spec_file(fig_id)
        # title 只在新建时给一次：用户改过的显示名不能被重绘刷掉
    save(data)
    return fig


def rename_figure(fig_id: str, title: str) -> dict:
    data = load()
    fig = _figure(data, fig_id)
    if fig is None:
        return {"ok": False, "error": "没有这张图：%s" % fig_id}
    fig["title"] = str(title or "").strip() or fig_id
    save(data)
    return {"ok": True, "id": fig_id, "title": fig["title"]}


def move_figure(fig_id: str, folder: str) -> dict:
    data = load()
    fig = _figure(data, fig_id)
    if fig is None:
        return {"ok": False, "error": "没有这张图：%s" % fig_id}
    if _folder(data, folder) is None:
        return {"ok": False, "error": "没有这个文件夹：%s" % folder}
    fig["folder"] = folder
    fig["order"] = _next_order([x for x in data["figures"] if x["folder"] == folder])
    save(data)
    return {"ok": True, "id": fig_id, "folder": folder}


def drop(fig_id: str) -> dict:
    """从项目里移除一张图（规格文件由调用方决定删不删）。"""
    data = load()
    data["figures"] = [f for f in data["figures"] if f["id"] != fig_id]
    save(data)
    return {"ok": True, "figures": data["figures"]}


# ------------------------------------------------------------------ 文件夹
def new_folder(name: str = "") -> dict:
    data = load()
    n = len(data["folders"]) + 1
    base = (name or "Folder%d" % n).strip() or "Folder%d" % n
    existing = {f["name"] for f in data["folders"]}
    cand, k = base, 2
    while cand in existing:
        cand = "%s (%d)" % (base, k)
        k += 1
    fid = "f_%s" % re.sub(r"[^A-Za-z0-9]", "", datetime.now().strftime("%H%M%S%f"))[:10]
    data["folders"].append({"id": fid, "name": cand, "open": True,
                            "order": _next_order(data["folders"])})
    save(data)
    return {"ok": True, "id": fid, "name": cand}


def rename_folder(fid: str, name: str) -> dict:
    data = load()
    f = _folder(data, fid)
    if f is None:
        return {"ok": False, "error": "没有这个文件夹：%s" % fid}
    f["name"] = str(name or "").strip() or f["name"]
    save(data)
    return {"ok": True, "id": fid, "name": f["name"]}


def toggle_folder(fid: str) -> dict:
    data = load()
    f = _folder(data, fid)
    if f is None:
        return {"ok": False, "error": "没有这个文件夹：%s" % fid}
    f["open"] = not f.get("open", True)
    save(data)
    return {"ok": True, "id": fid, "open": f["open"]}


def delete_folder(fid: str) -> dict:
    """删文件夹不删图：里面的图退回第一个文件夹（项目里不会凭空少东西）。"""
    data = load()
    if _folder(data, fid) is None:
        return {"ok": False, "error": "没有这个文件夹：%s" % fid}
    if len(data["folders"]) == 1:
        return {"ok": False, "error": "只剩一个文件夹，不能删（先新建一个再接）"}
    data["folders"] = [f for f in data["folders"] if f["id"] != fid]
    keep = data["folders"][0]["id"]
    moved = 0
    for fig in data["figures"]:
        if fig["folder"] == fid:
            fig["folder"] = keep
            moved += 1
    save(data)
    return {"ok": True, "moved": moved, "folder": keep}


# ------------------------------------------------------------------ 给界面
def snapshot() -> dict:
    """项目树：文件夹 + 图；图片带导出名与导出时间，界面直接显示不用再查。"""
    data = load()
    figs = []
    for fig in sorted(data["figures"], key=lambda x: int(x.get("order", 0))):
        item = dict(fig)
        spec_path = paths.spec_file(fig["id"])
        item["exists"] = os.path.isfile(spec_path)
        item["base"], item["mtime"], item["n_curves"] = "", "", 0
        if item["exists"]:
            try:
                with open(spec_path, encoding="utf-8") as fh:
                    spec = json.load(fh)
                item["base"] = spec.get("export", {}).get("base", "")
                item["n_curves"] = sum(1 for s in spec.get("series", [])
                                       if s.get("include", True))
                item["mtime"] = datetime.fromtimestamp(
                    os.path.getmtime(spec_path)).strftime("%m-%d %H:%M")
            except Exception:
                item["exists"] = False
        # 没改过名的窗口直接显示导出名（20261113阻抗作图），比 eis_wide 更像 Origin
        if item.get("title", fig["id"]) == fig["id"] and item["base"]:
            item["title"] = item["base"]
        figs.append(item)
    return {"root": ROOT_NAME,
            "folders": sorted(data["folders"], key=lambda x: int(x.get("order", 0))),
            "figures": figs}
