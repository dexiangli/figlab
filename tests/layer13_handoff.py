# -*- coding: utf-8 -*-
"""第十三层：所见即所得 + 成品只放桌面一个文件夹 + 项目可存可再开。

用户提的三件事（2026-11-14）：

  A. 工作台是散点，导出的 PPT 却是折线 —— 说明导出读的是磁盘旧规格；
  B. 成品位置不好找、文件夹里东西太多；
  C. 改完要能存下来，以后打开继续调。

本层验证：

  1. 导出以**页面传上来的规格**为准：磁盘上是折线、传散点，导出结果就是散点，
     并且磁盘也被更新成同一份（下次打开不会退回去）；
  2. 桌面成品文件夹里只有成品（PDF / PPT / .figlab），没有报告 json、没有 csv；
  3. 后台自动导出（deliver=false）**不往桌面写任何东西**；
  4. PPT 里嵌的那张图，像素上更接近散点渲染而不是折线渲染（不只是"文件存在"）；
  5. 项目文件保存 → 打开，画法/数据行数原样回来，且生成新图不覆盖原图；
  6. 校验不通过的规格：拒绝导出，磁盘规格一个字都不改；
  7. 真实数据集 md5 全程未变。

隔离：数据集复制到 _selftest13，成品根目录用 export.handoff_root 指到 tmp_test_out，
收尾全部删干净——不往用户桌面撒测试文件。
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import handoff, paths, project                 # noqa: E402
from figlab.spec.merge import load_spec                     # noqa: E402
from figlab.web.server import Handler                       # noqa: E402

PORT = 8785
SRC_DS = "eis_20261107"
TMP_DS = "_selftest13"
TMP_FIG = "_selftest13"
OUT_ROOT = os.path.join(ROOT, "tmp_test_out")
OK = FAIL = 0


def req(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (PORT, path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=300) as f:
            raw = f.read()
            ct = f.headers.get("Content-Type", "")
            return f.status, (json.loads(raw) if "application/json" in ct else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "ignore")}


def get(path):
    return req("GET", path)


def post(path, body):
    return req("POST", path, body)


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  [通过] %s%s" % (name, ("  " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        print("  [失败] %s%s" % (name, ("  " + str(detail)) if detail else ""))


def md5(path):
    if not os.path.isfile(path):
        return "-"
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def _rmtree(p):
    def onerr(func, path, exc):
        try:
            os.chmod(path, 0o700)
            func(path)
        except Exception:
            pass
    if os.path.isdir(p):
        shutil.rmtree(p, onerror=onerr)


def setup_isolated():
    _rmtree(paths.dataset_dir(TMP_DS))
    shutil.copytree(paths.dataset_dir(SRC_DS), paths.dataset_dir(TMP_DS))
    _rmtree(OUT_ROOT)
    spec = copy.deepcopy(load_spec("eis_main"))
    spec["id"] = TMP_FIG
    spec["data"]["dataset"] = TMP_DS
    spec["data"]["working_csv"] = paths.working(TMP_DS)
    spec["export"].update({
        "dir": os.path.join(paths.OUTPUTS, TMP_FIG),
        "base": TMP_FIG, "auto_name": False, "formats": ["pdf"],
        # 自测的成品根目录，不碰桌面
        "handoff_root": OUT_ROOT,
        "archive_root": os.path.join(ROOT, "tmp_test_archive"),
    })
    spec.setdefault("style", {})["connect"] = "segment"
    spec["style"]["break_gaps"] = True
    os.makedirs(spec["export"]["dir"], exist_ok=True)
    with open(paths.spec_file(TMP_FIG), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)


def teardown():
    _rmtree(paths.dataset_dir(TMP_DS))
    _rmtree(os.path.join(paths.OUTPUTS, TMP_FIG))
    _rmtree(OUT_ROOT)
    _rmtree(os.path.join(ROOT, "tmp_test_archive"))
    # 打开项目时可能生成了 _selftest13_r2 之类的图，一并清掉
    for name in os.listdir(paths.SPECS) if os.path.isdir(paths.SPECS) else []:
        if name.startswith("_selftest13") and name.endswith(".json"):
            try:
                os.chmod(os.path.join(paths.SPECS, name), 0o644)
                os.remove(os.path.join(paths.SPECS, name))
            except OSError:
                pass
    for p in (paths.spec_file(TMP_FIG),
              os.path.join(paths.ROOT, "history", TMP_DS + ".json")):
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o644)
                os.remove(p)
            except OSError:
                pass
    data = project.load()
    keep = [f for f in data["figures"] if not f["id"].startswith("_selftest13")]
    if len(keep) != len(data["figures"]):
        data["figures"] = keep
        project.save(data)


def disk_spec():
    with open(paths.spec_file(TMP_FIG), encoding="utf-8") as fh:
        return json.load(fh)


def list_files(d):
    out = []
    for r, _ds, ns in os.walk(d):
        for n in ns:
            out.append(os.path.relpath(os.path.join(r, n), d).replace("\\", "/"))
    return sorted(out)


def pixel_diff(a: bytes, b: bytes) -> float:
    """两张 PNG 的平均像素差（0=一样）。缩放不过，尺寸不同直接算大值。"""
    from PIL import Image
    import numpy as np
    ia = Image.open(io.BytesIO(a)).convert("RGB")
    ib = Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        return 999.0
    x = np.asarray(ia, dtype="int16")
    y = np.asarray(ib, dtype="int16")
    return float(np.abs(x - y).mean())


def render_png(spec: dict, dpi: int = 220) -> bytes:
    from figlab.render.engine import close, prepare
    built = prepare(spec)
    buf = io.BytesIO()
    built["fig"].savefig(buf, format="png", dpi=dpi)
    close(built)
    return buf.getvalue()


def main() -> int:
    print("=" * 74)
    print("第十三层：所见即所得导出 / 桌面一个文件夹 / 项目可存可再开")
    print("=" * 74)

    real_a = md5(paths.working(SRC_DS))
    real_b = md5(paths.working("photothermal_20261111")) if os.path.isfile(
        paths.working("photothermal_20261111")) else "-"

    setup_isolated()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        # ---------------------------------------------------------- 1. 控件
        print("\n[1] 页面上的入口")
        code, page = get("/")
        html = page.decode("utf-8") if isinstance(page, bytes) else str(page)
        for key, why in (("btnSaveProj", "保存项目按钮"),
                         ("btnOpenProj", "打开项目按钮"),
                         ("projFile", "选项目文件的输入框"),
                         ("outPath", "成品路径提示"),
                         ("导出到桌面", "导出按钮文案")):
            check("控件存在：%s" % why, key in html)
        check("页面不再把成品说成「归档到 FigLab输出」",
              "FigLab输出\\&lt;日期&gt;" not in html and "已归档到" not in html)

        # ---------------------------------------------------------- 2. 所见即所得
        print("\n[2] 界面是散点 → 导出必须也是散点（磁盘上原本是折线）")
        code, fig = get("/api/figure?id=" + TMP_FIG)
        page_spec = copy.deepcopy(fig["spec"])
        check("基线：磁盘规格是折线", disk_spec()["style"]["connect"] == "segment",
              disk_spec()["style"]["connect"])
        page_spec["style"]["connect"] = "scatter"        # 用户在界面上切成散点
        page_spec["export"]["formats"] = ["pdf"]

        code, d = post("/api/export", {"figure": TMP_FIG, "spec": page_spec,
                                       "deliver": True})
        check("导出成功", code == 200 and d.get("ok"), d.get("problems") or d.get("error"))
        rep_path = os.path.join(paths.out_dir(TMP_FIG), "export_report.json")
        with open(rep_path, encoding="utf-8") as fh:
            rep = json.load(fh)
        check("导出报告记录的是散点", rep.get("connect") == "scatter", rep.get("connect"))
        check("磁盘规格也被更新成散点（下次打开不会退回去）",
              disk_spec()["style"]["connect"] == "scatter",
              disk_spec()["style"]["connect"])
        check("导出/核验合格", d.get("export_status") == "合格" and
              d.get("verify_status") == "合格",
              "%s / %s" % (d.get("export_status"), d.get("verify_status")))

        # ---------------------------------------------------------- 3. 成品只放成品
        print("\n[3] 桌面成品文件夹：一个图一个文件夹，只放成品")
        fdir = handoff.figure_dir(TMP_FIG, disk_spec())
        check("成品文件夹按图名建", os.path.isdir(fdir), fdir)
        files = list_files(fdir)
        check("有 PDF", any(f.endswith(".pdf") for f in files), files)
        check("有 .figlab 项目文件", any(f.endswith(".figlab") for f in files), files)
        bad = [f for f in files if f.endswith((".json", ".csv")) or "/" in f]
        check("没有报告 json / csv / 子目录", not bad, bad)

        # ---------------------------------------------------------- 4. 自动导出不碰桌面
        print("\n[4] 后台自动导出（deliver=false）不往桌面写")
        before = list_files(OUT_ROOT)
        code, auto = post("/api/export", {"figure": TMP_FIG,
                                          "spec": disk_spec(), "deliver": False})
        check("自动导出本身成功", auto.get("ok") and auto.get("export_status") == "合格")
        after = list_files(OUT_ROOT)
        check("成品文件夹一个文件都没多", before == after,
              "%d → %d" % (len(before), len(after)))
        check("自动导出不回传 handoff", "handoff" not in auto)

        # ---------------------------------------------------------- 5. PPT 里真的是散点
        print("\n[5] PPT 里嵌的那张图，就是散点规格渲染出来的那一次")
        code, pp = post("/api/pptx", {"figure": TMP_FIG, "spec": disk_spec(),
                                      "mode": "new", "dpi": 220})
        check("PPT 生成成功", pp.get("ok"), pp.get("error"))
        check("PPT 落在同一个成品文件夹", os.path.dirname(pp.get("path", "")) == fdir,
              pp.get("path"))
        with zipfile.ZipFile(pp["path"]) as z:
            media = [n for n in z.namelist() if n.startswith("ppt/media/")]
            embedded = z.read(media[0]) if media else b""
        check("PPT 里有一张图", bool(embedded), media)

        # matplotlib 的 PNG 输出是确定性的（同一规格两次渲染逐字节相同），
        # 所以可以直接拿字节比对：PPT 里那张图 == 散点规格渲染出来的那张。
        sc = copy.deepcopy(disk_spec())
        sc["style"]["connect"] = "scatter"
        sg = copy.deepcopy(disk_spec())
        sg["style"]["connect"] = "segment"
        p_scatter = render_png(sc)
        p_segment = render_png(sg)
        check("证据有效：散点与折线渲染出来的图本身不同",
              hashlib.md5(p_scatter).hexdigest() != hashlib.md5(p_segment).hexdigest())
        check("PPT 内嵌图与散点渲染逐字节一致", embedded == p_scatter,
              "%d vs %d 字节" % (len(embedded), len(p_scatter)))
        check("PPT 内嵌图不是折线那一张", embedded != p_segment)
        d_scatter = pixel_diff(embedded, p_scatter)
        d_segment = pixel_diff(embedded, p_segment)
        check("像素上也贴着散点", d_scatter < 1e-9 and d_segment >= 0,
              "散点差 %.3f / 折线差 %.3f" % (d_scatter, d_segment))

        # ---------------------------------------------------------- 6. 项目往返
        print("\n[6] 保存项目 → 打开项目：画法与数据都回来，且不覆盖原图")
        code, sv = post("/api/project/save", {"figure": TMP_FIG, "spec": disk_spec()})
        check("保存项目成功", sv.get("ok"), sv.get("error"))
        proj_path = sv.get("path", "")
        check("项目文件在成品文件夹里", os.path.dirname(proj_path) == fdir, proj_path)
        with open(proj_path, encoding="utf-8") as fh:
            pdoc = json.load(fh)
        check("项目文件是自包含的（带工作副本）",
              pdoc.get("kind") == "figlab-project" and
              len(pdoc["data"]["working_csv"].splitlines()) > 10,
              "%d 行" % len(pdoc["data"]["working_csv"].splitlines()))

        # 模拟"过几天又打开这个项目"
        code, op = post("/api/project/open", {"text": json.dumps(pdoc, ensure_ascii=False)})
        check("打开项目成功", op.get("ok"), op.get("error"))
        new_id = op.get("id", "")
        check("生成了新图、不覆盖原图", bool(new_id) and new_id != TMP_FIG, new_id)
        check("打开后的图仍是散点",
              (op.get("spec") or {}).get("style", {}).get("connect") == "scatter",
              (op.get("spec") or {}).get("style", {}).get("connect"))
        check("打开后图上有数据点", len(op.get("points") or []) > 10,
              len(op.get("points") or []))
        check("原图还在", os.path.isfile(paths.spec_file(TMP_FIG)))

        code, bad = post("/api/project/open", {"text": "{not json"})
        check("坏项目文件被明确拒绝", bad.get("ok") is False and "JSON" in bad.get("error", ""),
              bad.get("error"))

        # ---------------------------------------------------------- 7. 坏规格不落盘
        print("\n[7] 校验不通过的规格：拒绝导出，磁盘一个字不改")
        keep = md5(paths.spec_file(TMP_FIG))
        junk = copy.deepcopy(disk_spec())
        junk["style"]["connect"] = "wobble"          # 非法值
        code, ej = post("/api/export", {"figure": TMP_FIG, "spec": junk,
                                        "deliver": True})
        check("拒绝导出", ej.get("ok") is False and ej.get("problems"), ej.get("problems"))
        check("磁盘规格未被写坏", md5(paths.spec_file(TMP_FIG)) == keep)

        # ---------------------------------------------------------- 8. 真实数据
        print("\n[8] 真实数据没被碰")
        check("eis_20261107/working.csv 未改", md5(paths.working(SRC_DS)) == real_a)
        check("photothermal_20261111/working.csv 未改",
              md5(paths.working("photothermal_20261111")) == real_b)
    finally:
        srv.shutdown()
        srv.server_close()
        teardown()

    print("\n" + "=" * 74)
    print("合计：%d 通过 / %d 失败" % (OK, FAIL))
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
