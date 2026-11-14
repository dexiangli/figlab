# -*- coding: utf-8 -*-
"""数据层 · 工作台事务：像 Origin 工作表那样直接改数据。

一次提交 = 一个事务：先在内存里把全部操作跑完 → 全量校验 → 一次写盘 →
一条台账 → 一个历史快照。任何一步不合格，整批改动都不落盘（回滚）。

不破坏既有契约：
  * 原始快照 raw/ 永不动，只有 working.csv 可写；
  * 排除（include=0）必须写理由，理由同时进该行 note，验收口径与 diff.py 一致；
  * 台账仍只有 ingest / modify / exclude / export 四类，细分用 subtype；
  * 插入行用「小数序号」，原有仪器点序一个都不改，四类比对不会把整条曲线误报成丢失+新增；
  * 历史快照存在顶层 history/，不往数据集目录里加第四块文件。

公式用受限 AST 白名单求值，绝不用 eval —— 本地服务虽只监听 127.0.0.1，
也不能让一个文本框变成任意代码执行入口。
"""
from __future__ import annotations

import ast
import copy
import json
import math
import os
import string

from .. import paths
from . import NUMERIC_COLUMNS, columns
from .dataset import append_ledger, now, read_long, write_long
from .diff import compare

HISTORY_DIR = os.path.join(paths.ROOT, "history")
MAX_HISTORY = 60

# 只读字段：身份列不允许在表格里被直接改写，participation 必须走带理由的入口
IMMUTABLE = {"curve", "point_index", "include"}

_FUNCS = {
    "abs": abs, "sqrt": math.sqrt, "exp": math.exp,
    "log": math.log, "log10": math.log10,
    "sin": math.sin, "cos": math.cos,
    "pow": math.pow, "min": min, "max": max,
}


# ---------------------------------------------------------------- 公式求值
def eval_formula(expr: str, env: dict) -> float:
    """受限表达式：数字 + 变量 + 四则 + 括号 + 白名单函数。"""
    if not str(expr).strip():
        raise ValueError("公式为空")
    try:
        tree = ast.parse(str(expr), mode="eval")
    except SyntaxError as e:
        raise ValueError("公式语法错误：%s" % e)

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("公式里只允许数字常量")
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ValueError("未知变量 %r；可用：%s" % (node.id, ", ".join(sorted(env))))
            return float(env[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = ev(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return a + b
            if isinstance(op, ast.Sub):
                return a - b
            if isinstance(op, ast.Mult):
                return a * b
            if isinstance(op, ast.Div):
                if b == 0:
                    raise ValueError("公式除以零")
                return a / b
            if isinstance(op, ast.Pow):
                return a ** b
            if isinstance(op, ast.Mod):
                return a % b
            raise ValueError("公式含不支持的运算符")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                raise ValueError("公式只允许这些函数：%s" % ", ".join(sorted(_FUNCS)))
            if node.keywords:
                raise ValueError("公式不支持关键字参数")
            args = [ev(a) for a in node.args]
            try:
                return float(_FUNCS[node.func.id](*args))
            except (ValueError, OverflowError) as e:
                raise ValueError("公式函数求值失败：%s" % e)
        raise ValueError("公式含不允许的语法：%s" % type(node).__name__)

    v = float(ev(tree))
    if not math.isfinite(v):
        raise ValueError("公式结果不是有限数")
    return v


def formula_env(row: dict, spectrum: str, field: str, row_no: int) -> dict:
    cols = columns(spectrum)
    env = {
        "x": float(row[field]),       # 当前列原值，最常用
        "i": float(row_no),           # 曲线内行号，从 1 起（类似 Origin 的 i）
        "row": float(row_no),
    }
    for k in NUMERIC_COLUMNS[spectrum]:
        try:
            env[k] = float(row[k])
        except (KeyError, TypeError, ValueError):
            pass
    # 列字母按长表列顺序映射（A=curve …），只对能转成数字的列生效
    for letter, k in zip(string.ascii_uppercase, cols):
        try:
            env[letter] = float(row[k])
        except (KeyError, TypeError, ValueError):
            pass
    return env


# ---------------------------------------------------------------- 历史快照
def _hist_path(name: str) -> str:
    return os.path.join(HISTORY_DIR, name + ".json")


def _same(a: list, b: list) -> bool:
    return len(a) == len(b) and all(x == y for x, y in zip(a, b))


def _trim(h: dict, index: int | None = None) -> dict:
    i = h["index"] if index is None else index
    return {"dataset": h["dataset"], "stack": h["stack"][:i + 1], "index": i}


def _save_history(h: dict) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(_hist_path(h["dataset"]), "w", encoding="utf-8") as fh:
        json.dump(h, fh, ensure_ascii=False)


def load_history(name: str, disk_rows: list) -> dict:
    """读入历史；若 working.csv 被外部（或旧接口）直接改过，把当前状态补成一帧。"""
    p = _hist_path(name)
    h = None
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as fh:
                h = json.load(fh)
        except (ValueError, OSError):
            h = None
    if not isinstance(h, dict) or not h.get("stack"):
        h = {"dataset": name, "index": 0,
             "stack": [{"at": now(), "label": "初始工作副本",
                        "rows": copy.deepcopy(disk_rows)}]}
        _save_history(h)
        return h
    h["index"] = max(0, min(int(h["index"]), len(h["stack"]) - 1))
    if not _same(h["stack"][h["index"]]["rows"], disk_rows):
        h = _trim(h)
        h["stack"].append({"at": now(), "label": "外部直接编辑 working.csv",
                           "rows": copy.deepcopy(disk_rows)})
        h["index"] = len(h["stack"]) - 1
        _save_history(h)
    return h


def push_history(h: dict, rows: list, label: str) -> dict:
    h = _trim(h)
    h["stack"].append({"at": now(), "label": label, "rows": copy.deepcopy(rows)})
    if len(h["stack"]) > MAX_HISTORY:
        h["stack"] = h["stack"][-MAX_HISTORY:]
    h["index"] = len(h["stack"]) - 1
    _save_history(h)
    return h


# ---------------------------------------------------------------- 行定位
def _pos(rows: list, curve: str, idx) -> int:
    s = str(idx)
    for i, r in enumerate(rows):
        if r.get("curve") == curve and str(r.get("point_index")) == s:
            return i
    raise KeyError("找不到行 curve=%r point_index=%r" % (curve, idx))


def _curve_rows(rows: list, curve: str) -> list[int]:
    return [i for i, r in enumerate(rows) if r.get("curve") == curve]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _new_index(rows: list, curve: str, after) -> str:
    """在 after 之后插入：序号取相邻两点中点；原有点序一个都不改。"""
    pos = _pos(rows, curve, after)
    seq = _curve_rows(rows, curve)
    k = seq.index(pos)
    used = {str(rows[i]["point_index"]) for i in seq}
    if k + 1 < len(seq):
        a = _f(after)
        b = _f(rows[seq[k + 1]]["point_index"])
        if a is not None and b is not None and b > a:
            cand = (a + b) / 2.0
            while ("%g" % cand) in used:
                cand = (a + cand) / 2.0
            return "%g" % cand
        base = str(after) + "+1"
        n = 1
        while base in used:
            n += 1
            base = str(after) + "+%d" % n
        return base
    vals = [_f(rows[i]["point_index"]) for i in seq]
    vals = [v for v in vals if v is not None]
    cand = (max(vals) if vals else len(seq)) + 1.0
    while ("%g" % cand) in used:
        cand += 1.0
    return "%g" % cand


def _seed_row(rows: list, curve: str, after, spectrum: str) -> dict:
    """人工插入行的默认数值：相邻两点线性内插，不凭空造未测得的量级。"""
    pos = _pos(rows, curve, after)
    r = dict(rows[pos])
    seq = _curve_rows(rows, curve)
    k = seq.index(pos)
    nxt = rows[seq[k + 1]] if k + 1 < len(seq) else None
    for c in NUMERIC_COLUMNS[spectrum]:
        a, b = _f(r.get(c)), _f(nxt.get(c)) if nxt else None
        r[c] = repr((a + b) / 2.0 if (a is not None and b is not None) else (a or 0.0))
    r["include"] = "1"
    r["note"] = "人工插入（工作台），待填实测值"
    return r


# ---------------------------------------------------------------- 事务
def _apply_one(rows: list, op: dict, spectrum: str, details: list) -> bool:
    """返回本批是否含排除动作。所有失败都抛异常 → 整批回滚。"""
    t = op.get("op")
    cols = columns(spectrum)
    nums = NUMERIC_COLUMNS[spectrum]

    if t == "cell":
        curve, idx, field = op["curve"], op["point_index"], op["field"]
        if field in IMMUTABLE:
            raise ValueError("字段 %r 不能在单元格里直接改（参与标记请用排除/恢复并写理由）" % field)
        if field not in cols:
            raise ValueError("未知字段 %r" % field)
        r = rows[_pos(rows, curve, idx)]
        val = op["value"]
        if field in nums:
            try:
                val = float(val)
                if not math.isfinite(val):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("数值列 %r 必须是有限数字：%r" % (field, op["value"]))
            val = repr(val)
        old = r.get(field, "")
        r[field] = str(val)
        details.append({"op": t, "curve": curve, "point_index": str(idx),
                        "field": field, "old": old, "new": r[field]})
        return False

    if t == "note":
        r = rows[_pos(rows, op["curve"], op["point_index"])]
        old = r.get("note", "")
        r["note"] = str(op.get("note", ""))
        details.append({"op": t, "curve": op["curve"],
                        "point_index": str(op["point_index"]),
                        "field": "note", "old": old, "new": r["note"]})
        return False

    if t == "include":
        want = bool(op.get("include"))
        reason = str(op.get("reason", "")).strip()
        if not want and not reason:
            raise ValueError("不合格操作：排除数据点必须写理由（规范 §一.7 / §九）")
        r = rows[_pos(rows, op["curve"], op["point_index"])]
        old = r.get("include", "1")
        r["include"] = "1" if want else "0"
        if reason:
            tag = ("恢复：" if want else "排除：") + reason
            if tag not in r.get("note", ""):
                r["note"] = (r.get("note", "") + " | " + tag).strip(" |")
        details.append({"op": t, "curve": op["curve"],
                        "point_index": str(op["point_index"]),
                        "old": old, "new": r["include"], "reason": reason})
        return not want

    if t == "insert":
        curve = op["curve"]
        after = op.get("after")
        if after is not None:
            seed = _seed_row(rows, curve, after, spectrum)
            seed["point_index"] = _new_index(rows, curve, after)
        else:
            seq = _curve_rows(rows, curve)
            if not seq:
                raise ValueError("曲线 %r 没有行，无法插入" % curve)
            seed = dict(rows[seq[0]])
            used = {str(rows[i]["point_index"]) for i in seq}
            first = _f(seed["point_index"])
            cand = (first - 1.0) if first is not None else 0.5
            while ("%g" % cand) in used:
                cand -= 1.0
            seed["point_index"] = "%g" % cand
            seed["include"] = "1"
            seed["note"] = "人工插入（工作台），待填实测值"
        for k, v in (op.get("values") or {}).items():
            if k in IMMUTABLE:
                continue
            if k in nums:
                seed[k] = repr(float(v))
            elif k in columns(spectrum):
                seed[k] = str(v)
        pos = _pos(rows, curve, after) + 1 if after is not None else _curve_rows(rows, curve)[0]
        rows.insert(pos, seed)
        details.append({"op": t, "curve": curve, "after": str(after),
                        "new_point_index": seed["point_index"]})
        return False

    if t == "delete":
        idxs = op.get("indices") or [op.get("point_index")]
        for idx in idxs:
            rows.pop(_pos(rows, op["curve"], idx))
        details.append({"op": t, "curve": op["curve"],
                        "indices": [str(i) for i in idxs],
                        "reason": str(op.get("reason", ""))})
        return False

    if t == "paste":
        matrix = op.get("matrix") or []
        if not matrix:
            raise ValueError("粘贴块为空")
        start = op.get("start_field")
        if start not in cols or start in IMMUTABLE:
            raise ValueError("粘贴起始列 %r 不可写" % start)
        si = cols.index(start)
        fields = [c for c in cols[si:] if c not in {"curve", "point_index", "include"}]
        fields = fields[:max(len(row) for row in matrix)]
        seq = _curve_rows(rows, op["curve"])
        p0 = seq.index(_pos(rows, op["curve"], op["start_index"]))
        if p0 + len(matrix) > len(seq):
            raise ValueError("粘贴块 %d 行超出该曲线剩余 %d 行；请先插入行" %
                             (len(matrix), len(seq) - p0))
        n = 0
        for j, line in enumerate(matrix):
            r = rows[seq[p0 + j]]
            for k, val in enumerate(line[:len(fields)]):
                if val is None or str(val).strip() == "":
                    continue        # 空单元格保留原值，符合 Excel/Origin 粘贴习惯
                f = fields[k]
                if f in nums:
                    try:
                        v = float(str(val).replace(",", ""))
                        if not math.isfinite(v):
                            raise ValueError
                    except (TypeError, ValueError):
                        raise ValueError("第 %d 行 %r 列不是数字：%r" % (j + 1, f, val))
                    r[f] = repr(v)
                else:
                    r[f] = str(val)
                n += 1
        details.append({"op": t, "curve": op["curve"],
                        "start_index": str(op["start_index"]),
                        "start_field": start, "fields": fields,
                        "rows": len(matrix), "cells": n})
        return False

    if t == "formula":
        field = op.get("field")
        if field not in nums:
            raise ValueError("公式只能写数值列：%r" % field)
        seq = _curve_rows(rows, op["curve"])
        idxs = op.get("indices")
        if idxs:
            wanted = {str(i) for i in idxs}
            seq = [i for i in seq if str(rows[i]["point_index"]) in wanted]
        if not seq:
            raise ValueError("公式没有选中任何行")
        expr = str(op.get("expr", ""))
        changed = []
        for n, i in enumerate(seq, start=1):
            r = rows[i]
            env = formula_env(r, spectrum, field, n)
            old = r[field]
            r[field] = repr(eval_formula(expr, env))
            changed.append([str(r["point_index"]), old, r[field]])
        details.append({"op": t, "curve": op["curve"], "field": field,
                        "expr": expr, "n": len(changed), "sample": changed[:3]})
        return False

    raise ValueError("未知操作 %r" % t)


def _guard(rows: list, spectrum: str) -> None:
    """整批校验：排除理由 + 每条曲线至少 4 个参与点（处理层弧顶判定的前提）。"""
    bad = [(r.get("curve"), r.get("point_index")) for r in rows
           if str(r.get("include", "1")) == "0" and not str(r.get("note", "")).strip()]
    if bad:
        raise ValueError("不合格操作：%d 个排除点未写理由（前 3 个 %s）；整批改动已回滚" %
                         (len(bad), bad[:3]))
    by_curve = {}
    for r in rows:
        if str(r.get("include", "1")) == "1":
            by_curve[r["curve"]] = by_curve.get(r["curve"], 0) + 1
    for c, n in by_curve.items():
        if n < 4:
            raise ValueError("不合格操作：曲线 %r 只剩 %d 个参与点（<4 无法判定弧顶）；整批改动已回滚"
                             % (c, n))


def apply_ops(name: str, spectrum: str, ops: list, reason: str = "",
              label: str = "工作台编辑") -> dict:
    if not isinstance(ops, list) or not ops:
        raise ValueError("没有待应用的操作")
    p = paths.working(name)
    before = read_long(p, spectrum)
    hist = load_history(name, before)          # 磁盘此刻仍是 before，可同步外部编辑
    rows = copy.deepcopy(before)
    details, has_exclude = [], False
    for k, op in enumerate(ops):
        try:
            has_exclude = _apply_one(rows, op, spectrum, details) or has_exclude
        except Exception as e:
            raise ValueError("第 %d 项操作失败：%s；整批 %d 项改动已回滚" %
                             (k + 1, e, len(ops))) from e
    _guard(rows, spectrum)
    write_long(p, spectrum, rows)              # 一次落盘
    hist = push_history(hist, rows, label)
    append_ledger(name, "modify", reason or label, subtype="workbook",
                  label=label, n_ops=len(ops), details=details[:60])
    if has_exclude:
        pts = [d for d in details if d.get("op") == "include" and d.get("new") == "0"]
        append_ledger(name, "exclude", reason or "工作台批量排除（逐点理由见 working.csv 备注）",
                      subtype="workbook_exclude",
                      points=[{"curve": d["curve"], "point_index": d["point_index"],
                               "reason": d["reason"]} for d in pts], n=len(pts))
    d = compare(name, spectrum)
    return {"ok": True, "label": label, "n_ops": len(ops), "n_rows": len(rows),
            "changes": details, "diff": d["counts"],
            "exclusions_without_reason": d["exclusions_without_reason"],
            "undo": hist["index"] > 0,
            "redo": hist["index"] < len(hist["stack"]) - 1,
            "history_index": hist["index"], "history_len": len(hist["stack"])}


def _restore(name: str, spectrum: str, kind: str) -> dict:
    rows = read_long(paths.working(name), spectrum)
    hist = load_history(name, rows)
    if kind == "undo":
        if hist["index"] <= 0:
            raise ValueError("已经到最早状态，没有可撤销的操作")
        hist["index"] -= 1
    else:
        if hist["index"] >= len(hist["stack"]) - 1:
            raise ValueError("已经到最新状态，没有可重做的操作")
        hist["index"] += 1
    frame = hist["stack"][hist["index"]]
    write_long(paths.working(name), spectrum, frame["rows"])
    _save_history(hist)
    append_ledger(name, "modify", "%s：%s" % ("撤销" if kind == "undo" else "重做", frame["label"]),
                  subtype=kind, history_index=hist["index"])
    d = compare(name, spectrum)
    return {"ok": True, "label": frame["label"], "kind": kind,
            "n_ops": 0, "n_rows": len(frame["rows"]), "changes": [],
            "diff": d["counts"], "exclusions_without_reason": d["exclusions_without_reason"],
            "undo": hist["index"] > 0,
            "redo": hist["index"] < len(hist["stack"]) - 1,
            "history_index": hist["index"], "history_len": len(hist["stack"])}


def undo(name: str, spectrum: str) -> dict:
    return _restore(name, spectrum, "undo")


def redo(name: str, spectrum: str) -> dict:
    return _restore(name, spectrum, "redo")


def workbook(name: str, spectrum: str) -> dict:
    """一次给前端表格需要的全部内容：列、行、曲线统计、四类比对、台账、撤销状态。"""
    rows = read_long(paths.working(name), spectrum)
    hist = load_history(name, rows)
    d = compare(name, spectrum)
    lp = paths.ledger(name)
    ledger = []
    if os.path.isfile(lp):
        with open(lp, encoding="utf-8") as fh:
            ledger = json.load(fh)
    curves = []
    for c in sorted({r["curve"] for r in rows}):
        sub = [r for r in rows if r["curve"] == c]
        curves.append({"curve": c, "n": len(sub),
                       "n_included": sum(1 for r in sub if str(r.get("include", "1")) == "1")})
    return {
        "dataset": name, "spectrum": spectrum,
        "columns": columns(spectrum), "numeric_columns": NUMERIC_COLUMNS[spectrum],
        "rows": rows, "n_rows": len(rows), "curves": curves,
        "diff": d["counts"],
        "exclusions_without_reason": d["exclusions_without_reason"],
        "formulas": {"variables": ["x（本列原值）", "i / row（曲线内行号，从 1 起）"]
                     + NUMERIC_COLUMNS[spectrum]
                     + ["A..Z（按列顺序，能转成数字的列）"],
                     "functions": sorted(_FUNCS)},
        "ledger_tail": ledger[-12:], "n_ledger": len(ledger),
        "undo": hist["index"] > 0,
        "redo": hist["index"] < len(hist["stack"]) - 1,
        "history_index": hist["index"], "history_len": len(hist["stack"]),
        "history_labels": [f.get("label", "") for f in hist["stack"]],
    }
