# -*- coding: utf-8 -*-
"""渲染层：输入工作副本与规格，输出投稿级矢量图。

字体类型只能在全局 rcParams 里设（matplotlib 3.11 起 savefig(pdf={...})
会抛 TypeError，缺陷清单第 1 条）；SVG 保留真文字不转轮廓；PNG 仅 600 dpi
预览，不作投稿件。导出目录一律绝对路径（缺陷清单第 2 条）。

额外输出两项（规范 §四.1）：
  points.json  每个数据点在画布上的归一化坐标，供前端铺点击热区
  实际生效的坐标范围，供缩放与平移
"""
from __future__ import annotations

import bisect
import io
import math
from collections import defaultdict

from .curve import CONNECT_MODES, smooth_path
from .. import paths

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                     # noqa: E402
import numpy as np                                  # noqa: E402
from matplotlib import rcParams                     # noqa: E402
from matplotlib.colors import to_hex, to_rgb         # noqa: E402
from matplotlib.lines import Line2D                  # noqa: E402
from matplotlib.ticker import AutoMinorLocator, FormatStrFormatter, FuncFormatter, MultipleLocator  # noqa: E402

from ..data.dataset import read_long                # noqa: E402
from ..process import get_processor                 # noqa: E402
from ..spec.schema import validate                 # noqa: E402
from .mapping import (annotation_rect_data, nice_limits,  # noqa: E402
                      normalize_points)

MARKER_MAP = {
    "circle": "o", "square": "s",
    "triangle_up": "^", "triangle_down": "v",
}
CANDIDATE_OFFSETS = [
    (8, 0), (8, 6), (8, -8), (0, 9), (0, -11),
    (14, 0), (14, 7), (14, -8), (-15, 0), (-15, 7), (-15, -8),
    (0, 15), (0, -17), (22, 0), (-22, 0), (22, 10), (22, -10),
]
FIT_DISCLAIMER_EN = "Dashed arc: circle fit (reference, not measured)"


def _gap_between(zs: list[float], a: float, b: float) -> bool:
    """a、b 两点之间（不含端点）是否夹着被排除点的实部。"""
    lo, hi = (a, b) if a <= b else (b, a)
    i = bisect.bisect_right(zs, lo + 1e-12)
    return i < len(zs) and zs[i] < hi - 1e-12


def split_runs(points: list, excl_z: list[float]) -> list[list]:
    """按被排除点的位置把曲线切成若干段。

    框选剔除中段之后，如果仍然把两侧端点用直线连起来，图上就出现了一段
    「从未测过」的连线——这是核验最忌讳的假数据。所以断点处必须断开：
    有几个连续段就画几条线，标记点仍然是全部参与点。
    """
    if not excl_z or len(points) < 2:
        return [points]
    runs, cur = [], [points[0]]
    for p in points[1:]:
        if _gap_between(excl_z, cur[-1][0], p[0]):
            runs.append(cur)
            cur = [p]
        else:
            cur.append(p)
    runs.append(cur)
    return [r for r in runs if r]


def setup_rc(style: dict) -> list[str]:
    """全局字体嵌入设置；matplotlib 3.11 不再接受 savefig(pdf={...})。

    返回字体族列表（含 CJK 回退），供图上文字统一使用——只传单个字体名会让
    中文变成空框。
    """
    rcParams["pdf.fonttype"] = 42            # TrueType 子集，禁止 Type3
    rcParams["ps.fonttype"] = 42
    rcParams["svg.fonttype"] = "none"        # SVG 保留真文字，不转轮廓
    rcParams["pdf.compression"] = 6
    font = style["font"]
    # 中文字注：Times New Roman 没有汉字字形，必须给一条 CJK 回退链，
    # 否则图上中文会变成空框（matplotlib 只告警、不报错，很容易漏掉）。
    cjk = ["Microsoft YaHei", "SimSun", "SimHei"]
    fams = [font] + cjk + ["DejaVu Serif" if "times" in font.lower() else "DejaVu Sans"]
    if "times" in font.lower():
        rcParams["font.family"] = "serif"
        rcParams["font.serif"] = fams
    else:
        rcParams["font.family"] = "sans-serif"
        rcParams["font.sans-serif"] = fams
    rcParams["font.size"] = style["tick_pt"]
    rcParams["axes.linewidth"] = style.get("frame_line_width_pt", 0.6)
    rcParams["mathtext.fontset"] = "stix"
    return fams


def _place_annotations(ax, plotted, limits, base_pt, fonts, dpi, spec, series_by):
    """末端标注；用数据点坐标去撞标注矩形（§八.6），不数像素。

    规范默认是「自动避让」，但用户要求能像 Origin 一样直接拖标注、改名字：
    series.annot_locked 为 true 时按用户给的点偏移放置，不再自动重排，
    否则每拖一次就被自动避让弹回去。
    """
    page, layer = spec["page"], spec["layer"]
    w_cm, h_cm = page["w_cm"], page["h_cm"]
    left, top = layer["left"] / 100.0, layer["top"] / 100.0
    wf, hf = layer["width"] / 100.0, layer["height"] / 100.0
    all_pts = [(x, y) for pd in plotted for x, y, _ in pd["points"]]
    lx0, lx1 = limits["x"][:2]
    ly0, ly1 = limits["y"][:2]

    def clamp_inside(x, y, dx, dy, fs):
        """标注框越出图框就往里推——核验会判「越框」，不能放着不管。"""
        rect = annotation_rect_data(ax, x, y, dx, dy, fs, dpi)
        inside = (rect[0] >= lx0 and rect[2] <= lx1
                  and rect[1] >= ly0 and rect[3] <= ly1)
        for _ in range(3):
            if inside:
                break
            p0 = ax.transData.transform((rect[0], rect[1]))
            p1 = ax.transData.transform((rect[2], rect[3]))
            bb = ax.bbox
            ddx = ddy = 0.0
            if p0[0] < bb.x0:
                ddx = (bb.x0 - p0[0]) * 72.0 / dpi
            elif p1[0] > bb.x1:
                ddx = (bb.x1 - p1[0]) * 72.0 / dpi
            if p0[1] < bb.y0:
                ddy = (bb.y0 - p0[1]) * 72.0 / dpi
            elif p1[1] > bb.y1:
                ddy = (bb.y1 - p1[1]) * 72.0 / dpi
            if not ddx and not ddy:
                break
            dx, dy = dx + ddx, dy + ddy
            rect = annotation_rect_data(ax, x, y, dx, dy, fs, dpi)
            inside = (rect[0] >= lx0 and rect[2] <= lx1
                      and rect[1] >= ly0 and rect[3] <= ly1)
        return dx, dy, rect, inside

    results = []
    for pd in plotted:
        s = series_by.get(pd["curve"], {})
        x, y, _ = pd["points"][-1]
        fs = max(base_pt - 1.0, 6.0)
        text = str(s.get("annot_text") or pd["letter"])
        locked = bool(s.get("annot_locked"))
        pnx = left + (x - lx0) / (lx1 - lx0) * wf
        pny = top + (1.0 - (y - ly0) / (ly1 - ly0)) * hf
        # 曲线被拖到图框外时不再画标注：一个贴边的字母会被误读成端点还在那里
        if not (lx0 <= x <= lx1 and ly0 <= y <= ly1):
            results.append({"curve": pd["curve"], "letter": pd["letter"], "text": text,
                            "dx_pt": 0.0, "dy_pt": 0.0, "rect_data": [x, y, x, y],
                            "locked": locked, "collides_with_points": 0,
                            "inside_frame": True, "hidden": True,
                            "point_nx": round(pnx, 6), "point_ny": round(pny, 6),
                            "nx": round(pnx, 6), "ny": round(pny, 6)})
            continue
        if locked:
            dx = float(s.get("annot_dx_pt", 7.0))
            dy = float(s.get("annot_dy_pt", 0.0))
            dx, dy, rect, inside = clamp_inside(x, y, dx, dy, fs)
            x0, y0, x1, y1 = rect
            hits = sum(1 for px, py in all_pts if x0 <= px <= x1 and y0 <= py <= y1)
        else:
            chosen = None
            for cdx, cdy in CANDIDATE_OFFSETS:
                rect = annotation_rect_data(ax, x, y, cdx, cdy, fs, dpi)
                x0, y0, x1, y1 = rect
                tol_x, tol_y = (x1 - x0) * 0.12, (y1 - y0) * 0.12
                chits = sum(1 for px, py in all_pts
                            if x0 - tol_x <= px <= x1 + tol_x
                            and y0 - tol_y <= py <= y1 + tol_y)
                cinside = (x0 >= lx0 and x1 <= lx1 and y0 >= ly0 and y1 <= ly1)
                if chits == 0 and cinside:
                    chosen = (cdx, cdy, rect, chits, cinside)
                    break
            if chosen is None:
                cdx, cdy = CANDIDATE_OFFSETS[0]
                dx, dy, rect, inside = clamp_inside(x, y, cdx, cdy, fs)
                x0, y0, x1, y1 = rect
                hits = sum(1 for px, py in all_pts if x0 <= px <= x1 and y0 <= py <= y1)
            else:
                dx, dy, rect, hits, inside = chosen
        ax.annotate(text, xy=(x, y), xytext=(dx, dy),
                    textcoords="offset points", ha="left", va="bottom",
                    color=pd["color"], fontsize=fs, fontname=fonts,
                    annotation_clip=False, zorder=5)
        results.append({"curve": pd["curve"], "letter": pd["letter"], "text": text,
                        "dx_pt": dx, "dy_pt": dy, "rect_data": rect,
                        "locked": locked, "hidden": False,
                        "collides_with_points": hits, "inside_frame": inside,
                        "point_nx": round(pnx, 6), "point_ny": round(pny, 6),
                        # 标注锚点（左下角）在整张画布上的归一化坐标，供前端铺拖拽热区
                        "nx": round(pnx + dx / 72.0 / (w_cm / 2.54), 6),
                        "ny": round(pny - dy / 72.0 / (h_cm / 2.54), 6)})
    return results


def _draw_texts(fig, spec, fonts):
    """自由文字对象：位置按整张画布归一化坐标（0~1，y 从上往下）。"""
    out = []
    for i, t in enumerate(spec.get("texts") or []):
        nx, ny = float(t["nx"]), float(t["ny"])
        size = float(t.get("size_pt", spec["style"]["tick_pt"]))
        color = str(t.get("color", "#000000"))
        fig.text(nx, 1.0 - ny, str(t["text"]), fontsize=size, color=color,
                 fontname=fonts, fontweight=t.get("font_weight", "normal"),
                 ha=str(t.get("ha", "left")),
                 va=str(t.get("va", "bottom")), zorder=6)
        out.append({"id": str(t.get("id") or "t%d" % (i + 1)),
                    "text": str(t["text"]), "nx": nx, "ny": ny,
                    "size_pt": size, "color": color,
                    "ha": str(t.get("ha", "left"))})
    return out


def _draw_fscv_peak_table(ax, plotted, sweep_boundary, table_curve, names, fonts):
    for curve in plotted:
        points = curve["points"]
        forward = (point for point in points if float(point[2]["point_index"]) < sweep_boundary)
        reverse = (point for point in points if float(point[2]["point_index"]) >= sweep_boundary)
        oxidation = max(forward, key=lambda point: point[1], default=None)
        reduction = min(reverse, key=lambda point: point[1], default=None)
        peaks = [point for point in (oxidation, reduction) if point is not None]
        ax.plot([point[0] for point in peaks], [point[1] for point in peaks], linestyle="none",
                marker="o", markersize=3.2, markerfacecolor="white", markeredgecolor=curve["color"],
                markeredgewidth=.9, zorder=5)
        if curve["curve"] != table_curve or len(peaks) != 2:
            continue

        rows = []
        for label, (_, _, point) in zip(("Ox.", "Red."), peaks):
            potential = format(float(point["potential_V"]), "+.3f").replace("-", "−")
            current = format(float(point["current_nA"]), "+.2f").replace("-", "−")
            rows.append([label, potential, current])
        ax.text(.56, .31, names[table_curve], transform=ax.transAxes, va="bottom",
                fontsize=6.7, fontfamily=fonts, color="#35404A")
        table = ax.table(cellText=rows, colLabels=["Peak", "V", "nA"], cellLoc="right",
                         colLoc="right", colWidths=[.31, .31, .38], bbox=[.55, .045, .43, .245])
        table.auto_set_font_size(False)
        table.set_fontsize(6.7)
        for (row, column), cell in table.get_celld().items():
            cell.set_edgecolor("#B9C2CB")
            cell.set_linewidth(.45)
            cell.visible_edges = "B" if row == 0 else ""
            cell.get_text().set_color("#35404A")
            cell.get_text().set_fontfamily(fonts)
            if column == 0:
                cell.get_text().set_ha("left")


def prepare(spec: dict, target_ticks: int = 8, lock_axis: bool = False) -> dict:
    """lock_axis=True 时坐标范围只按**未平移**的实测点算。

    拖曲线时要用它：否则轴范围随平移一起跳（nice_limits 归整到整刻度，会一下
    跳 10~30 Ω），看起来就像「线不跟手」。松手后再按含平移的范围重算一次，
    只跳这一下，且保证曲线不会被切在图外。
    """
    v = validate(spec)
    if not v["ok"]:
        raise ValueError("规格校验未通过（一次报出全部问题）：\n  - " +
                         "\n  - ".join(v["problems"]))

    st, page, layer, axs = spec["style"], spec["page"], spec["layer"], spec["axis"]
    data = spec["data"]
    spectrum = data.get("spectrum", "eis")
    fonts = setup_rc(st)          # 含 CJK 回退的字体族列表
    font = st["font"]

    rows = read_long(paths.absolute(data["working_csv"]), spectrum)
    only_inc = data.get("only_included", True)
    groups = defaultdict(list)        # 曲线 → [(行, 是否参与)]，保持文件原序
    for r in rows:
        inc = (not only_inc) or str(r.get("include", "1")) == "1"
        groups[r["curve"]].append((r, inc))

    proc = get_processor(spectrum)
    is_ms = spectrum == "mott_schottky"
    is_fscv = spectrum == "fscv"
    open_axes = st["spines"] == "left_bottom"
    is_uvvis = spectrum == "uvvis"
    is_tauc = is_uvvis and data.get("view") == "tauc_preview"
    if is_ms:
        from ..process.mott_schottky import (
            common_window, inverse_capacitance_squared, shared_intercept_window,
        )

        def coordinates(row):
            return float(row["potential_V"]), inverse_capacitance_squared(row)
    elif is_uvvis:
        if is_tauc:
            from ..process.uvvis import tauc_coordinates as coordinates
        else:
            def coordinates(row):
                return float(row["wavelength_nm"]), float(row["absorbance"])
    elif is_fscv:
        def coordinates(row):
            return float(row["potential_V"]), float(row["current_nA"])
    else:
        def coordinates(row):
            return float(row["Zp_ohm"]), -float(row["Zpp_ohm"])
    break_gaps = bool(st.get("break_gaps", True))
    # 连线画法：scatter 只画符号 / segment 直连（默认）/ smooth 过点平滑插值
    connect = str(st.get("connect") or "segment")
    if connect not in CONNECT_MODES:
        raise ValueError("style.connect 只能是 %s，收到 %r" %
                         ("/".join(CONNECT_MODES), connect))
    plotted, geoms = [], {}
    for s in spec["series"]:
        if not s["include"]:
            continue
        c = s["curve"]
        pairs = groups.get(c)
        if not pairs:
            continue
        rs = [r for r, inc in pairs if inc and (not is_tauc or float(r["absorbance"]) >= 0)]
        if not rs:
            continue
        g = proc.geometry(rs)
        kept = proc.truncate(rs, g, data.get("tail_ohm", 0) or 0)
        if not kept:
            continue
        # 整条曲线的显示平移：Origin 里拖曲线看的是相对位置，数据本身不动。
        # 偏移只写在规格里（series.off_x / off_y），不写台账、不改工作副本，
        # 台账里也就不会出现一堆「曲线整体平移」这种假改动。
        ox = float(s.get("off_x") or 0.0)
        oy = float(s.get("off_y") or 0.0)
        pts = [(x + ox, y + oy, r) for r in kept for x, y in [coordinates(r)]]
        # 被排除（框选删掉）的点在 Z' 轴上的位置：夹在两点之间就说明这里断开了
        if is_fscv:
            breaks = sorted(data.get("break_before_point", []))
            excluded = sorted(float(r["point_index"]) for r, inc in pairs if not inc)
            runs = []
            previous = None
            for point in pts:
                index = float(point[2]["point_index"])
                if (previous is None or bisect.bisect_right(breaks, previous) < bisect.bisect_right(breaks, index)
                        or (break_gaps and bisect.bisect_right(excluded, previous) < bisect.bisect_left(excluded, index))):
                    runs.append([])
                runs[-1].append(point)
                previous = index
        elif is_uvvis:
            excl_z = sorted(coordinates(r)[0] + ox for r, inc in pairs
                            if not inc or (is_tauc and float(r["absorbance"]) < 0))
        elif is_ms:
            excl_z = sorted(float(r["potential_V"]) + ox for r, inc in pairs
                            if not inc or float(r["Zpp_ohm"]) >= 0)
        else:
            excl_z = sorted(float(r["Zp_ohm"]) + ox for r, inc in pairs if not inc)
        if not is_fscv:
            runs = split_runs(pts, excl_z) if break_gaps else [pts]
        reference = s.get("reference", False)
        color = to_hex(0.58 * np.array(to_rgb(s["color"])) + 0.42) if reference else s["color"]
        plotted.append({"curve": c, "letter": s["letter"], "color": color, "reference": reference,
                        "marker": s["marker"], "points": pts, "runs": runs,
                        "off_x": ox, "off_y": oy,
                        "geometry": g, "n_plotted": len(pts),
                        "n_runs": len(runs)})
        geoms[c] = {"geometry": g, "n_plotted": len(pts),
                    "tail_ohm": data.get("tail_ohm", 0),
                    "n_segments": len(runs)}
    if not plotted:
        raise ValueError("没有任何可绘制的点（检查 include 标记与 series 配置）")

    all_x = [x for pd in plotted for x, _, _ in pd["points"]]
    all_y = [y for pd in plotted for _, y, _ in pd["points"]]
    # 轴范围用的点：默认含平移；拖动过程中（lock_axis）只用实测值，避免轴跟着跳
    raw_x = [x - pd["off_x"] for pd in plotted for x, _, _ in pd["points"]]
    raw_y = [y - pd["off_y"] for pd in plotted for _, y, _ in pd["points"]]
    lim_x = raw_x if lock_axis else all_x
    lim_y = raw_y if lock_axis else all_y
    fit_info = {}
    shared_window = data.get("ms_shared_window_V") if is_ms else None
    frequency_key = is_ms and st.get("ms_frequency_key", False)
    focus_fit = is_ms and st.get("ms_focus_fit", False)
    if is_ms and data.get("fit_linear"):
        fit_rows = {pd["curve"]: [r for r, inc in groups[pd["curve"]] if inc]
                    for pd in plotted}
        fit_info = (shared_intercept_window(fit_rows, shared_window)
                    if shared_window is not None else common_window(fit_rows))
        if data.get("show_fit_intercepts") and fit_info:
            lim_x = lim_x + [fit_info[pd["curve"]]["zero_V"] + (0 if lock_axis else pd["off_x"])
                             for pd in plotted if pd["curve"] in fit_info]
            lim_y = lim_y + [0 if lock_axis else pd["off_y"]
                             for pd in plotted if pd["curve"] in fit_info]
    pad = float(axs.get("pad_frac", 0.05))
    if axs.get("auto_from_data", True):
        lx0, lx1, lxi = nice_limits(lim_x, pad, target_ticks)
        ly0, ly1, lyi = nice_limits(lim_y, pad, target_ticks)
    else:
        lx0, lx1 = float(axs["x_from"]), float(axs["x_to"])
        ly0, ly1 = float(axs["y_from"]), float(axs["y_to"])
        lxi = float(axs["x_inc"] or 10)
        lyi = float(axs["y_inc"] or 10)
    # §三.7：等比开启时纵轴跨度被抬到横轴的 3/4，图框上半必然空出一片。
    # 调整必须发生在 limits 构造之前：points.json 的 effective_range 直接取 limits，
    # 图上拖点也按它反算；若与 ax 实际范围不一致，热区会整体偏掉。
    if st.get("equal_aspect"):
        need = (lx1 - lx0) * (layer["height"] / layer["width"])
        if need > ly1 - ly0:
            mid = (ly0 + ly1) / 2
            ly0, ly1 = mid - need / 2, mid + need / 2
    limits = {"x": [lx0, lx1, lxi], "y": [ly0, ly1, lyi],
              "x_inc": lxi, "y_inc": lyi}

    w, h = page["w_cm"], page["h_cm"]
    dpi = 600
    fig = plt.figure(figsize=(w / 2.54, h / 2.54), dpi=dpi)
    bottom = 1.0 - (layer["top"] + layer["height"]) / 100.0
    ax = fig.add_axes([layer["left"] / 100.0, bottom,
                       layer["width"] / 100.0, layer["height"] / 100.0])

    # 可选参考圆拟合：只作虚线叠加，明确声明为拟合而非实测（§二.4 / §八.7）
    if is_ms and data.get("fit_linear"):
        for pd in plotted:
            f = fit_info.get(pd["curve"])
            if f:
                x = np.array([f["x_from"], f["x_to"]])
                origin = f["zero_V"] if shared_window is not None else 0
                offset = 0 if shared_window is not None else f["intercept"]
                ax.plot(x + pd["off_x"], f["slope"] * (x - origin) + offset + pd["off_y"],
                        "--", linewidth=max(1.2, st["line_width_pt"]) if focus_fit else 0.85,
                        color=pd["color"], zorder=2)
                if data.get("show_fit_intercepts"):
                    x = np.array([f["zero_V"], f["x_from"]])
                    ax.plot(x + pd["off_x"], f["slope"] * (x - origin) + offset + pd["off_y"],
                            linestyle=":" if not focus_fit else "-",
                            linewidth=max(1.15, st["line_width_pt"]) if focus_fit else 0.9,
                            color=pd["color"], zorder=1.5)
        if fit_info and data.get("show_fit_intercepts"):
            ax.axhline(0, color="#777777", linewidth=0.45, zorder=0)
    elif data.get("fit_arc"):
        for pd in plotted:
            f = proc.fit([r for _, _, r in pd["points"]], pd["geometry"])
            fit_info[pd["curve"]] = f
            if f:
                cx, cy, R = f["center_Zp_ohm"], f["center_y_ohm"], f["radius_ohm"]
                th = np.linspace(0, math.pi, 200)
                ax.plot(cx + R * np.cos(th), cy + R * np.sin(th),
                        linestyle="--", linewidth=0.6, color="#777777", zorder=1)
        fig.text(layer["left"] / 100.0, 0.015, FIT_DISCLAIMER_EN,
                 fontsize=6, color="#555555", fontname=fonts)

    # 线与标记分两层：所有连线先画在下层，所有封闭实心符号统一画在上层。
    # 否则后画曲线的连线会横穿先画曲线的符号中心，把该曲线的颜色整段盖掉。
    # 每条曲线的线/符号都带 gid（cv0-line-0 / cv0-mk）：页面靠它在 SVG 里
    # 单独淡出某条曲线（框选删点时"只框这一条"），PDF 不受影响。
    cidx = {pd["curve"]: i for i, pd in enumerate(plotted)}
    for pd in plotted:
        if focus_fit and pd["curve"] in fit_info:
            fit = fit_info[pd["curve"]]
            pd["fit_display_range"] = (fit["x_from"] + pd["off_x"] - 1e-6,
                                       fit["x_to"] + pd["off_x"] + 1e-6)
            pd["context_color"] = to_hex(0.38 * np.array(to_rgb(pd["color"])) + 0.62)
        pd["n_line_pts"] = 0
        if connect == "scatter":        # 散点图：一条线都不画
            continue
        for si, seg in enumerate(pd["runs"]):   # 一段一条线：剔除处断开，不跨断点连直线
            xy = [(p[0], p[1]) for p in seg]
            if connect == "smooth":
                xy = smooth_path(xy)
            if len(xy) < 2:
                continue
            ln, = ax.plot([p[0] for p in xy], [p[1] for p in xy], linestyle="-",
                          linewidth=st["line_width_pt"] * (0.65 if pd["reference"] else 1),
                          color=pd.get("context_color", pd["color"]), zorder=1)
            ln.set_gid("cv%d-line-%d" % (cidx[pd["curve"]], si))
            pd["n_line_pts"] += len(xy)
    # 点少的曲线后画，减少被平行重复曲线整段压住的机会（不改数据、不改点序）
    for pd in sorted(plotted, key=lambda d: -d["n_plotted"]):
        if is_fscv and connect != "scatter":
            continue
        start, stop = pd.get("fit_display_range", (-math.inf, math.inf))
        foreground = [p for p in pd["points"] if start <= p[0] <= stop]
        context = [p for p in pd["points"] if not start <= p[0] <= stop]
        if context:
            context_marker, = ax.plot([p[0] for p in context], [p[1] for p in context], linestyle="None",
                    marker=MARKER_MAP[pd["marker"]], markersize=st["marker_size_pt"] * 0.71,
                    markeredgewidth=0, color=pd["context_color"], zorder=1)
            context_marker.set_gid("cv%d-context" % cidx[pd["curve"]])
        marker, = ax.plot([p[0] for p in foreground], [p[1] for p in foreground],
                          linestyle="None", marker=MARKER_MAP[pd["marker"]],
                          markersize=st["marker_size_pt"] * (0.75 if pd["reference"] else 1), markerfacecolor=pd["color"],
                          markeredgecolor=pd["color"], markeredgewidth=0.25,
                          color=pd["color"], zorder=3)
        marker.set_gid("cv%d-mk" % cidx[pd["curve"]])

    # 线画完了才有力气回报"实际画了几个连线顶点"（散点=0，平滑>点数）
    for pd in plotted:
        g = geoms.get(pd["curve"])
        if g is not None:
            g["n_line_pts"] = pd.get("n_line_pts", 0)

    ax.set_xlim(lx0, lx1)
    ax.set_ylim(ly0, ly1)
    if is_fscv:
        # Anchor tick labels at zero independently of the padding around the data.
        ax.xaxis.set_major_locator(MultipleLocator(lxi))
        ax.yaxis.set_major_locator(MultipleLocator(lyi))
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.tick_params(axis="x", which="minor", direction=st["tick_dir"], top=not open_axes, length=2)
    else:
        x_ticks = np.arange(lx0, lx1 + lxi * 0.5, lxi)
        y_ticks = np.arange(ly0, ly1 + lyi * 0.5, lyi)
        ax.set_xticks(np.where(abs(x_ticks) < lxi * 1e-10, 0, x_ticks))
        ax.set_yticks(np.where(abs(y_ticks) < lyi * 1e-10, 0, y_ticks))
    ax.xaxis.set_major_formatter(FormatStrFormatter("%g"))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
    if is_ms and axs.get("ms_y_exponent") == 10:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{100 * value:g}"))
    ax.tick_params(axis="both", which="major", direction=st["tick_dir"],
                   top=not open_axes, right=not open_axes, length=3.0, width=0.6, pad=3)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontfamily(fonts)
        lbl.set_fontsize(st["tick_pt"])
    axis_title_style = dict(fontsize=st["title_pt"], fontname=fonts,
                            fontweight=st.get("axis_title_weight", "normal"), labelpad=2)
    ax.set_xlabel(axs["x_title"], **axis_title_style)
    ax.set_ylabel(axs["y_title"], **axis_title_style)
    for side, sp in ax.spines.items():
        sp.set_visible(not open_axes or side in ("left", "bottom"))
        sp.set_linewidth(st.get("frame_line_width_pt", 0.6))
        if open_axes:
            sp.set_color("#666666")
    ax.grid(st.get("grid", False))
    if st.get("equal_aspect"):
        ax.set_aspect("equal", adjustable="box")

    if frequency_key:
        names = {s["curve"]: s["name"] for s in spec["series"]}
        handles = [ax.plot([], [], linestyle="None", marker=MARKER_MAP[pd["marker"]],
                           color=pd["color"], markersize=max(3.3, st["marker_size_pt"]),
                           markeredgewidth=0,
                           label=names[pd["curve"]])[0] for pd in plotted]
        ax.legend(handles=handles, loc="upper left", frameon=False,
                  prop={"family": fonts, "size": st["tick_pt"]},
                  handlelength=0.9, handletextpad=0.45, borderaxespad=0.7, labelspacing=0.45)
    if shared_window is not None and fit_info and data.get("show_fit_intercepts"):
        zero = next(iter(fit_info.values()))["zero_V"]
        if all(pd["off_x"] == pd["off_y"] == 0 for pd in plotted):
            ax.annotate(f"{zero:.2f} V".replace("-", "−"), xy=(zero, 0),
                        xytext=(0, 15), textcoords="offset points", ha="center",
                        va="bottom", fontsize=st["tick_pt"], fontname=fonts,
                        fontweight="bold" if focus_fit else "normal",
                        arrowprops={"arrowstyle": "-|>", "lw": 0.55, "color": "#303030"},
                        color="#222222", zorder=6)
    if is_fscv:
        names = {series["curve"]: series.get("name") or series["curve"] for series in spec["series"]}
        handles = [Line2D([], [], color=pd["color"], linewidth=st["line_width_pt"],
                          linestyle="None" if connect == "scatter" else "-",
                          marker=MARKER_MAP[pd["marker"]] if connect == "scatter" else None,
                          label=names[pd["curve"]]) for pd in plotted]
        ax.legend(handles=handles, loc=spec["legend"].get("loc", "upper right"), frameon=False,
                  prop={"family": fonts, "size": st["tick_pt"]},
                  handlelength=1.5, handletextpad=0.55, labelspacing=0.32)
        table_curve = st.get("fscv_peak_table_curve")
        if table_curve:
            _draw_fscv_peak_table(ax, plotted, data["break_before_point"][0], table_curve, names, fonts)
    annotations = ([] if frequency_key or is_fscv else
                   _place_annotations(ax, plotted, limits, st["tick_pt"], fonts, dpi,
                                      spec, {s["curve"]: s for s in spec["series"]}))
    texts = _draw_texts(fig, spec, fonts)
    points_norm = normalize_points(plotted, limits, layer)
    if is_ms:
        for point, (_, _, row) in zip(points_norm, (pt for pd in plotted for pt in pd["points"])):
            point.update(potential_V=float(row["potential_V"]), inverse_Cs2=point["Zpp_neg_ohm"],
                         phase_deg=float(row["phase_deg"]))
    elif is_uvvis:
        for point, (_, _, row) in zip(points_norm, (pt for pd in plotted for pt in pd["points"])):
            point.update(wavelength_nm=float(row["wavelength_nm"]), absorbance=float(row["absorbance"]))
    elif is_fscv:
        for point, (_, _, row) in zip(points_norm, (pt for pd in plotted for pt in pd["points"])):
            point.update(potential_V=float(row["potential_V"]), current_nA=float(row["current_nA"]))

    return {
        "fig": fig, "ax": ax, "spec": spec, "plotted": plotted,
        "limits": limits, "geometry": geoms, "fit": fit_info,
        "connect": connect,
        "points_norm": points_norm, "annotations": annotations, "texts": texts,
        "validation": v, "dpi": dpi,
        "data_bbox": {"x": [min(raw_x), max(raw_x)],
                      "y": [min(raw_y), max(raw_y)]},
    }


def svg_string(built: dict) -> str:
    """服务端渲染 SVG 嵌入页面（真文字，不转轮廓）。"""
    buf = io.StringIO()
    built["fig"].savefig(buf, format="svg")
    return buf.getvalue()


def close(built: dict) -> None:
    plt.close(built["fig"])
