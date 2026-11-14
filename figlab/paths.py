# -*- coding: utf-8 -*-
"""唯一路径解析入口：所有跨层契约一律绝对路径。

对应「已知缺陷清单」第 2 条：导出目录若用相对路径，保存端与校验端会解析到
不同目录，结果判为失败并留下 0 字节文件。本模块是全部路径的唯一来源。
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ...\figlab
DATASETS = os.path.join(ROOT, "datasets")
SPECS = os.path.join(ROOT, "specs")
OUTPUTS = os.path.join(ROOT, "outputs")
TESTS = os.path.join(ROOT, "tests")
PRESETS = os.path.join(ROOT, "figlab", "spec", "presets")
FIGURES = os.path.join(ROOT, "figures.json")


def absolute(p: str) -> str:
    """把任意契约路径解析为绝对路径；空路径直接报错，不静默兜底。

    **相对路径一律按项目根（ROOT）解析**，所以规格里可以放心存
    ``datasets/eis_20261107/working.csv`` 这种相对写法：项目整个搬到别的盘、
    别人的电脑上克隆下来，都还能找到。
    """
    if not p:
        raise ValueError("路径为空：所有层间契约必须显式给出路径")
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(ROOT, p))


def portable(p: str) -> str:
    """写进规格文件前的路径规范：项目内的存相对，项目外的保持绝对。

    - 项目内（工作副本、中间导出目录）→ ``datasets/..../working.csv`` 这种相对路径，
      换台机器 clone、整个项目搬到别的盘也不会指错；
    - 项目外（桌面的成品文件夹、用户自己指定的 ppt 路径）→ 保留绝对路径，
      它们本来就不在项目里，相对化没有意义。
    """
    if not p:
        return p
    ap = os.path.normpath(p if os.path.isabs(p) else os.path.join(ROOT, p))
    try:
        rel = os.path.relpath(ap, ROOT)
    except ValueError:                      # Windows 跨盘符
        return ap
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return ap
    return rel.replace(os.sep, "/")


def display_source(p: str) -> str:
    """把「这份数据是从哪来的」写成能公开的短路径。

    元数据要跟着仓库给人看，不能写 ``C:\\Users\\<某人>\\Desktop\\...``：
    家目录下的写成 ``~/Desktop/...``，项目内的写成相对路径，其它保持原样。
    """
    if not p:
        return p
    ap = os.path.normpath(p if os.path.isabs(p) else os.path.join(ROOT, p))
    rel = portable(ap)
    if rel != ap or not os.path.isabs(ap):
        return rel
    home = os.path.expanduser("~")
    try:
        h = os.path.relpath(ap, home)
    except ValueError:
        return ap
    if h.startswith(os.pardir):
        return ap
    return "~/" + h.replace(os.sep, "/")


def dataset_dir(name: str) -> str:
    return os.path.join(DATASETS, name)


def raw_dir(name: str) -> str:
    return os.path.join(dataset_dir(name), "raw")


def sources_dir(name: str) -> str:
    return os.path.join(raw_dir(name), "sources")


def raw_long(name: str) -> str:
    return os.path.join(raw_dir(name), "raw_long.csv")


def raw_meta(name: str) -> str:
    return os.path.join(raw_dir(name), "raw_meta.json")


def working(name: str) -> str:
    return os.path.join(dataset_dir(name), "working.csv")


def ledger(name: str) -> str:
    return os.path.join(dataset_dir(name), "ledger.json")


def spec_file(fig_id: str) -> str:
    return os.path.join(SPECS, fig_id + ".json")


def out_dir(fig_id: str) -> str:
    return os.path.join(OUTPUTS, fig_id)


def ensure_dirs(*paths: str) -> None:
    for p in paths:
        os.makedirs(p, exist_ok=True)


# ---------------------------------------------------------------- 桌面归档（已停用）
# 2026-11-14 起不再按「日期 / 类别」往桌面归档：同一个数据的图隔天再导会被塞进
# 另一个日期目录，用户明确反对。现在成品统一走 handoff.py 的
# ``桌面\FigLab\<数据日期><类别>作图\``，名字定完就不改。
# 下面的函数只为读旧的 FigLab输出 内容而保留——旧目录已整体收进
# ``桌面\FigLab\_旧归档\``，结构没变，所以旧索引还能列出来。
ARCHIVE_NAME = "FigLab输出"
LEGACY_ARCHIVE = os.path.join("FigLab", "_旧归档")


def desktop() -> str:
    """找到真实桌面：优先 ~/Desktop，兼容 OneDrive 重定向与中文「桌面」。"""
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"),
                 os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(home, "桌面")):
        if os.path.isdir(cand):
            return cand
    return os.path.join(home, "Desktop")


def archive_root() -> str:
    r"""旧归档的实际位置：``桌面\FigLab\_旧归档``（按日期分级的老产物）。"""
    return os.path.join(desktop(), LEGACY_ARCHIVE)


def archive_dir(day: str, kind: str, sub: str = "") -> str:
    """day 形如 2026-11-13；kind 是「图片/数据/报告」。"""
    p = os.path.join(archive_root(), day, kind)
    return os.path.join(p, sub) if sub else p
