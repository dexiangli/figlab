# -*- coding: utf-8 -*-
"""第十一层：连线画法（散点 / 折线 / 平滑）一键切换。

用户的原话是"文献里应该是散点图，但作图时用折线比较好看，要能一键切换"。
本层验证三件事：
  1. 三种画法只改"点怎么连"，一个数据点都不许动（点数、坐标、段数全不变）；
  2. 平滑是**过实测点的插值**，不是拟合——每个实测点都必须落在曲线上；
  3. 画法必须进留痕（points.json / geometry.json / export_report.json），
     否则以后看图的人分不清"这条线是测的还是算的"。

隔离原则与前两层一致：复制数据集到 _selftest11，只动副本，收尾删干净，
真实数据集前后做 md5 比对。
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths, project                          # noqa: E402
from figlab.render.curve import CONNECT_MODES, smooth_path  # noqa: E402
from figlab.spec.merge import load_spec                     # noqa: E402
from figlab.web.server import Handler                       # noqa: E402

PORT = 8783
SRC_DS = "eis_20261107"
TMP_DS = "_selftest11"
TMP_FIG = "_selftest11"
OK = FAIL = 0


# ------------------------------------------------------------------ 工具
def req(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (PORT, path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=180) as f:
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
    spec = copy.deepcopy(load_spec("eis_main"))
    spec["id"] = TMP_FIG
    spec["data"]["dataset"] = TMP_DS
    spec["data"]["working_csv"] = paths.working(TMP_DS)
    spec["export"].update({"dir": os.path.join(paths.OUTPUTS, TMP_FIG),
                           "base": TMP_FIG, "auto_name": False, "formats": ["pdf"],
                           "archive_root": os.path.join(ROOT, "tmp_test_archive")})
    spec.setdefault("style", {}).pop("connect", None)   # 故意不留这个键：老规格也要能用
    os.makedirs(spec["export"]["dir"], exist_ok=True)
    with open(paths.spec_file(TMP_FIG), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)


def teardown():
    _rmtree(paths.dataset_dir(TMP_DS))
    _rmtree(os.path.join(paths.OUTPUTS, TMP_FIG))
    _rmtree(os.path.join(ROOT, "tmp_test_archive"))
    for p in (paths.spec_file(TMP_FIG),
              os.path.join(paths.ROOT, "history", TMP_DS + ".json")):
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o644)
                os.remove(p)
            except OSError:
                pass
    try:
        project.drop(TMP_FIG)
    except Exception:
        pass


def near_pt(a, b, tol=1e-9):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


# ------------------------------------------------------------------ 主体
def main() -> int:
    print("=" * 70)
    print("第十一层：连线画法（散点 / 折线 / 平滑）一键切换")
    print("=" * 70)

    real_a = md5(paths.working(SRC_DS))
    real_b = md5(paths.working("photothermal_20261111")) if os.path.isfile(
        paths.working("photothermal_20261111")) else "-"

    # ---- [1] 插值函数本身（不依赖服务）
    print("\n[1] 平滑插值算法（PCHIP，过实测点）")
    arc = [(math.cos(math.pi - i * math.pi / 8), math.sin(math.pi - i * math.pi / 8))
           for i in range(9)]
    sp = smooth_path(arc, per_gap=8)
    check("插值加密（顶点数 > 点数）", len(sp) > len(arc), "%d → %d" % (len(arc), len(sp)))
    check("每个实测点都落在曲线上",
          all(any(near_pt(p, q) for q in sp) for p in arc))
    # 折线的误差出在**两点的中间**（弦在弧内），实测点上当然是 0，所以取弦中点算
    poly_err = max(abs(math.hypot((arc[i][0] + arc[i + 1][0]) / 2,
                                  (arc[i][1] + arc[i + 1][1]) / 2) - 1)
                   for i in range(len(arc) - 1))
    smooth_err = max(abs(math.hypot(*p) - 1) for p in sp)
    check("比折线更接近真圆", smooth_err < poly_err,
          "折线中点 %.4f → 平滑 %.4f" % (poly_err, smooth_err))
    check("首尾点严格对齐", near_pt(sp[0], arc[0]) and near_pt(sp[-1], arc[-1]))
    check("两点退化（没有弧度可插）", smooth_path(arc[:2]) ==
          [(float(a), float(b)) for a, b in arc[:2]])
    check("一点退化", len(smooth_path(arc[:1])) == 1)
    mono = [0, 1, 3, 6, 10, 15]
    msp = smooth_path([(i, v) for i, v in enumerate(mono)], per_gap=12)
    ys = [q[1] for q in msp]
    check("单调序列插值后仍单调（不制造假峰）",
          all(ys[i] <= ys[i + 1] + 1e-12 for i in range(len(ys) - 1)))
    check("取值不超出实测区间（保形，无过冲）",
          min(ys) >= 0 - 1e-9 and max(ys) <= 15 + 1e-9,
          "%.3f..%.3f" % (min(ys), max(ys)))

    setup_isolated()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        # ---- [2] 页面控件
        print("\n[2] 页面控件")
        code, html = get("/")
        html = html.decode("utf-8") if isinstance(html, bytes) else str(html)
        for key in ("connectToggle", "vConnect", "连线 折线", "散点（只符号）",
                    "折线（点直连）", "平滑（过点插值）", "?connect="):
            check("页面含 %s" % key, key in html)

        # ---- [3] 老规格没这个键 → 按折线
        print("\n[3] 缺省：老规格没有 style.connect 时按「折线」")
        code, fig = get("/api/figure?id=" + TMP_FIG)
        check("默认 connect=segment", fig.get("connect") == "segment", fig.get("connect"))
        base_pts = {(p["curve"], p["point_index"]): (p["nx"], p["ny"])
                    for p in fig["points"]}
        n_pts = len(fig["points"])
        base_seg = dict(fig["segments"])
        lv = fig.get("line_vertices") or {}
        cnt = {}
        for p in fig["points"]:
            cnt[p["curve"]] = cnt.get(p["curve"], 0) + 1
        check("折线：每条曲线的连线顶点数 = 点数",
              all(lv.get(c) == n for c, n in cnt.items()), list(lv.items())[:3])
        svg_seg = fig["svg"].count("<path")

        # ---- [4] 切散点
        print("\n[4] 切到「散点」：连线全没了，数据一个点都没动")
        code, d = post("/api/spec", {"figure": TMP_FIG,
                                     "patch": {"style": {"connect": "scatter"}},
                                     "fast": True})
        check("接口返回 ok", d.get("ok") is True, (d.get("problems") or d.get("error") or ""))
        check("connect=scatter", d.get("connect") == "scatter", d.get("connect"))
        check("连线顶点数全为 0", all(v == 0 for v in (d.get("line_vertices") or {}).values()),
              (d.get("line_vertices") or {}))
        check("数据点一个没少", len(d["points"]) == n_pts,
              "%d → %d" % (n_pts, len(d["points"])))
        after = {(p["curve"], p["point_index"]): (p["nx"], p["ny"]) for p in d["points"]}
        check("每个点的画布坐标都没动",
              set(after) == set(base_pts) and
              all(abs(after[k][0] - v[0]) < 1e-12 and abs(after[k][1] - v[1]) < 1e-12
                  for k, v in base_pts.items()))
        check("分几段也没变（散点不影响断线）", d.get("segments") == base_seg, d.get("segments"))
        check("SVG 里的线确实没了（path 变少）", d["svg"].count("<path") < svg_seg,
              "%d → %d" % (svg_seg, d["svg"].count("<path")))

        # ---- [5] 切平滑
        print("\n[5] 切到「平滑」：加密曲线，但仍然过每一个实测点")
        code, d2 = post("/api/spec", {"figure": TMP_FIG,
                                      "patch": {"style": {"connect": "smooth"}},
                                      "fast": True})
        check("connect=smooth", d2.get("connect") == "smooth", d2.get("connect"))
        lv2 = d2.get("line_vertices") or {}
        check("连线顶点数明显多于点数（确实插值了）",
              all(v > cnt.get(c, 0) * 3 for c, v in lv2.items()), list(lv2.items())[:3])
        check("数据点数量不变（插值只加密线，不加点）", len(d2["points"]) == n_pts)
        check("断线段数不受画法影响", d2.get("segments") == base_seg)
        check("SVG 里仍是一条直线段（没有裂成碎线）",
              d2["svg"].count("<path") == svg_seg, d2["svg"].count("<path"))

        # ---- [6] 非法值必须被拦
        print("\n[6] 非法画法要被拦下，且不能改坏规格")
        code, bad = post("/api/spec", {"figure": TMP_FIG,
                                       "patch": {"style": {"connect": "fit"}},
                                       "fast": True})
        check("非法值 ok=false", bad.get("ok") is False)
        check("报错里点名 style.connect",
              any("connect" in str(x) for x in (bad.get("problems") or [])),
              (bad.get("problems") or [])[:1])
        code, again = get("/api/figure?id=" + TMP_FIG)
        check("非法值没有写进规格（仍是 smooth）", again.get("connect") == "smooth",
              again.get("connect"))

        # ---- [7] 留痕
        print("\n[7] 导出留痕：points.json / geometry.json / export_report 都要写画法")
        code, ex = post("/api/export", {"figure": TMP_FIG})
        outdir = os.path.join(paths.OUTPUTS, TMP_FIG)
        reps = []
        for name in ("points.json", "geometry.json", "export_report.json"):
            with open(os.path.join(outdir, name), encoding="utf-8") as fh:
                reps.append(json.load(fh))
        pdoc, gdoc, rdoc = reps
        check("points.json 记了 connect", pdoc.get("connect") == "smooth", pdoc.get("connect"))
        check("points.json 标明是插值", pdoc.get("interpolated") is True)
        check("points.json 有可读说明", "插值" in (pdoc.get("connect_note") or ""),
              pdoc.get("connect_note"))
        check("points.json 记了每条曲线的连线顶点数",
              bool(pdoc.get("line_vertices")), pdoc.get("line_vertices"))
        check("geometry.json 记了 connect", gdoc.get("connect") == "smooth")
        check("geometry.json 每条曲线的 n_line_pts 也在",
              all("n_line_pts" in v for v in gdoc["curves"].values()))
        check("export_report 记了 connect", rdoc.get("connect") == "smooth")
        check("导出本身仍合格", rdoc.get("status") == "合格", rdoc.get("failures"))

        # 切回折线：留痕要跟着变，不能残留上次的说法
        post("/api/spec", {"figure": TMP_FIG,
                           "patch": {"style": {"connect": "segment"}}, "fast": True})
        post("/api/export", {"figure": TMP_FIG})
        with open(os.path.join(outdir, "points.json"), encoding="utf-8") as fh:
            pdoc2 = json.load(fh)
        check("切回折线后 interpolated=false", pdoc2.get("interpolated") is False)
        check("切回折线后 note 不再说插值",
              "插值" not in (pdoc2.get("connect_note") or ""), pdoc2.get("connect_note"))

        # ---- [8] 真实数据没被动
        print("\n[8] 真实数据集与真实规格")
        check("eis_20261107/working.csv 未改", md5(paths.working(SRC_DS)) == real_a)
        if real_b != "-":
            check("photothermal_20261111/working.csv 未改",
                  md5(paths.working("photothermal_20261111")) == real_b)
        check("实测主图规格没有 connect 被写脏",
              "connect" not in (load_spec("eis_main").get("style") or {})
              or load_spec("eis_main")["style"]["connect"] in CONNECT_MODES)

    finally:
        srv.shutdown()
        teardown()

    print("\n" + "=" * 70)
    print("合计 %d 项：通过 %d，失败 %d" % (OK + FAIL, OK, FAIL))
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
