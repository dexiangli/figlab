# -*- coding: utf-8 -*-
"""数据集目录契约：每个数据集固定三块，不多不少。

    <name>/raw/sources/   源文件字节副本（写入后只读）
    <name>/raw/raw_long.csv / raw_meta.json   长表快照 + 元数据
    <name>/working.csv    唯一绘图输入，允许人工编辑
    <name>/ledger.json    摄取 / 修改 / 排除 / 导出 + 理由

raw/ 一旦写入即置只读；重复摄取必须显式 force=True 并写进台账。
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import stat
from datetime import datetime

from .. import paths
from . import columns
from .ingest import (PARSERS, count_chi_bin_points, group_by_stem, load_sources,
                     sha256)

ENCODING = "utf-8-sig"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _set_readonly(path: str, ro: bool) -> None:
    try:
        os.chmod(path, stat.S_IREAD if ro else stat.S_IWRITE)
    except OSError:
        pass  # 某些文件系统不支持，不因此中断


def read_long(path: str, spectrum: str) -> list[dict]:
    with open(path, "r", encoding=ENCODING, newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def write_long(path: str, spectrum: str, rows: list[dict]) -> None:
    cols = columns(spectrum)
    with open(path, "w", encoding=ENCODING, newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def append_ledger(name: str, action: str, reason: str, **detail) -> None:
    p = paths.ledger(name)
    data = []
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    rec = {"at": now(), "action": action, "reason": reason}
    rec.update(detail)
    data.append(rec)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class Dataset:
    def __init__(self, name: str, spectrum: str = "eis"):
        self.name = name
        self.spectrum = spectrum
        columns(spectrum)  # 早校验

    # ------------------------------------------------------------ 摄取
    def ingest(self, src: str, force: bool = False, reason: str = "") -> dict:
        rl, rm, wk, lg = (paths.raw_long(self.name), paths.raw_meta(self.name),
                          paths.working(self.name), paths.ledger(self.name))
        if os.path.exists(rl) and not force:
            raise RuntimeError("原始快照已存在，写入后只读；要重摄取须显式 force=True")
        if force and os.path.exists(rl):
            _set_readonly(rl, False)
            _set_readonly(rm, False)
            for f in os.listdir(paths.sources_dir(self.name)):
                _set_readonly(os.path.join(paths.sources_dir(self.name), f), False)

        paths.ensure_dirs(paths.sources_dir(self.name))
        files = load_sources(src)
        chosen, skipped, bin_only = group_by_stem(files)

        # 1) 所有源文件字节原样落盘（含被跳过与未纳入的），保证哈希可复核
        for fname, blob in files:
            with open(os.path.join(paths.sources_dir(self.name), fname), "wb") as fh:
                fh.write(blob)

        # 2) 解析被选中的文本导出，点序照抄文件行序
        parser = PARSERS[self.spectrum]
        rows, sources = [], []
        for stem, (fname, _ext, blob) in chosen:
            info = parser(blob)
            cols = columns(self.spectrum)
            for i, r in enumerate(info["rows"], start=1):
                rec = {"curve": stem, "point_index": i, "include": "1", "note": ""}
                for k in cols:
                    if k in r:
                        rec[k] = r[k]
                rows.append(rec)
            src_rec = {
                "file": fname, "kind": "TEXT", "sha256": sha256(blob),
                "points": len(info["rows"]), "stamp": info["stamp"],
                "params": info["params"], "encoding": info["encoding"],
                "status": "ingested", "skipped_duplicate": "",
                "first": info.get("freq_first", info.get("time_first_s")),
                "last": info.get("freq_last", info.get("time_last_s")),
            }
            # 记录同主干被跳过的二进制文件
            dup = [s["file"] for s in skipped if os.path.splitext(s["file"])[0] == stem]
            src_rec["skipped_duplicate"] = ", ".join(dup)
            sources.append(src_rec)

        for s in skipped:
            fname = s["file"]
            blob = dict(files)[fname]
            sources.append({
                "file": fname, "kind": "BIN" if fname.lower().endswith(".bin") else "OTHER",
                "sha256": sha256(blob), "points": None, "stamp": "", "params": {},
                "encoding": "", "status": "skipped_duplicate",
                "skipped_duplicate": "", "reason": s["reason"],
                "first": None, "last": None,
            })

        for stem, (fname, _ext, blob) in bin_only:
            sources.append({
                "file": fname, "kind": "BIN", "sha256": sha256(blob),
                "points": count_chi_bin_points(blob), "stamp": "", "params": {},
                "encoding": "", "status": "not_ingested",
                "skipped_duplicate": "",
                "reason": "该测量只有二进制导出、无文本导出；本版不纳入绘图（未解析数值，仅登记哈希与点数）",
                "first": None, "last": None,
            })

        meta = {
            "dataset": self.name, "spectrum": self.spectrum,
            "ingested_at": now(), "columns": columns(self.spectrum),
            "dedup_rule": "按文件名主干分组；组内文本导出优先，二进制记 skipped_duplicate；"
                          "禁止用频率取整去重（浮点差 3.9e-04 量级）",
            "source_of_sources": paths.display_source(src),
            "sources": sources,
            "totals": {
                "source_files": len(files),
                "text_chosen": len(chosen),
                "skipped_duplicates": len(skipped),
                "bin_only_not_ingested": len(bin_only),
                "curves": len(chosen),
                "points": len(rows),
            },
        }

        write_long(rl, self.spectrum, rows)
        with open(rm, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        shutil.copyfile(rl, wk)  # 工作副本起始内容 == 原始快照
        if os.path.exists(lg):
            os.remove(lg)
        append_ledger(self.name, "ingest", reason or "首次摄取仪器导出文件",
                      curves=len(chosen), points=len(rows),
                      skipped_duplicates=[s["file"] for s in skipped],
                      bin_only_not_ingested=[b[1][0] for b in bin_only])

        # 3) 原始快照写入后只读
        _set_readonly(rl, True); _set_readonly(rm, True)
        for f in os.listdir(paths.sources_dir(self.name)):
            _set_readonly(os.path.join(paths.sources_dir(self.name), f), True)

        return meta["totals"]
