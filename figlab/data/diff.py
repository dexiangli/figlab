# -*- coding: utf-8 -*-
"""改动比对：工作副本 vs 原始快照，结果严格分四类（规范 §一.6）。"""
from __future__ import annotations

from .. import paths
from . import NUMERIC_COLUMNS
from .dataset import read_long


def compare(name: str, spectrum: str = "eis") -> dict:
    raw = read_long(paths.raw_long(name), spectrum)
    work = read_long(paths.working(name), spectrum)
    key = lambda r: (r.get("curve", ""), str(r.get("point_index", "")))
    ri = {key(r): r for r in raw}
    wi = {key(r): r for r in work}
    nums = NUMERIC_COLUMNS[spectrum]

    changed, flipped, added, lost = [], [], [], []
    for k in sorted(set(ri) & set(wi), key=lambda t: (t[0], int(t[1]) if t[1].isdigit() else 0)):
        a, b = ri[k], wi[k]
        diffs = {}
        for c in nums:
            try:
                if float(a.get(c, "")) != float(b.get(c, "")):
                    diffs[c] = [a.get(c), b.get(c)]
            except (TypeError, ValueError):
                if str(a.get(c, "")) != str(b.get(c, "")):
                    diffs[c] = [a.get(c), b.get(c)]
        if diffs:
            changed.append({"key": list(k), "fields": diffs, "note": b.get("note", "")})
        if str(a.get("include", "1")) != str(b.get("include", "1")):
            flipped.append({"key": list(k), "from": a.get("include"),
                            "to": b.get("include"), "note": b.get("note", "")})
    for k in sorted(set(wi) - set(ri)):
        added.append({"key": list(k), "row": wi[k]})
    for k in sorted(set(ri) - set(wi)):
        lost.append({"key": list(k), "row": ri[k]})

    return {
        "dataset": name, "raw_rows": len(raw), "working_rows": len(work),
        "value_changed": changed, "include_flipped": flipped,
        "rows_added": added, "rows_lost": lost,
        "counts": {
            "value_changed": len(changed), "include_flipped": len(flipped),
            "rows_added": len(added), "rows_lost": len(lost),
        },
        # 验收口径：扫描工作副本里「所有」被排除的行，而不只是刚翻转的行，
        # 这样绕过 edit.py 直接手改 CSV 的排除同样会被判为不合格。
        "exclusions_without_reason": [
            [r.get("curve"), r.get("point_index")]
            for r in work
            if str(r.get("include", "1")) == "0" and not str(r.get("note", "")).strip()
        ],
    }
