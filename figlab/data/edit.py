# -*- coding: utf-8 -*-
"""人工改数据的三个入口：改数值 / 改参与标记 / 写理由（规范 §一.7）。

没有理由记录的排除视为不合格操作 —— 这里在写入前直接拒绝，不留灰色地带。
所有写操作都追加台账；原始快照永不动。
"""
from __future__ import annotations

import os

from .. import paths
from . import NUMERIC_COLUMNS
from .dataset import append_ledger, read_long, write_long


def _find(rows, curve, idx):
    for r in rows:
        if r.get("curve") == curve and str(r.get("point_index")) == str(idx):
            return r
    raise KeyError("找不到点 curve=%r point_index=%r" % (curve, idx))


def set_value(name: str, spectrum: str, curve: str, idx, field: str,
              value, reason: str = "") -> dict:
    if field not in NUMERIC_COLUMNS[spectrum]:
        raise ValueError("字段 %r 不属于谱型 %s 的数值列" % (field, spectrum))
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("数值必须是数字：%r" % value)
    p = paths.working(name)
    rows = read_long(p, spectrum)
    r = _find(rows, curve, idx)
    old = r[field]
    r[field] = repr(value)
    if reason:
        r["note"] = (r.get("note", "") + " | " + reason).strip(" |")
    write_long(p, spectrum, rows)
    append_ledger(name, "modify", reason or "改数值（未附理由）",
                  curve=curve, point_index=idx, field=field,
                  old=old, new=r[field])
    return {"curve": curve, "point_index": idx, "field": field, "old": old, "new": r[field]}


def set_include(name: str, spectrum: str, curve: str, idx, include: bool,
                reason: str) -> dict:
    """排除（include=False）必须写理由；理由同时写进该行 note，便于验收逐点查。"""
    if not include and not str(reason).strip():
        raise ValueError("不合格操作：排除数据点必须写理由（规范 §一.7 / §九）")
    p = paths.working(name)
    rows = read_long(p, spectrum)
    r = _find(rows, curve, idx)
    old = r.get("include", "1")
    r["include"] = "1" if include else "0"
    if reason.strip():
        tag = ("恢复：" if include else "排除：") + reason.strip()
        if tag not in r.get("note", ""):
            r["note"] = (r.get("note", "") + " | " + tag).strip(" |")
    write_long(p, spectrum, rows)
    # 台账只允许四类动作：ingest / modify / exclude / export；恢复归入 modify
    append_ledger(name, "exclude" if not include else "modify", reason.strip(),
                  subtype="exclude" if not include else "restore",
                  curve=curve, point_index=idx, old=old, new=r["include"])
    return {"curve": curve, "point_index": idx, "include": r["include"], "note": r["note"]}


def set_note(name: str, spectrum: str, curve: str, idx, note: str,
             reason: str = "写理由") -> dict:
    p = paths.working(name)
    rows = read_long(p, spectrum)
    r = _find(rows, curve, idx)
    r["note"] = note
    write_long(p, spectrum, rows)
    append_ledger(name, "modify", reason, curve=curve, point_index=idx, note=note)
    return {"curve": curve, "point_index": idx, "note": note}


def _short_path(p: str) -> str:
    """台账里不落本机绝对路径（发布仓库会泄露用户名）：项目内用相对路径，
    桌面下的只记「桌面/…」，其余保持原样。"""
    ap = os.path.abspath(p)
    try:
        return os.path.relpath(ap, paths.ROOT).replace("\\", "/")
    except ValueError:
        pass
    desk = paths.desktop()
    if desk and ap.lower().startswith(desk.lower() + os.sep):
        return "桌面/" + ap[len(desk) + 1:].replace("\\", "/")
    return ap


def record_export(name: str, fig_id: str, formats: list[str], paths_out: list[str],
                  reason: str = "导出投稿级图件") -> None:
    append_ledger(name, "export", reason, figure=fig_id, formats=formats,
                  files=[_short_path(p) for p in paths_out])
