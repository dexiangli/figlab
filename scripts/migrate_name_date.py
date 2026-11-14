# -*- coding: utf-8 -*-
"""一次性迁移：把已有图名从「导出当天日期」改成「数据日期」，并冻结。

背景（2026-11-14 用户反馈）：
    同一批 eis_20261107 数据，11-13 导出得到 20261113阻抗作图，
    11-14 再导出又得到 20261114阻抗作图，桌面上同一份数据攒了两个日期文件夹。
    现在命名日期一律取数据自身的日期（数据集名里的 20261107），写进
    export.name_date 后不再随天变化。

用法：python scripts/migrate_name_date.py [--apply]
不带 --apply 只打印计划，不动任何文件。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import handoff, paths                     # noqa: E402
from figlab.spec.merge import data_date, resolve_name  # noqa: E402


def migrate_specs(apply: bool) -> list[dict]:
    acts = []
    sdir = paths.SPECS
    if not os.path.isdir(sdir):
        return acts
    for name in sorted(os.listdir(sdir)):
        if not name.endswith(".json"):
            continue
        p = os.path.join(sdir, name)
        with open(p, encoding="utf-8") as fh:
            spec = json.load(fh)
        ex = spec.setdefault("export", {})
        if not ex.get("auto_name"):
            continue
        before = ex.get("base")
        day = data_date(spec.get("data", {}).get("dataset", ""))
        spec.setdefault("export", {})["name_date"] = day
        spec, _ = resolve_name(spec)
        after = spec["export"]["base"]
        acts.append({"file": name, "id": spec.get("id"), "day": day,
                     "before": before, "after": after, "changed": before != after})
        if apply and before != after:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(spec, fh, ensure_ascii=False, indent=1)
    return acts


def migrate_desktop(apply: bool) -> list[dict]:
    """桌面成品文件夹跟着改名：一次改文件夹 + 里面的文件 + 项目文件里的名字。"""
    acts = []
    root = handoff.out_root()
    if not os.path.isdir(root):
        return acts
    for d in sorted(os.listdir(root)):
        full = os.path.join(root, d)
        if not os.path.isdir(full):
            continue
        proj = os.path.join(full, d + handoff.PROJECT_EXT)
        if not os.path.isfile(proj):
            continue
        with open(proj, encoding="utf-8") as fh:
            doc = json.load(fh)
        ex = (doc.get("spec") or {}).get("export") or {}
        if not ex.get("auto_name"):
            continue
        day = data_date((doc.get("spec") or {}).get("data", {}).get("dataset", ""))
        # 用平台的命名函数，别在这里自己拼类别
        from figlab.spec.merge import default_base
        new_base = default_base(doc["spec"]["data"]["dataset"],
                                doc["spec"]["data"].get("spectrum", "eis"),
                                str(ex.get("name_suffix", "")), date=day)
        if new_base == d:
            continue
        dst = os.path.join(root, new_base)
        acts.append({"dir": full, "to": dst, "from": d, "to_name": new_base,
                     "exists": os.path.exists(dst)})
        if not apply:
            continue
        if os.path.exists(dst):
            acts[-1]["skipped"] = "目标文件夹已存在，未动"
            continue
        os.rename(full, dst)
        for fn in os.listdir(dst):
            stem, ext = os.path.splitext(fn)
            if stem != d:
                continue
            os.rename(os.path.join(dst, fn), os.path.join(dst, new_base + ext))
        pj = os.path.join(dst, new_base + handoff.PROJECT_EXT)
        with open(pj, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["title"] = new_base
        doc["spec"].setdefault("export", {})["base"] = new_base
        doc["spec"]["export"]["name_date"] = day
        with open(pj, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
    return acts


def main() -> int:
    apply = "--apply" in sys.argv
    print("模式：%s" % ("执行" if apply else "预览（加 --apply 才动文件）"))
    print("\n[1] 规格文件")
    for a in migrate_specs(apply):
        print("  %-16s %-18s %s -> %s%s" % (a["file"], a["id"], a["before"],
                                            a["after"], "" if a["changed"] else "（已是新名）"))
    print("\n[2] 桌面成品文件夹")
    ds = migrate_desktop(apply)
    if not ds:
        print("  无需处理")
    for a in ds:
        print("  %s -> %s%s" % (a["from"], a["to_name"],
                                "  [" + a.get("skipped", "") + "]" if a.get("skipped") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
