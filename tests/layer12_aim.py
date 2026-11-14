# -*- coding: utf-8 -*-
"""第十二层：锁定一条曲线再框选（线多时只删这一条的点）。

做法是给每条曲线的线/符号在 SVG 里打 gid（cv<N>-line-<段>、cv<N>-mk），
页面靠它把非目标曲线淡出，并在框选时按曲线过滤。本层验证：

  1. gid 覆盖完整：每条曲线都有、索引连续、线和符号都在；
  2. 剔除断线后**每一段**都要有 gid —— 只标第一段的话，后半截淡不掉，
     框选时看着"这条线还在"，实际却选不中它的点；
  3. 散点模式没有线 gid（本来就没线），平滑模式仍然有；
  4. 页面有下拉与锁定入口；
  5. gid 只是 SVG 元数据，PDF 导出的自检必须照样合格。

隔离原则同前：复制数据集到 _selftest12，收尾删干净，真实数据 md5 比对。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths, project                          # noqa: E402
from figlab.spec.merge import load_spec                     # noqa: E402
from figlab.web.server import Handler                       # noqa: E402

PORT = 8784
SRC_DS = "eis_20261107"
TMP_DS = "_selftest12"
TMP_FIG = "_selftest12"
OK = FAIL = 0


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
    spec.setdefault("style", {})["connect"] = "segment"
    spec["style"]["break_gaps"] = True
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


def gids(svg):
    """SVG 里的 cv 分组：{'cv0-line-0': 1, 'cv0-mk': 1, ...}"""
    return re.findall(r'id="(cv\d+-(?:line-\d+|mk))"', svg)


def main() -> int:
    print("=" * 70)
    print("第十二层：锁定一条曲线再框选删点（线多时可用）")
    print("=" * 70)

    real_a = md5(paths.working(SRC_DS))
    real_b = md5(paths.working("photothermal_20261111")) if os.path.isfile(
        paths.working("photothermal_20261111")) else "-"

    setup_isolated()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        # ---- [1] gid 覆盖完整
        print("\n[1] SVG 分组标记：每条曲线都能被单独定位")
        code, fig = get("/api/figure?id=" + TMP_FIG)
        cg = fig.get("curve_gids") or {}
        curves = sorted({p["curve"] for p in fig["points"]})
        check("curve_gids 覆盖所有曲线", set(cg) == set(curves),
              "%d / %d" % (len(cg), len(curves)))
        check("序号从 0 连续到底", sorted(cg.values()) == list(range(len(cg))),
              sorted(cg.values()))
        g = gids(fig["svg"])
        n = len(cg)
        check("每条曲线都有一条线的 gid",
              sorted(x for x in g if "-line-" in x) ==
              sorted("cv%d-line-0" % i for i in range(n)),
              [x for x in g if "-line-" in x][:4])
        check("每条曲线都有一组符号的 gid",
              sorted(x for x in g if x.endswith("-mk")) ==
              sorted("cv%d-mk" % i for i in range(n)),
              [x for x in g if x.endswith("-mk")][:4])
        check("gid 不重复（每个只出现一次）", len(g) == len(set(g)), len(g))

        # ---- [2] 断线：每一段都要有 gid
        print("\n[2] 剔除中段后曲线断成 2 段 → 两段都要能淡出")
        cnt = {}
        for p in fig["points"]:
            cnt[p["curve"]] = cnt.get(p["curve"], 0) + 1
        curve = max(cnt, key=cnt.get)
        drawn = sorted([p for p in fig["points"] if p["curve"] == curve],
                       key=lambda p: p["Zp_ohm"])
        mid = len(drawn) // 2
        idxs = [str(p["point_index"]) for p in drawn[mid - 3:mid + 3]]
        code, d = post("/api/workbook", {
            "figure": TMP_FIG,
            "ops": [{"op": "include", "curve": curve, "point_index": i,
                     "include": False, "reason": "第十二层测试：断线 gid"} for i in idxs],
            "label": "测试剔除 6 点", "fast": True})
        check("剔除成功且该曲线断成 2 段", d.get("segments", {}).get(curve) == 2,
              d.get("segments"))
        g2 = gids(d["svg"])
        ci = cg[curve]
        segs = set(x for x in g2 if x.startswith("cv%d-line-" % ci))
        check("断成两段后两段都有 gid", segs == {"cv%d-line-0" % ci, "cv%d-line-1" % ci},
              sorted(segs))
        check("符号 gid 仍只有一个（点还是同一组）", ("cv%d-mk" % ci) in g2)
        code, u = post("/api/undo", {"figure": TMP_FIG, "fast": True})
        check("撤销后回到 1 段", (u.get("segments") or {}).get(curve) == 1,
              (u.get("segments") or {}).get(curve))

        # ---- [3] 三种画法下的 gid
        print("\n[3] 换画法时 gid 的存废要跟着走")
        post("/api/spec", {"figure": TMP_FIG, "patch": {"style": {"connect": "scatter"}},
                           "fast": True})
        code, sc = get("/api/figure?id=" + TMP_FIG)
        gs = gids(sc["svg"])
        check("散点模式：没有任何线的 gid", not [x for x in gs if "-line-" in x],
              [x for x in gs if "-line-" in x][:3])
        check("散点模式：符号 gid 还在（符号要能淡出）",
              len([x for x in gs if x.endswith("-mk")]) == len(cg))
        post("/api/spec", {"figure": TMP_FIG, "patch": {"style": {"connect": "smooth"}},
                           "fast": True})
        code, sm = get("/api/figure?id=" + TMP_FIG)
        gm = gids(sm["svg"])
        check("平滑模式：线 gid 仍然每条一个",
              sorted(x for x in gm if "-line-" in x) ==
              sorted("cv%d-line-0" % i for i in range(len(cg))), len(gm))
        post("/api/spec", {"figure": TMP_FIG,
                           "patch": {"style": {"connect": "segment"}}, "fast": True})

        # ---- [4] 页面控件
        print("\n[4] 页面上的锁定入口")
        code, html = get("/")
        html = html.decode("utf-8") if isinstance(html, bytes) else str(html)
        for key in ("boxCurve", "全部曲线", "function setAim(", "function paintAim(",
                    "function fillBoxCurves(", "curveGids", "aim:null",
                    "只框选", "已锁定"):
            check("页面含 %s" % key, key in html)

        # ---- [5] 导出不受影响
        print("\n[5] gid 只是 SVG 元数据，PDF 自检照样要合格")
        code, ex = post("/api/export", {"figure": TMP_FIG})
        outdir = os.path.join(paths.OUTPUTS, TMP_FIG)
        with open(os.path.join(outdir, "export_report.json"), encoding="utf-8") as fh:
            rdoc = json.load(fh)
        check("导出状态合格", rdoc.get("status") == "合格", rdoc.get("failures"))
        with open(os.path.join(outdir, "points.json"), encoding="utf-8") as fh:
            pdoc = json.load(fh)
        check("points.json 仍可读且点数正确",
              pdoc.get("n_points") == len(fig["points"]), pdoc.get("n_points"))

        # ---- [6] 真实数据
        print("\n[6] 真实数据集与真实规格")
        check("eis_20261107/working.csv 未改", md5(paths.working(SRC_DS)) == real_a)
        if real_b != "-":
            check("photothermal_20261111/working.csv 未改",
                  md5(paths.working("photothermal_20261111")) == real_b)
        main_spec = load_spec("eis_main")
        check("实测主图规格仍是折线（没被测试带跑）",
              (main_spec.get("style") or {}).get("connect", "segment") == "segment",
              (main_spec.get("style") or {}).get("connect"))

    finally:
        srv.shutdown()
        teardown()

    print("\n" + "=" * 70)
    print("合计 %d 项：通过 %d，失败 %d" % (OK + FAIL, OK, FAIL))
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
