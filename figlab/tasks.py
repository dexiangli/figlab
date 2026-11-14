# -*- coding: utf-8 -*-
"""需求单：你在界面上写一句「我要什么」，落到 tasks/requests.jsonl，等 AI 来做。

用户的原话是「我不想进行数据处理，我只要表达一下，你帮我处理，结果在绘图平台
显示，我可以微调」。所以这里只做三件事：收需求、标状态、记下 AI 改了什么。
不做任何自动算法猜测——算法归 AI，界面只负责把需求说清楚和把结果摆出来。

一行一条 JSON（append-only 写入，改状态时整份重写，量级几十条，够用）：

    {"id":"20261113-2231-01","figure":"eis_wide","text":"8 条按 Rs 重排…",
     "status":"pending","created":"…","closed":"","reply":""}

状态：pending（待处理）/ doing（在处理）/ done（已完成）/ rejected（做不了）。
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime

from . import paths

DIR = os.path.join(paths.ROOT, "tasks")
LOG = os.path.join(DIR, "requests.jsonl")
STATUSES = ("pending", "doing", "done", "rejected")
LABEL = {"pending": "待处理", "doing": "处理中", "done": "已完成",
         "rejected": "未采纳"}


def _read() -> list[dict]:
    if not os.path.isfile(LOG):
        return []
    out = []
    with open(LOG, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _write(rows: list[dict]) -> None:
    os.makedirs(DIR, exist_ok=True)
    tmp = LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, LOG)


def add(figure: str, text: str) -> dict:
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "需求是空的"}
    if len(text) > 2000:
        return {"ok": False, "error": "一条需求别超过 2000 字，拆成几条更好处理"}
    now = datetime.now()
    rows = _read()
    seq = sum(1 for r in rows if r["created"][:10] == now.strftime("%Y-%m-%d")) + 1
    item = {"id": "%s-%03d" % (now.strftime("%Y%m%d-%H%M"), seq),
            "figure": figure, "text": text, "status": "pending",
            "created": now.isoformat(timespec="seconds"),
            "closed": "", "reply": ""}
    rows.append(item)
    _write(rows)
    return {"ok": True, "request": item}


def listing(figure: str = "", limit: int = 60) -> dict:
    rows = _read()
    if figure:
        rows = [r for r in rows if r.get("figure") == figure]
    counts = {}
    for r in rows:
        counts[r.get("status", "?")] = counts.get(r.get("status", "?"), 0) + 1
    rows = sorted(rows, key=lambda r: r.get("created", ""), reverse=True)[:limit]
    for r in rows:
        r["label"] = LABEL.get(r.get("status", ""), r.get("status", ""))
    return {"n": len(rows), "counts": counts, "requests": rows,
            "pending": counts.get("pending", 0) + counts.get("doing", 0)}


def update(req_id: str, status: str, reply: str = "") -> dict:
    if status not in STATUSES:
        return {"ok": False, "error": "状态只能是 %s" % (STATUSES,)}
    rows = _read()
    hit = None
    for r in rows:
        if r.get("id") == req_id:
            r["status"] = status
            r["reply"] = reply or r.get("reply", "")
            r["closed"] = "" if status in ("pending", "doing") else \
                datetime.now().isoformat(timespec="seconds")
            hit = r
    if hit is None:
        return {"ok": False, "error": "没有这条需求：%s" % req_id}
    _write(rows)
    return {"ok": True, "request": hit}


def drop(req_id: str) -> dict:
    """删掉一条（自测产生的噪音用；正常流程只改状态不删）。"""
    rows = _read()
    keep = [r for r in rows if r.get("id") != req_id]
    if len(keep) == len(rows):
        return {"ok": False, "error": "没有这条需求：%s" % req_id}
    _write(keep)
    return {"ok": True, "id": req_id}


def _cli(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        d = listing(limit=100)
        for r in d["requests"]:
            print("%s  [%s]  %-10s %s" % (r["id"], r["label"], r["figure"],
                                          r["text"][:70].replace("\n", " ")))
            if r.get("reply"):
                print("    → %s" % r["reply"])
        print("合计 %d 条，待处理 %d 条" % (d["n"], d["pending"]))
        return 0
    if cmd == "add" and len(argv) >= 3:
        print(add(argv[1], argv[2]))
        return 0
    if cmd in STATUSES and len(argv) >= 2:
        print(update(argv[1], cmd, " ".join(argv[2:])))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
