# -*- coding: utf-8 -*-
"""交互层业务逻辑：服务端渲染 SVG、改数据、改版式、导出、核验。

每轮改动后重新导出并重新过一遍核验（规范 §十），返回数字而不是形容词。
"""
from __future__ import annotations

import copy
import json
import os
import re

from .. import handoff, paths, project, pptx_out
from ..archive import archive_index          # 只读旧归档列表，写入路径已停用
from ..data import NUMERIC_COLUMNS
from ..data.dataset import read_long
from ..data.diff import compare
from ..data.workbook import apply_ops, redo, undo, workbook
from ..render.engine import close, prepare, svg_string
from ..render.export import export
from ..spec.merge import (build_spec, list_figures, load_spec,
                          remove_figure, resolve_name, sanitize_base, save_spec)
from ..spec.schema import PRESET_NAMES, validate
from ..verify.report import verify


def _strip_svg(s: str) -> str:
    s = re.sub(r"<\?xml[^>]*\?>", "", s)
    s = re.sub(r"<!DOCTYPE[^>]*>", "", s, flags=re.S)
    return s.strip()


def _userpath(p) -> str:
    """页面上手填的路径：去空白，并把 ~ 与环境变量展开成真实路径。

    用户可能写 ``~/Desktop/组会.pptx``（mac/Linux 习惯）或 ``%USERPROFILE%\\Desktop``，
    直接丢给 open() 会找不到；这里统一展开一次，空值仍返回空串。
    """
    s = str(p or "").strip().strip('"').strip("'")
    if not s:
        return ""
    return os.path.normpath(os.path.expandvars(os.path.expanduser(s)))


def _payload(built: dict, spec: dict) -> dict:
    """把一次渲染的结果打包给页面：SVG + 热区点 + 标注 + 文字 + 规格。

    一律取 built 里的实时值，不读 points.json——快速渲染不写文件，
    读磁盘会拿到上一次的点位，拖动时热区就会整体偏一帧。
    """
    return {"svg": _strip_svg(svg_string(built)),
            "points": built["points_norm"],
            "effective_range": built["limits"],
            "annotations": built["annotations"],
            "texts": built.get("texts", []),
            # 每条曲线现在由几段线画成（框选剔除中段后会断开，>1 即为断开）
            "segments": {pd["curve"]: pd.get("n_runs", 1) for pd in built["plotted"]},
            # 连线画法（散点/折线/平滑）与每条曲线实际画出的连线顶点数
            "connect": built.get("connect", "segment"),
            "line_vertices": {pd["curve"]: pd.get("n_line_pts", 0)
                              for pd in built["plotted"]},
            # 曲线名 → SVG 里的序号（gid 前缀 cv<N>），页面靠它单独淡出某条曲线
            "curve_gids": {pd["curve"]: i for i, pd in enumerate(built["plotted"])},
            # 成品落在哪：桌面\FigLab\<图名>\（PDF / PPT / .figlab 同处）
            "figure_dir": handoff.figure_dir(spec["export"]["base"], spec),
            "output_dir": paths.absolute(spec["export"]["dir"]),
            "spec": spec,
            "page_cm": [spec["page"]["w_cm"], spec["page"]["h_cm"]]}


def get_figure(fig_id: str) -> dict:
    """只生成 SVG 供页面显示，不强制重新导出文件。"""
    spec = load_spec(fig_id)
    built = prepare(spec)
    out = _payload(built, spec)
    close(built)
    out.update({"id": fig_id, "ok": True})
    return out


def re_render(fig_id: str, full: bool = True, lock_axis: bool = False,
              spec: dict | None = None, deliver: bool = False) -> dict:
    """改动后重新渲染。

    full=False 是「跟手」通道：只渲染 SVG（约 30 ms），不写 PDF、不核验、不归档，
    页面先立刻看到结果；再由前端在停顿 1.2 s 后自动走一次 full=True 补齐
    导出件与核验数字。这样点按钮不会卡住整台服务。

    spec：页面当前那一份完整规格。给了就以它为准（先校验、再落盘、再渲染），
    绝不再去磁盘上读旧值——「所见即所得」就是靠这一条落地的：
    页面显示的是散点，导出的就一定是散点。

    deliver：是否把成品复制到桌面\\FigLab\\<图名>\\。
    只有用户亲手点「导出」才为 True；后台自动重渲染只写 outputs，
    桌面不会因为改一个点就多出一堆文件。
    """
    if spec is not None:
        spec = copy.deepcopy(spec)
        spec["id"] = fig_id
        v = validate(spec)
        if not v["ok"]:
            return {"ok": False, "problems": v["problems"]}
        save_spec(spec)                            # 校验通过才写盘
    else:
        spec = load_spec(fig_id)
    if full:
        spec, renamed = resolve_name(spec)   # 按数据日期定名，定完冻住
        if renamed:
            save_spec(spec)
    v = validate(spec)
    if not v["ok"]:
        return {"ok": False, "problems": v["problems"]}
    built = prepare(spec, lock_axis=lock_axis)
    out = _payload(built, spec)
    if not full:
        close(built)
        out.update({"ok": True, "id": fig_id, "fast": True,
                    "base": spec["export"]["base"],
                    "export_status": None, "verify_status": None,
                    "n_points": len(built["points_norm"]),
                    "n_curves": len(built["plotted"])})
        return out
    rep = export(built, spec)
    close(built)
    vr = verify(spec)
    out.update({"ok": True, "id": fig_id, "fast": False,
                "base": spec["export"]["base"],
                "export_status": rep["status"], "verify_status": vr["status"],
                "verify_checks": vr["checks"], "verify_failures": vr["failures"],
                "n_points": len(built["points_norm"]),
                "n_curves": len(built["plotted"])})
    if deliver:
        # 桌面只放成品：PDF/EPS/SVG/PNG 直接躺在「图名」文件夹里
        out["handoff"] = handoff.deliver(spec, rep)
        out["project_file"] = handoff.save_project(fig_id, spec)
    return out



def figure_list() -> list[dict]:
    return list_figures()


def add_figure(fig_id: str, preset: str = "inhouse",
               dataset: str = "eis_20261107", folder: str = "") -> dict:
    if not fig_id or not re.fullmatch(r"[A-Za-z0-9_\-]+", fig_id):
        return {"ok": False, "error": "图 ID 只能用字母数字下划线连字符"}
    if preset not in PRESET_NAMES:
        return {"ok": False, "error": "未知预设"}
    rows = read_long(paths.working(dataset), "eis")
    curves = sorted({r["curve"] for r in rows})
    spec = build_spec(fig_id, dataset, curves, preset=preset,
                      note="由网页新建；使用默认预设", tail_ohm=60.0)
    save_spec(spec)
    if folder:
        project.move_figure(fig_id, folder)
    return {"ok": True, "id": fig_id, "checks": validate(spec)["checks"],
            "project": project.snapshot()}


def delete_figure(fig_id: str) -> dict:
    remove_figure(fig_id)
    p = paths.spec_file(fig_id)
    if os.path.isfile(p):
        os.remove(p)
    return {"ok": True, "figures": figure_list(), "project": project.snapshot()}


# ------------------------------------------------------------------ 项目管理器
def project_view() -> dict:
    return project.snapshot()


def project_op(body: dict) -> dict:
    """文件夹 / 窗口的组织动作；一律回整棵项目树，前端只认一个真相。"""
    op = str(body.get("op") or "")
    if op == "new-folder":
        out = project.new_folder(body.get("name", ""))
    elif op == "rename-folder":
        out = project.rename_folder(body["id"], body.get("name", ""))
    elif op == "toggle-folder":
        out = project.toggle_folder(body["id"])
    elif op == "delete-folder":
        out = project.delete_folder(body["id"])
    elif op == "move-figure":
        out = project.move_figure(body["id"], body["folder"])
    elif op == "rename-figure":
        out = project.rename_figure(body["id"], body.get("title", ""))
    elif op == "delete-figure":
        return delete_figure(body["id"])
    else:
        return {"ok": False, "error": "未知操作 %r" % op}
    out["project"] = project.snapshot()
    return out


# ------------------------------------------------------------------ 一键出 PPT
def export_pptx(fig_id: str, body: dict) -> dict:
    """把**当前页面上那张图**（规格由页面整份传上来）放进 16:9 幻灯片。

    不再自己 load_spec：页面显示散点、PPT 里就必须是散点。
    页面没传 spec 时才退回读磁盘（老调用方式）。
    成品默认落在 桌面\\FigLab\\<图名>\\<图名>.pptx，与 PDF 同一个文件夹。
    """
    spec = body.get("spec")
    if isinstance(spec, dict) and spec:
        spec = copy.deepcopy(spec)
        spec["id"] = fig_id
        v = validate(spec)
        if not v["ok"]:
            return {"ok": False, "problems": v["problems"]}
        save_spec(spec, register=False)
    else:
        spec = load_spec(fig_id)
    spec, _ = resolve_name(spec)
    save_spec(spec, register=False)

    outdir = paths.absolute(spec["export"]["dir"])
    paths.ensure_dirs(outdir)
    base = spec["export"]["base"]
    dpi = int(body.get("dpi") or 1200)

    built = prepare(spec)
    png = os.path.join(outdir, base + "_ppt.png")
    built["fig"].savefig(png, format="png", dpi=dpi)
    close(built)

    url = str(body.get("url") or "").strip() or \
        "http://127.0.0.1:8778/?fig=" + fig_id
    caption = body.get("caption")
    caption = base if caption is None else str(caption)
    subtitle = str(body.get("subtitle") or "")

    def _in_out_root(path: str) -> bool:
        root = handoff.out_root(spec).replace("/", "\\").lower()
        return path.replace("/", "\\").lower().startswith(root)

    if str(body.get("mode") or "new").lower() == "append":
        target = _userpath(body.get("path"))
        res = pptx_out.append(spec, png, url, target, caption, subtitle)
        if not res.get("ok"):
            return res
        res["png"] = png
        res["inspect"] = pptx_out.inspect(res["path"])
        # 追加目标本来就是成品文件夹里的那份：不必再复制一次（会撞出 _locked）
        if _in_out_root(res["path"]):
            res["handoff"] = {"ok": True, "path": res["path"],
                              "dir": os.path.dirname(res["path"])}
        else:
            res["handoff"] = handoff.deliver_extra(spec, res["path"])
        return res

    # 默认就放桌面图名文件夹里，和 PDF 并排；用户显式给 path 时以用户为准
    out = _userpath(body.get("path")) or \
        os.path.join(handoff.figure_dir(base, spec), base + ".pptx")
    res = pptx_out.build(spec, png, url, out, caption, subtitle)
    res["png"] = png
    res["png_bytes"] = os.path.getsize(png)
    res["dpi"] = dpi
    if _in_out_root(out):
        res["handoff"] = {"ok": True, "path": out, "dir": os.path.dirname(out)}
    else:
        res["handoff"] = handoff.deliver_extra(spec, res["path"])
    res["project_file"] = handoff.save_project(fig_id, spec)
    res["inspect"] = pptx_out.inspect(res["path"])
    return res



def pptx_list() -> dict:
    """桌面成品文件夹里的 PPT，供「追加到已有 PPT」选。

    新结构是 桌面\\FigLab\\<图名>\\<图名>.pptx；旧归档（日期/图片/pptx）也一并列出，
    免得以前生成的那几份突然选不到。
    """
    out = []
    root = handoff.out_root()
    if os.path.isdir(root):
        for name in sorted(os.listdir(root), reverse=True):
            d = os.path.join(root, name)
            if not os.path.isdir(d):
                continue
            for n in sorted(os.listdir(d)):
                if n.lower().endswith(".pptx"):
                    p = os.path.join(d, n)
                    out.append({"folder": name, "name": n, "path": p,
                                "bytes": os.path.getsize(p)})
    old = paths.archive_root()
    if os.path.isdir(old):
        for day in sorted(os.listdir(old), reverse=True)[:30]:
            d = os.path.join(old, day, "图片", "pptx")
            if not os.path.isdir(d):
                continue
            for n in sorted(os.listdir(d)):
                if n.lower().endswith(".pptx"):
                    p = os.path.join(d, n)
                    out.append({"folder": day, "name": n, "path": p,
                                "bytes": os.path.getsize(p), "old": True})
    return {"n": len(out), "files": out[:60]}


def patch_spec(fig_id: str, patch: dict, fast: bool = False) -> dict:
    """单图覆盖：覆盖项写入该图规格，不改预设。"""
    spec = load_spec(fig_id)
    merged = copy.deepcopy(spec)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    if isinstance(merged.get("export"), dict) and "base" in (patch.get("export") or {}):
        merged["export"]["base"] = sanitize_base(merged["export"]["base"])
    ov = merged.get("overrides", {})
    ov.update(patch)
    merged["overrides"] = ov
    v = validate(merged)
    if not v["ok"]:
        return {"ok": False, "problems": v["problems"]}
    save_spec(merged)
    return re_render(fig_id, full=not fast)


def curve_shift(fig_id: str, curve: str, dx: float, dy: float,
                lock_axis: bool = False) -> dict:
    """整条曲线平移（只有显示位置变，工作副本一行都不动）。

    前端拖线时每帧只发这三个数，不重传整个 series 数组——既不会被别的改动
    覆盖，也不会因为并发把两次拖动揉在一起。lock_axis=True 时轴范围按实测值
    算，拖动过程中不跳刻度；松手那一帧再按含平移的范围重算。
    """
    spec = load_spec(fig_id)
    hit = None
    for s in spec.get("series", []):
        if s.get("curve") == curve:
            s["off_x"] = round(float(dx), 4)
            s["off_y"] = round(float(dy), 4)
            hit = s
            break
    if hit is None:
        return {"ok": False, "error": "没有这条曲线：%s" % curve}
    v = validate(spec)
    if not v["ok"]:
        return {"ok": False, "problems": v["problems"]}
    save_spec(spec)
    out = re_render(fig_id, full=False, lock_axis=lock_axis)
    out["curve"] = curve
    out["off_x"], out["off_y"] = hit["off_x"], hit["off_y"]
    return out


def _ds_of(fig_id: str) -> tuple[str, str]:
    spec = load_spec(fig_id)
    return spec["data"]["dataset"], spec["data"].get("spectrum", "eis")


def _after_edit(fig_id: str, result: dict, fast: bool = False) -> dict:
    """任何数据改动后：重新渲染（fast 时只出 SVG），并把工作台状态一起回传。"""
    out = re_render(fig_id, full=not fast)
    out["diff"] = result["diff"]
    out["edit"] = {k: result[k] for k in
                   ("ok", "label", "kind", "n_ops", "n_rows", "changes",
                    "undo", "redo", "history_index", "history_len") if k in result}
    out["workbook"] = get_workbook(fig_id)
    return out


def edit_point(fig_id: str, body: dict) -> dict:
    """右栏单点编辑也走同一事务，保证撤销历史连续、台账口径统一。"""
    ds, spectrum = _ds_of(fig_id)
    curve, idx = body["curve"], body["point_index"]
    action = body["action"]
    reason = body.get("reason", "")
    if action == "value":
        op = {"op": "cell", "curve": curve, "point_index": idx,
              "field": body["field"], "value": body["value"]}
    elif action == "note":
        op = {"op": "note", "curve": curve, "point_index": idx, "note": body["note"]}
    elif action == "exclude":
        op = {"op": "include", "curve": curve, "point_index": idx,
              "include": False, "reason": reason}       # 无理由会被拒绝
    elif action == "restore":
        # 恢复不需要理由（规范只要求排除写理由）；没写理由就不往 note 里塞
        # 任何默认文案，否则备注列会被「网页恢复参与」之类的噪音污染。
        op = {"op": "include", "curve": curve, "point_index": idx,
              "include": True, "reason": reason}
    else:
        return {"ok": False, "error": "未知动作 %r" % action}
    res = apply_ops(ds, spectrum, [op], reason, "右栏单点编辑：%s" % action)
    return _after_edit(fig_id, res, bool(body.get("fast")))


def get_workbook(fig_id: str) -> dict:
    ds, spectrum = _ds_of(fig_id)
    return workbook(ds, spectrum)


def commit_workbook(fig_id: str, body: dict) -> dict:
    ds, spectrum = _ds_of(fig_id)
    res = apply_ops(ds, spectrum, body.get("ops") or [],
                    body.get("reason", ""), body.get("label", "工作台编辑"))
    return _after_edit(fig_id, res, bool(body.get("fast")))


def history_step(fig_id: str, kind: str, fast: bool = False) -> dict:
    ds, spectrum = _ds_of(fig_id)
    fn = undo if kind == "undo" else redo
    res = fn(ds, spectrum)
    return _after_edit(fig_id, res, fast)


def ledger_view(fig_id: str) -> dict:
    ds, _ = _ds_of(fig_id)
    p = paths.ledger(ds)
    data = []
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    counts = {}
    for r in data:
        counts[r.get("action", "?")] = counts.get(r.get("action", "?"), 0) + 1
    return {"n": len(data), "counts": counts, "records": data[-40:]}


def table(fig_id: str, curve: str) -> dict:
    spec = load_spec(fig_id)
    ds = spec["data"]["dataset"]
    rows = [r for r in read_long(paths.working(ds), "eis") if r["curve"] == curve]
    return {"curve": curve, "n": len(rows),
            "n_included": sum(1 for r in rows if str(r["include"]) == "1"),
            "rows": rows}


def reports(fig_id: str) -> dict:
    spec = load_spec(fig_id)
    d = paths.absolute(spec["export"]["dir"])
    out = {}
    for name in ("export_report.json", "verify_report.json", "geometry.json"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                out[name] = json.load(fh)
    return out


def thumbs(fig_id: str) -> list[str]:
    spec = load_spec(fig_id)
    d = paths.absolute(spec["export"]["dir"])
    return sorted(f for f in os.listdir(d) if f.lower().endswith(".png"))


# ------------------------------------------------------------------ 原始视图
def raw_view(fig_id: str) -> dict:
    """原始快照的只读视图：逐行标出「当前工作副本改了什么/排除了什么」。

    这样界面上能并排对照「原始 vs 处理后」，而不是只能看到被改过的表。
    """
    ds, spectrum = _ds_of(fig_id)
    rows = read_long(paths.raw_long(ds), spectrum)
    d = compare(ds, spectrum)
    chg = {tuple(c["key"]): c["fields"] for c in d["value_changed"]}
    flip = {tuple(f["key"]): f for f in d["include_flipped"]}

    out = []
    for r in rows:
        item = dict(r)
        k = (r.get("curve", ""), str(r.get("point_index", "")))
        if k in chg:
            # 只带当前工作值，原始值就是本行本身，不重复存
            item["_changed"] = {f: v[1] for f, v in chg[k].items()}
        if k in flip:
            item["_flip"] = {"from": flip[k]["from"], "to": flip[k]["to"],
                             "note": flip[k].get("note", "")}
        out.append(item)

    counts = {}
    for r in rows:
        counts[r["curve"]] = counts.get(r["curve"], 0) + 1
    return {"dataset": ds, "spectrum": spectrum, "n_rows": len(rows),
            "numeric_columns": list(NUMERIC_COLUMNS[spectrum]),
            "curves": [{"curve": c, "n": n} for c, n in sorted(counts.items())],
            "rows": out, "diff": d["counts"],
            "added": [a["key"] for a in d["rows_added"]],
            "lost": [l["key"] for l in d["rows_lost"]],
            "exclusions_without_reason": d["exclusions_without_reason"]}


def archive_view() -> dict:
    """桌面归档索引（最近几天、按类别列文件）。"""
    return archive_index()


def open_folder(fig_id: str = "", which: str = "archive") -> dict:
    """在资源管理器里打开成品文件夹或本图输出目录（仅本机）。"""
    if which == "output" and fig_id:
        p = paths.absolute(load_spec(fig_id)["export"]["dir"])
    elif which == "figure" and fig_id:
        # 桌面那个「图名」文件夹：用户要找 PDF / PPT 就开这个
        sp = load_spec(fig_id)
        p = handoff.figure_dir(sp["export"]["base"], sp)
    else:
        p = handoff.out_root()
    if not os.path.isdir(p):
        return {"ok": False, "error": "目录不存在：%s" % p, "path": p}
    if not hasattr(os, "startfile"):
        return {"ok": False, "error": "当前系统不支持直接打开目录", "path": p}
    os.startfile(p)                      # noqa: S606  仅本机、仅固定目录
    return {"ok": True, "path": p}


# ------------------------------------------------------------------ 项目文件
def save_project_file(fig_id: str, body: dict | None = None) -> dict:
    """把当前图存成 .figlab 项目文件（桌面图名文件夹里，和 PDF 并排）。"""
    body = body or {}
    spec = body.get("spec")
    if isinstance(spec, dict) and spec:
        spec = copy.deepcopy(spec)
        spec["id"] = fig_id
        v = validate(spec)
        if not v["ok"]:
            return {"ok": False, "problems": v["problems"]}
        save_spec(spec)
    res = handoff.save_project(fig_id)
    if res.get("ok"):
        res["hint"] = "下次用「打开项目」选这个文件就能接着改"
    return res


def open_project_file(body: dict) -> dict:
    """读上传的项目文件，恢复成一张可继续改的图。"""
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "没有收到项目文件内容"}
    got = handoff.read_project(text)
    if not got["ok"]:
        return got
    try:
        res = handoff.import_project(got["doc"], folder=str(body.get("folder") or ""))
    except Exception as e:
        return {"ok": False, "error": "恢复失败：%s: %s" % (type(e).__name__, e)}
    if not res.get("ok"):
        return res
    out = get_figure(res["id"])
    out.update(res)
    out["figures"] = figure_list()
    out["project"] = project.snapshot()
    return out
