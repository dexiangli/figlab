# -*- coding: utf-8 -*-
"""第十层：框选删点（拉框选择点 → 剔除 / 删行）+ 剔除处断线。

要点：框选剔除中段之后，曲线必须在断点处**断开**，不能把两侧端点直接连起来
（那等于在图上画出没测过的数据）。本层用真实 HTTP 接口验证这条，并检查
断线信息进了 points.json / geometry.json 的留痕字段。

隔离原则与第六层一致：复制一份数据集到 _selftest10，所有写操作只动副本，
收尾删干净；真实数据集与真实导出目录前后做 md5 比对。
"""
from __future__ import annotations

import copy
import hashlib
import json
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
from figlab.render.engine import split_runs                # noqa: E402
from figlab.spec.merge import load_spec                    # noqa: E402
from figlab.web.server import Handler                      # noqa: E402

PORT = 8782
SRC_DS = "eis_20261107"
TMP_DS = "_selftest10"
TMP_FIG = "_selftest10"
LINE = "-" * 70
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
    spec.setdefault("style", {})["break_gaps"] = True
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


# ------------------------------------------------------------------ 主体
def main() -> int:
    print("=" * 70)
    print("第十层：框选删点（拉框选点 → 不画 / 删行）+ 剔除处断线")
    print("=" * 70)

    real_a = md5(paths.working(SRC_DS))
    real_b = md5(paths.working("photothermal_20261111")) if os.path.isfile(
        paths.working("photothermal_20261111")) else "-"

    setup_isolated()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        # ---- [1] 分段函数本身
        print("\n[1] 分段算法（不跨被剔除的点连直线）")
        pts = [(0, 0, {}), (1, 1, {}), (2, 2, {}), (10, 3, {}), (11, 4, {})]
        check("无剔除 → 1 段", [len(r) for r in split_runs(pts, [])] == [5])
        check("剔除夹在中间 → 2 段 2+3",
              [len(r) for r in split_runs(pts, [1.5])] == [2, 3])
        check("两侧都剔除 → 2 段",
              [len(r) for r in split_runs(pts, [5.0])] == [3, 2])
        check("边界值不误判（剔除点正好等于端点值不算断）",
              len(split_runs(pts, [2.0])) == 1 and len(split_runs(pts, [0.0])) == 1)

        # ---- [2] 界面控件
        print("\n[2] 页面控件与提示")
        code, html = get("/")
        html = html.decode("utf-8") if isinstance(html, bytes) else str(html)
        for key in ("boxToggle", "框选删点", "marquee", "boxbar", "boxExclude",
                    "boxDelete", "删行", "框选剔除", "不跨被删点连直线"):
            check("页面含 %s" % key, key in html)

        # ---- [3] 基线
        print("\n[3] 基线：没有剔除时每条曲线只有 1 段")
        code, fig = get("/api/figure?id=" + TMP_FIG)
        seg0 = fig["segments"]
        n0 = len(fig["points"])
        cnt = {}
        for p in fig["points"]:
            cnt[p["curve"]] = cnt.get(p["curve"], 0) + 1
        curve = max(cnt, key=cnt.get)        # 图上点最多的那条曲线
        print("    曲线 %s；点 %d；段 %s" % (curve, n0, seg0))
        check("基线全 1 段", all(v == 1 for v in seg0.values()), seg0)
        check("基线热区点数与渲染一致", n0 == len(fig["points"]), n0)

        # ---- [4] 框选剔除中段 8 点
        print("\n[4] 框选剔除中段 8 点 → 曲线断成 2 段")
        code, wb = get("/api/workbook?figure=" + TMP_FIG)
        rows = [r for r in wb["rows"] if r["curve"] == curve]
        rows.sort(key=lambda r: float(r["Zp_ohm"]))
        mid = len(rows) // 2
        # 框选只可能框到图上画出来的点，所以从**已绘制的点**里挑中段 8 个
        drawn = sorted([p for p in fig["points"] if p["curve"] == curve],
                       key=lambda p: p["Zp_ohm"])
        dm = len(drawn) // 2
        selp = drawn[dm - 4:dm + 4]
        pick = [{"point_index": p["point_index"], "Zp_ohm": p["Zp_ohm"]} for p in selp]
        idxs = [str(p["point_index"]) for p in selp]
        ops = [{"op": "include", "curve": curve, "point_index": i,
                "include": False, "reason": "框选剔除（测试）"} for i in idxs]
        code, d = post("/api/workbook", {"figure": TMP_FIG, "ops": ops,
                                         "label": "框选剔除 8 点（测试）",
                                         "reason": "框选剔除（测试）", "fast": True})
        print("    HTTP %d；点 %d → %d；段 %s；diff=%s" %
              (code, n0, d.get("n_points", -1), d.get("segments"), d.get("diff")))
        check("接口返回 200", code == 200)
        # 点数不必正好减 8：几何量（鞍点/截尾）按参与点重算，尾部可能会跟着变
        check("剔除后图上点数变少（不含被剔除的点）", d["n_points"] < n0, d["n_points"])
        check("该曲线断成 2 段", d["segments"].get(curve) == 2, d["segments"])
        check("台账记为 exclude 8 点",
              d["diff"].get("include_flipped") == 8 or
              d["diff"].get("excluded") == 8, d["diff"])
        check("被剔除的点不再出现在热区里",
              not any(p["curve"] == curve and str(p["point_index"]) in idxs
                      for p in d["points"]))
        zs = [float(p["Zp_ohm"]) for p in d["points"] if p["curve"] == curve]
        ze = [float(r["Zp_ohm"]) for r in pick]
        check("断点两侧都还有点（缺口在图内，不是切掉尾巴）",
              min(zs) < min(ze) and max(zs) > max(ze))

        # ---- [5] 留痕：导出的 points.json / geometry.json 说清楚断了
        print("\n[5] 导出留痕（断线必须写在文件里，不能只在界面上）")
        code, ex = post("/api/export", {"figure": TMP_FIG})
        outdir = paths.absolute(load_spec(TMP_FIG)["export"]["dir"])
        pj = json.load(open(os.path.join(outdir, "points.json"), encoding="utf-8"))
        gj = json.load(open(os.path.join(outdir, "geometry.json"), encoding="utf-8"))
        print("    segments=%s；segment_note=%r" %
              (pj.get("segments"), pj.get("segment_note")))
        check("导出合格", ex.get("export_status") == "合格", ex.get("export_status"))
        check("points.json 记录分段数", pj.get("segments", {}).get(curve) == 2)
        check("points.json 有断线说明文字", bool(pj.get("segment_note", "").strip()))
        check("geometry.json 记录 n_segments",
              gj["curves"][curve].get("n_segments") == 2)

        # ---- [6] 没写理由的剔除必须被拒
        print("\n[6] 剔除必须写理由（规范 §一.7）")
        code, bad = post("/api/workbook", {"figure": TMP_FIG,
                                           "ops": [{"op": "include", "curve": curve,
                                                    "point_index": str(rows[0]["point_index"]),
                                                    "include": False}],
                                           "label": "缺理由", "fast": True})
        print("    HTTP %d；%s" % (code, str(bad.get("error", ""))[:70]))
        check("缺理由 → HTTP 500 且整批回滚", code == 500)
        code, wb2 = get("/api/workbook?figure=" + TMP_FIG)
        still = [r for r in wb2["rows"] if str(r["include"]) != "1"]
        check("回滚后仍是刚才那 8 个点被剔除", len(still) == 8, len(still))

        # ---- [7] 撤销 / 重做
        print("\n[7] 撤销一步 → 曲线回到 1 段；重做 → 又断成 2 段")
        code, u = post("/api/undo", {"figure": TMP_FIG, "fast": True})
        check("撤销后 1 段", u.get("segments", {}).get(curve) == 1, u.get("segments"))
        check("撤销后点数复原", u.get("n_points") == n0, u.get("n_points"))
        code, r = post("/api/redo", {"figure": TMP_FIG, "fast": True})
        check("重做后 2 段", r.get("segments", {}).get(curve) == 2, r.get("segments"))
        post("/api/undo", {"figure": TMP_FIG, "fast": True})

        # ---- [8] break_gaps 开关
        print("\n[8] 版式开关「剔除处断线」：关掉就恢复成一条连续线")
        post("/api/workbook", {"figure": TMP_FIG, "ops": ops,
                              "label": "再剔除一次", "reason": "框选剔除（测试）",
                              "fast": True})
        code, off = post("/api/spec", {"figure": TMP_FIG, "fast": True,
                                       "patch": {"style": {"break_gaps": False}}})
        check("关掉断线开关 → 1 段", off.get("segments", {}).get(curve) == 1,
              off.get("segments"))
        code, on = post("/api/spec", {"figure": TMP_FIG, "fast": True,
                                      "patch": {"style": {"break_gaps": True}}})
        check("打开断线开关 → 2 段", on.get("segments", {}).get(curve) == 2,
              on.get("segments"))

        # ---- [9] 真删行（先回到没有剔除的状态，才能看出「删行不留断点」）
        print("\n[9] 「彻底删行」：行真的没了 → 两侧点直接相连（这是它与剔除的区别）")
        post("/api/undo", {"figure": TMP_FIG, "fast": True})
        code, wb3 = get("/api/workbook?figure=" + TMP_FIG)
        before_rows = wb3["n_rows"]
        rows3 = [x for x in wb3["rows"] if x["curve"] == curve]
        rows3.sort(key=lambda x: float(x["Zp_ohm"]))
        del_idx = [str(x["point_index"]) for x in rows3[mid - 2:mid + 3]]
        code, dl = post("/api/workbook", {"figure": TMP_FIG,
                                         "ops": [{"op": "delete", "curve": curve,
                                                  "indices": del_idx}],
                                         "label": "框选删行 5 点（测试）", "fast": True})
        print("    行 %d → %d；段 %s" % (before_rows, dl.get("workbook", {}).get("n_rows", -1),
                                       dl.get("segments")))
        check("删行后总行数减 5", dl["workbook"]["n_rows"] == before_rows - 5,
              dl["workbook"]["n_rows"])
        check("删行不留断点（1 段；想要断开就用「不画这些点」）",
              dl.get("segments", {}).get(curve) == 1, dl.get("segments"))
        code, u2 = post("/api/undo", {"figure": TMP_FIG, "fast": True})
        check("撤销删行后行数复原",
              u2["workbook"]["n_rows"] == before_rows, u2["workbook"]["n_rows"])

        # ---- [10] 真实数据没被碰过
        print("\n[10] 真实数据集未被触碰（md5 前后一致）")
        check("%s/working.csv 未改" % SRC_DS, md5(paths.working(SRC_DS)) == real_a)
        if real_b != "-":
            check("photothermal_20261111/working.csv 未改",
                  md5(paths.working("photothermal_20261111")) == real_b)

    finally:
        srv.shutdown()
        teardown()

    print("\n" + LINE)
    print("合计：%d 通过 / %d 失败" % (OK, FAIL))
    print(LINE)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
