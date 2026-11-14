# -*- coding: utf-8 -*-
"""预设合并：单图覆盖预设参数，覆盖项写入该图规格而不改预设（规范 §三.3）。"""
from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime

from .. import paths, project
from .schema import PRESET_NAMES

# 导出件命名：<数据日期><类别>作图，例如 20261107阻抗作图.pdf
# 日期取数据自己带的（数据集名/原始文件），不是导出当天的——同一批数据隔几天
# 再导，名字还是同一个，落在同一个文件夹里覆盖，不堆出「一天一份」。
CATEGORY = {"eis": "阻抗", "photothermal": "光热"}


def category_of(dataset: str, spectrum: str = "") -> str:
    return (CATEGORY.get(spectrum) or CATEGORY.get(str(dataset).split("_")[0], "")
            or "图")


def sanitize_base(name: str) -> str:
    """Windows 文件名非法字符替换掉；空名回退为「图」。"""
    s = re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip().strip(".")
    return s or "图"


def data_date(dataset: str) -> str:
    """数据自身的日期（YYYYMMDD），用来定名——**不是**导出当天的日期。

    用户的原话（2026-11-14）：「同一个数据，两天都有不同的保存，只要按原始
    文件的日期命名之后不改就行了」。同一批数据 11-13 导一次、11-14 再导一次，
    以前会变成 20261113阻抗作图 / 20261114阻抗作图 两份；现在两天的名字一样，
    就是同一个文件夹、同一个文件。

    取法从强到弱：
    1. 数据集名里带的 8 位日期（eis_20261107 → 20261107），摄取时就定了；
    2. 原始快照 / 源文件的最早修改日期；
    3. 数据集目录创建日期；
    4. 兜底今天（只在完全查不到来源时发生）。
    """
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", str(dataset or ""))
    if m:
        return "%s%s%s" % m.groups()

    stamps = []
    for d in (paths.sources_dir(dataset), paths.raw_dir(dataset)):
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                try:
                    stamps.append(os.path.getmtime(p))
                except OSError:
                    pass
    if not stamps:
        d = paths.dataset_dir(dataset)
        if os.path.isdir(d):
            try:
                stamps.append(os.path.getmtime(d))
            except OSError:
                pass
    if stamps:
        return datetime.fromtimestamp(min(stamps)).strftime("%Y%m%d")
    return datetime.now().strftime("%Y%m%d")


def default_base(dataset: str, spectrum: str = "eis",
                 suffix: str = "", at: datetime | None = None,
                 date: str = "") -> str:
    """<数据日期><类别>作图<序号>；日期取数据自身的，不取导出当天的。"""
    day = date or data_date(dataset)
    return sanitize_base("%s%s作图%s" % (day, category_of(dataset, spectrum), suffix))


def next_suffix(dataset: str, spectrum: str = "eis") -> str:
    """同一数据集第二张图起用 2、3… 后缀，避免导出件同名互相覆盖。"""
    used = set()
    for f in list_figures():
        try:
            s = load_spec(f["id"])
        except Exception:
            continue
        if s.get("data", {}).get("dataset") == dataset:
            used.add(str(s.get("export", {}).get("name_suffix", "")))
    if "" not in used:
        return ""
    n = 2
    while str(n) in used:
        n += 1
    return str(n)


def resolve_name(spec: dict, at: datetime | None = None) -> tuple[dict, bool]:
    """按**数据日期**定名，定完就冻住，隔天再打开/导出都不改。

    规则：
    - auto_name=False（用户自己改过名）→ 一个字都不碰；
    - auto_name=True → 第一次算出 ``export.name_date`` 并写入规格，之后
      永远复用它，只在类别/序号变了的时候重拼，日期不再跟今天跑。
    """
    ex = spec.setdefault("export", {})
    if not ex.get("auto_name"):
        return spec, False
    dataset = spec.get("data", {}).get("dataset", "")
    day = str(ex.get("name_date") or "").strip() or data_date(dataset)
    ex["name_date"] = day
    base = default_base(dataset,
                        spec.get("data", {}).get("spectrum", "eis"),
                        str(ex.get("name_suffix", "")), at, date=day)
    if base != ex.get("base"):
        ex["base"] = base
        return spec, True
    return spec, False


def load_preset(name: str) -> dict:
    if name not in PRESET_NAMES:
        raise ValueError("未知预设 %r；可用：%s" % (name, list(PRESET_NAMES)))
    with open(os.path.join(paths.PRESETS, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def series_for(curves: list[str], preset: dict) -> list[dict]:
    """按预设配色与封闭实心符号循环，自动分配末端单字母。"""
    pal = preset["palette"]
    cyc = preset["marker_cycle"]
    out = []
    for i, c in enumerate(curves):
        let = chr(ord("a") + i) if i < 26 else str(i)
        out.append({
            "curve": c,
            "letter": let,
            "name": "",                     # 显示名，空则用 curve
            "annot_text": let,              # 图上末端标注文字，可改成名字
            "color": pal[i % len(pal)],
            "marker": cyc[i % len(cyc)],
            "include": True,
            "annot_dx_pt": 7.0, "annot_dy_pt": 0.0,
            "annot_locked": False,          # 用户拖过位置后置 true，不再自动避让
            "off_x": 0.0, "off_y": 0.0,     # 整条曲线的显示平移（不改数据）
        })
    return out


def build_spec(fig_id: str, dataset: str, curves: list[str], preset: str = "inhouse",
               overrides: dict | None = None, note: str = "",
               tail_ohm: float = 60.0, fit_arc: bool = False,
               spectrum: str = "eis") -> dict:
    p = load_preset(preset)
    outdir = paths.out_dir(fig_id)
    suffix = next_suffix(dataset, spectrum)
    spec = {
        "id": fig_id,
        "preset": preset,
        "overrides": copy.deepcopy(overrides or {}),
        "note": note,
        "data": {
            "dataset": dataset,
            "working_csv": paths.portable(paths.working(dataset)),   # 相对项目根
            "x": "Zp_ohm", "y": "Zpp_neg_ohm",
            "only_included": True,
            "tail_ohm": tail_ohm,
            "fit_arc": fit_arc,
            "fit_disclaimer": ("参考圆拟合弧（fit），非实测数据；由首弧实测点最小二乘算出"
                               if fit_arc else ""),
        },
        "page": copy.deepcopy(p["page"]),
        "layer": copy.deepcopy(p["layer"]),
        "style": copy.deepcopy(p["style"]),
        "axis": copy.deepcopy(p["axis"]),
        "series": series_for(curves, p),
        "legend": copy.deepcopy(p["legend"]),
        "texts": [],                      # 自由文字对象，可拖可改
        "export": {
            "dir": paths.portable(outdir),   # 相对项目根，换机器也能用
            "base": default_base(dataset, spectrum, suffix),
            "name_suffix": suffix,
            "name_date": data_date(dataset),   # 数据日期，定名后不再改
            "auto_name": True,          # 名字按数据日期自动定，定完冻住
            "dpi": p["export"]["dpi"],
            "formats": list(p["export"]["formats"]),
        },
    }
    if overrides:
        spec = _deep_merge(spec, overrides)
        spec["overrides"] = copy.deepcopy(overrides)
        spec["preset"] = preset
    return spec


def save_spec(spec: dict, register: bool = True) -> str:
    """写规格文件。register=False 时只落文件、不往项目树里塞新窗口
    （出 PPT / 自动导出这类动作不该改变项目结构）。

    落盘前把项目内的路径改成相对写法：规格文件是要跟着项目一起搬家的，
    写死本机盘符的绝对路径，换台机器就全指错了。
    """
    data = spec.get("data")
    if isinstance(data, dict) and str(data.get("working_csv") or "").strip():
        data["working_csv"] = paths.portable(data["working_csv"])
    ex = spec.get("export")
    if isinstance(ex, dict) and str(ex.get("dir") or "").strip():
        ex["dir"] = paths.portable(ex["dir"])
    paths.ensure_dirs(paths.SPECS)
    p = paths.spec_file(spec["id"])
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
    if register:
        project.ensure(spec["id"], spec.get("preset", "inhouse"),
                       title=str(spec.get("export", {}).get("base", "") or spec["id"]))
    return p


def load_spec(fig_id: str) -> dict:
    with open(paths.spec_file(fig_id), encoding="utf-8") as fh:
        return json.load(fh)


def _register(fig_id: str, preset: str, add: bool):
    if add:
        project.ensure(fig_id, preset)
    else:
        project.drop(fig_id)
    return list_figures()


def remove_figure(fig_id: str):
    return _register(fig_id, "", add=False)


def list_figures() -> list[dict]:
    """页签列表；顺手剔掉规格文件已被删除的僵尸条目（自测图会留下这种）。"""
    data = project.load()
    alive = [f for f in data.get("figures", [])
             if os.path.isfile(paths.spec_file(f.get("id", "")))]
    if len(alive) != len(data.get("figures", [])):
        data["figures"] = alive
        project.save(data)
    return alive
