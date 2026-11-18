# -*- coding: utf-8 -*-
"""规格层校验：一张图的全部版式写成一份 JSON，一次报出**全部**结构性问题。

不画到一半才失败（规范 §三.2）。所有检查都跑完再返回，不中途抛异常。
"""
from __future__ import annotations

import csv
import math
import os
import re

from .. import paths

PRESET_NAMES = ("inhouse", "generic", "dark_outline")
FILLED_MARKERS = {"circle", "square", "triangle_up", "triangle_down"}
# 明确的线符号 / 开口符号黑名单（规范 §三.5 / §八.4）
FORBIDDEN_MARKERS = {"x", "X", "cross", "plus", "+", "star", "*", "diamond",
                     "pentagon", "hexagon", "hline", "vline", "none", "",
                     "open_circle", "open_square", "open_triangle"}
FORMATS = {"pdf", "eps", "svg", "png"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

TOP_KEYS = ("id", "preset", "data", "page", "layer", "style", "axis",
            "series", "legend", "export")
LAYER_KEYS = ("left", "top", "width", "height")


def available_curves(spec: dict) -> set[str]:
    p = spec.get("data", {}).get("working_csv", "")
    p = paths.absolute(p) if str(p or "").strip() else ""
    if not p or not os.path.isfile(p):
        return set()
    with open(p, "r", encoding="utf-8-sig", newline="") as fh:
        return {r["curve"] for r in csv.DictReader(fh) if r.get("curve")}


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def validate(spec: dict, curves: set[str] | None = None) -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    checks = 0

    def ck(cond: bool, msg: str):
        nonlocal checks
        checks += 1
        if not cond:
            problems.append(msg)

    # ---- 顶层结构
    for k in TOP_KEYS:
        ck(k in spec, "缺少顶层字段：%s" % k)
    if any(k not in spec for k in TOP_KEYS):
        # 继续把能查的都查完，不提前返回
        pass
    fid = str(spec.get("id", ""))
    ck(bool(fid) and not re.search(r'[\\/:*?"<>|]', fid), "id 为空或含非法文件名字符")
    ck(spec.get("preset") in PRESET_NAMES,
       "preset 必须是 %s，实际 %r" % (list(PRESET_NAMES), spec.get("preset")))

    # ---- 数据契约
    data = spec.get("data", {}) or {}
    for k in ("working_csv", "x", "y", "only_included"):
        ck(k in data, "data 缺少字段：%s" % k)
    wcsv = str(data.get("working_csv", ""))
    ck(bool(wcsv.strip()), "data.working_csv 不能为空")
    # 相对路径按项目根解析（规格里默认存相对写法，换机器/换目录也能用）
    ck(os.path.isfile(paths.absolute(wcsv)) if wcsv.strip() else False,
       "data.working_csv 不存在（相对路径按项目根解析）：%s" % wcsv)
    ck(isinstance(data.get("only_included"), bool), "data.only_included 必须是布尔")
    if "break_before_point" in data:
        breaks = data["break_before_point"]
        ck(data.get("spectrum") == "fscv" and isinstance(breaks, list)
           and all(type(index) is int and index > 1 for index in breaks),
           "break_before_point 必须是 FSCV 断线处的点序列表")
    tail = data.get("tail_ohm", 0)
    ck(_num(tail) is not None and float(tail or 0) >= 0,
       "data.tail_ohm 必须是 >=0 的数值（固定欧姆数截尾，禁止固定比例）")
    ck(isinstance(data.get("fit_arc", False), bool), "data.fit_arc 必须是布尔")
    if data.get("fit_arc"):
        ck(bool(str(data.get("fit_disclaimer", "")).strip()),
           "开启圆拟合必须写 fit_disclaimer，声明为拟合而非实测（规范 §二.4）")
    fit_window = data.get("ms_shared_window_V")
    if fit_window is not None:
        ck(data.get("spectrum") == "mott_schottky" and data.get("fit_linear") is True
           and isinstance(fit_window, list) and len(fit_window) == 2
           and all(_num(v) is not None for v in fit_window)
           and float(fit_window[0]) < float(fit_window[1]),
           "ms_shared_window_V 必须是 Mott–Schottky 拟合的起止电位")

    # ---- 画布与图层
    page = spec.get("page", {}) or {}
    for k in ("w_cm", "h_cm"):
        v = _num(page.get(k))
        ck(v is not None and v > 0, "page.%s 必须是正数" % k)
    layer = spec.get("layer", {}) or {}
    lv = {}
    for k in LAYER_KEYS:
        v = _num(layer.get(k))
        lv[k] = v
        ck(v is not None and v > 0, "layer.%s 必须是正数（页面百分比）" % k)
    if all(v is not None for v in lv.values()):
        ck(lv["left"] + lv["width"] <= 100 + 1e-9,
           "layer.left + layer.width = %.2f > 100，图框越出右边界" % (lv["left"] + lv["width"]))
        ck(lv["top"] + lv["height"] <= 100 + 1e-9,
           "layer.top + layer.height = %.2f > 100，图框越出下边界" % (lv["top"] + lv["height"]))

    # ---- 样式（默认预设口径，规范 §三.4）
    st = spec.get("style", {}) or {}
    for k in ("font", "tick_pt", "title_pt", "spines", "tick_dir", "grid",
              "equal_aspect", "fill_frame", "line_width_pt", "marker_size_pt"):
        ck(k in st, "style 缺少字段：%s" % k)
    ck(bool(str(st.get("font", "")).strip()), "style.font 不能为空")
    for k in ("tick_pt", "title_pt", "marker_size_pt"):
        v = _num(st.get(k))
        ck(v is not None and v > 0, "style.%s 必须是正数" % k)
    v = _num(st.get("line_width_pt"))
    ck(v is not None and v >= 0, "style.line_width_pt 必须 >= 0")
    open_axes = st.get("spines") == "left_bottom"
    ck(st.get("spines") == "all" or open_axes, "坐标轴可选四边框或左下轴")
    ck(st.get("tick_dir") in ("in", "out"), "刻度方向须为 in 或 out")
    ck(st.get("grid") is False, "默认无网格（grid=false）")
    ck(isinstance(st.get("ms_frequency_key", False), bool), "ms_frequency_key 必须是布尔")
    ck(st.get("axis_title_weight", "normal") in ("normal", "bold"),
       "axis_title_weight 必须是 normal 或 bold")
    # 剔除处断线：缺省视为开启（老规格没有这个键也要能用）
    ck(isinstance(st.get("break_gaps", True), bool),
       "style.break_gaps 必须是 true/false")
    # 连线画法：散点 / 折线 / 平滑；老规格缺键按"折线"（即原来的画法）
    ck(st.get("connect", "segment") in ("scatter", "segment", "smooth"),
       "style.connect 只能是 scatter / segment / smooth（收到 %r）" % st.get("connect"))
    ck(not (st.get("equal_aspect") is True and st.get("fill_frame") is True),
       "两轴严格等比与铺满图框互斥，必须关闭其一（规范 §三.7）")
    if st.get("equal_aspect") is True:
        warnings.append("等比开启：纵轴跨度将被抬到横轴的 3/4，图框上半可能空出（规范 §三.7）")

    # ---- 坐标轴
    ax = spec.get("axis", {}) or {}
    for k in ("x_title", "y_title"):
        ck(bool(str(ax.get(k, "")).strip()), "axis.%s 不能为空" % k)
    ck(ax.get("zero_origin", False) is False,
       "不得固定从零起（axis.zero_origin 必须为 false，规范 §四.2）")
    for axis in ("x", "y"):
        lo, hi, inc = (_num(ax.get(axis + "_from")), _num(ax.get(axis + "_to")),
                       _num(ax.get(axis + "_inc")))
        if lo is not None and hi is not None:
            ck(hi > lo, "axis.%s_to 必须大于 %s_from" % (axis, axis))
        if inc is not None:
            ck(inc > 0, "axis.%s_inc 必须 > 0" % axis)
        if lo is not None and ax.get("auto_from_data") is True:
            warnings.append("axis.%s_from 已显式指定，auto_from_data 将不生效" % axis)
    ck(isinstance(ax.get("auto_from_data", True), bool), "axis.auto_from_data 必须是布尔")
    padv = _num(ax.get("pad_frac", 0.05))
    ck(padv is not None and 0 <= padv <= 0.2, "axis.pad_frac 应在 0~0.2")

    # ---- 曲线
    series = spec.get("series", []) or []
    ck(len(series) > 0, "series 为空：至少要有一条曲线")
    if curves is None:
        curves = available_curves(spec)
    letters, markers = [], []
    for i, s in enumerate(series):
        ck(isinstance(s.get("reference", False), bool), "曲线 reference 必须是布尔值")
        for k in ("curve", "letter", "color", "marker", "include"):
            ck(k in s, "series[%d] 缺少字段：%s" % (i, k))
        c = str(s.get("curve", ""))
        ck(bool(c), "series[%d].curve 为空" % i)
        if curves:
            ck(c in curves, "series[%d].curve=%r 不在工作副本的曲线列表中" % (i, c))
        col = str(s.get("color", ""))
        ck(bool(HEX.match(col)), "series[%d].color 必须是 #RRGGBB：%r" % (i, col))
        let = str(s.get("letter", ""))
        ck(bool(re.fullmatch(r"[A-Za-z]", let)),
           "series[%d].letter 必须是单个字母：%r" % (i, let))
        letters.append(let)
        mk = str(s.get("marker", ""))
        markers.append(mk)
        ck(mk in FILLED_MARKERS,
           "series[%d].marker=%r 不是封闭实心形；只允许 %s"
           % (i, mk, sorted(FILLED_MARKERS)))
        ck(mk not in FORBIDDEN_MARKERS,
           "series[%d].marker=%r 是线符号/开口符号，禁止使用（规范 §三.5 / §八.4）" % (i, mk))
        ck(isinstance(s.get("include"), bool), "series[%d].include 必须是布尔" % i)
        # 图上末端标注：文字可改名、位置可拖（拖过就锁定，不再自动避让）
        txtv = s.get("annot_text", let)
        ck(isinstance(txtv, str) and 1 <= len(txtv.strip()) <= 12,
           "series[%d].annot_text 必须是 1~12 个字符的字符串：%r" % (i, txtv))
        if "annot_locked" in s:
            ck(isinstance(s.get("annot_locked"), bool),
               "series[%d].annot_locked 必须是布尔" % i)
        for k in ("annot_dx_pt", "annot_dy_pt"):
            if k in s:
                ck(_num(s.get(k)) is not None, "series[%d].%s 必须是数值" % (i, k))
        # 整条曲线的显示平移（数据坐标单位的位移；只影响显示，不改工作副本）
        for k in ("off_x", "off_y"):
            if k in s:
                v = _num(s.get(k))
                ck(v is not None and abs(v) <= 1e9,
                   "series[%d].%s 必须是有限数值" % (i, k))
        if "name" in s:
            ck(isinstance(s.get("name"), str), "series[%d].name 必须是字符串" % i)
    ck(len(letters) == len(set(letters)), "曲线末端字母重复：%s" % letters)
    ck(len(set(markers)) >= 1, "未指定任何符号")
    if len(series) > 6:
        warnings.append("曲线数 %d > 6：配色可能重复，缩印后可分辨性下降" % len(series))
    if "fscv_peak_table_curve" in st:
        boundary = data.get("break_before_point")
        ck(data.get("spectrum") == "fscv" and isinstance(boundary, list) and len(boundary) == 1
           and isinstance(st["fscv_peak_table_curve"], str)
           and any(s.get("curve") == st["fscv_peak_table_curve"] for s in series),
           "FSCV 峰值表需要指定曲线和一个正扫/回扫分界点")
    if data.get("spectrum") == "fscv" and "loc" in spec.get("legend", {}):
        ck(spec["legend"]["loc"] in ("upper left", "upper right"),
           "FSCV 图例位置必须是 upper left 或 upper right")
    if spec.get("legend", {}).get("show") is not False:
        ck(False, "默认不用图例框，曲线身份用末端同色单字母（规范 §三.6）")

    # ---- 自由文字（图上可拖可改的图层对象；位置按画布归一化坐标 0~1）
    texts = spec.get("texts", [])
    ck(isinstance(texts, list), "texts 必须是列表")
    if isinstance(texts, list):
        for i, t in enumerate(texts):
            ck(isinstance(t, dict), "texts[%d] 必须是对象" % i)
            if not isinstance(t, dict):
                continue
            ck(bool(str(t.get("text", "")).strip()), "texts[%d].text 不能为空" % i)
            ck(t.get("font_weight", "normal") in ("normal", "bold"),
               "texts[%d].font_weight 必须是 normal 或 bold" % i)
            for k in ("nx", "ny"):
                v = _num(t.get(k))
                ck(v is not None and -0.05 <= v <= 1.05,
                   "texts[%d].%s 必须是 0~1 的画布归一化坐标" % (i, k))
            if "size_pt" in t:
                v = _num(t.get("size_pt"))
                ck(v is not None and 0 < v <= 72, "texts[%d].size_pt 必须在 0~72" % i)
            if "color" in t:
                ck(bool(HEX.match(str(t.get("color")))),
                   "texts[%d].color 必须是 #RRGGBB" % i)

    # ---- 导出（规格里存相对项目根的写法；渲染/校验前统一解析为绝对路径）
    ex = spec.get("export", {}) or {}
    d = str(ex.get("dir", ""))
    ck(bool(d.strip()), "export.dir 不能为空")
    ck(bool(str(ex.get("base", "")).strip()), "export.base 不能为空")
    ck(not re.search(r'[\\/:*?"<>|]', str(ex.get("base", ""))),
       "export.base 不能含 Windows 文件名字符：%r" % ex.get("base"))
    if "auto_name" in ex:
        ck(isinstance(ex.get("auto_name"), bool), "export.auto_name 必须是布尔")
    fmts = ex.get("formats", []) or []
    ck(bool(fmts), "export.formats 为空")
    for f in fmts:
        ck(str(f).lower() in FORMATS, "不支持的导出格式：%r" % f)
    ck("pdf" in [str(f).lower() for f in fmts], "必须导出 PDF（投稿级矢量）")
    ck(_num(ex.get("dpi")) == 600, "export.dpi 必须为 600；位图仅作预览不得用于投稿")

    return {"ok": len(problems) == 0, "checks": checks,
            "problems": problems, "warnings": warnings,
            "problem_count": len(problems), "warning_count": len(warnings)}
