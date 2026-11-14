# -*- coding: utf-8 -*-
"""交互层 · Origin 式数据工作台真实 HTTP 跑通。

每项操作都走真实接口：改数据 → 自动重新导出 → 自动重新核验 → 数字回报。
收尾把工作副本恢复干净，保证后续层的验收基线不被测试污染。
"""
from __future__ import annotations

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

from figlab import paths                                   # noqa: E402
from figlab.data import workbook as W                      # noqa: E402
from figlab.web.server import Handler                      # noqa: E402

PORT = 8781
# 隔离原则：本层所有写操作都在临时数据集上做，绝不碰用户正在编辑的真实数据
# （旧版收尾会用原始快照覆盖 working.csv，那会把用户的人工改值与排除一起抹掉）
SRC_DS = "eis_20261107"
TMP_DS = "_selftest6"
TMP_FIG = "_selftest6"
FIG = TMP_FIG
N, S = TMP_DS, "eis"
LINE = "=" * 68
PASS, FAIL = [], []


def req(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (PORT, path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=180) as f:
            raw = f.read()
            return f.status, json.loads(raw) if "application/json" in f.headers.get("Content-Type", "") else raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:300]


def post(path, body):
    return req("POST", path, body)


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("    [%s] %s%s" % ("OK" if cond else "FAIL", name,
                             ("  → " + detail) if detail else ""))


def commit(ops, label):
    return post("/api/workbook", {"figure": FIG, "ops": ops, "label": label, "reason": label})


def undo():
    return post("/api/undo", {"figure": FIG})


def setup_isolated():
    """复制一份数据集与规格，测试全程只动副本。"""
    from figlab.spec.merge import load_spec
    _rmtree(paths.dataset_dir(TMP_DS))
    shutil.copytree(paths.dataset_dir(SRC_DS), paths.dataset_dir(TMP_DS))
    spec = load_spec("eis_main")
    spec["id"] = TMP_FIG
    spec["data"]["dataset"] = TMP_DS
    spec["data"]["working_csv"] = paths.working(TMP_DS)
    spec["export"].update({"dir": os.path.join(paths.OUTPUTS, TMP_FIG),
                           "base": TMP_FIG, "auto_name": False, "formats": ["pdf"],
                           # 归档写到仓库内临时目录，别往用户桌面上堆测试件
                           "archive_root": os.path.join(ROOT, "tmp_test_archive")})
    os.makedirs(spec["export"]["dir"], exist_ok=True)
    with open(paths.spec_file(TMP_FIG), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)


def _rmtree(p):
    def onerr(func, path, exc):
        try:
            os.chmod(path, 0o700)
            func(path)
        except Exception:
            pass
    if os.path.isdir(p):
        shutil.rmtree(p, onerror=onerr)


def teardown_isolated():
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


def main():
    setup_isolated()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(LINE)
    print("数据工作台 · 真实 HTTP 跑通（Origin 式改数据 / 规范 §一.7 / §十）")
    print(LINE)

    try:
        code, wb = req("GET", "/api/workbook?figure=" + FIG)
        c, i0 = wb["rows"][0]["curve"], wb["rows"][0]["point_index"]
        old = float(wb["rows"][0]["Zp_ohm"])
        print("\n[1] GET /api/workbook → HTTP %d；%d 行 / %d 列 / %d 条曲线；"
              "四类比对 %s；台账 %d 条" %
              (code, wb["n_rows"], len(wb["columns"]), len(wb["curves"]),
               wb["diff"], wb["n_ledger"]))
        print("    公式变量 %s；安全函数 %s" %
              (wb["formulas"]["variables"], wb["formulas"]["functions"]))
        check("工作台返回全部 7 列与公式白名单", len(wb["columns"]) == 7 and "sqrt" in wb["formulas"]["functions"])

        code, html = req("GET", "/")
        for key in ("数据表", "拖动数据点", "撤销", "重做", "sheetBox", "公式填充"):
            check("页面含控件 %s" % key, key.encode("utf-8") in html)

        print("\n[2] 单元格改值 + 撤销/重做（每次都自动重导出重核验）")
        code, d = commit([{"op": "cell", "curve": c, "point_index": i0,
                           "field": "Zp_ohm", "value": old + 7}], "测试：单元格改值")
        print("    HTTP %d；导出=%s 核验=%s（%d/%d）；diff=%s；svg=%d 字符；点=%d" %
              (code, d["export_status"], d["verify_status"],
               sum(d["verify_checks"].values()), len(d["verify_checks"]),
               d["diff"], len(d["svg"]), d["n_points"]))
        check("改值后 value_changed=1", d["diff"]["value_changed"] == 1)
        check("改值后导出与核验仍合格", d["export_status"] == "合格" and d["verify_status"] == "合格")
        check("返回工作台状态与撤销可用", d["workbook"]["undo"] is True)
        d = undo()[1]
        check("撤销后 diff 归零", d["diff"]["value_changed"] == 0)
        d = post("/api/redo", {"figure": FIG})[1]
        check("重做后 diff 恢复", d["diff"]["value_changed"] == 1)
        d = undo()[1]
        check("再撤销归零", d["diff"]["value_changed"] == 0)

        print("\n[3] 粘贴 Excel 的 TSV 块（2×3）")
        code, d = commit([{"op": "paste", "curve": c, "start_index": 1,
                           "start_field": "freq_Hz",
                           "matrix": [[99950, 21.11, -3.11], [79430, 22.22, -3.22]]}],
                         "测试：粘贴 2x3")
        print("    写入 %d 格；diff=%s；核验=%s" %
              (d["edit"]["changes"][0]["cells"], d["diff"], d["verify_status"]))
        check("粘贴 6 格生效", d["edit"]["changes"][0]["cells"] == 6)
        check("粘贴后 value_changed=2", d["diff"]["value_changed"] == 2)
        undo()

        print("\n[4] 公式填充（安全 AST，不允许任意代码）")
        code, d = commit([{"op": "formula", "curve": c, "indices": [1, 2, 3],
                           "field": "Zp_ohm", "expr": "x + 2*i"}], "测试：公式 x+2i")
        smp = d["edit"]["changes"][0]["sample"]
        print("    样本 原值→新值：%s；核验=%s" %
              ([[s[1], s[2]] for s in smp], d["verify_status"]))
        check("公式按行号 i 生效", abs(float(smp[0][2]) - float(smp[0][1]) - 2) < 1e-9 and
              abs(float(smp[2][2]) - float(smp[2][1]) - 6) < 1e-9)
        undo()
        code, bad = commit([{"op": "formula", "curve": c, "indices": [1],
                             "field": "Zp_ohm",
                             "expr": "__import__('os').system('echo hacked')"}],
                           "测试：公式注入")
        check("公式注入被拒绝（HTTP 500）", code == 500)
        check("注入失败后整批回滚", W.workbook(N, S)["diff"]["value_changed"] == 0)

        print("\n[5] 插入行 / 删除行（保持仪器点序稳定）")
        code, d = commit([{"op": "insert", "curve": c, "after": i0}], "测试：插入行")
        new_idx = d["edit"]["changes"][0]["new_point_index"]
        print("    新点序=%r；rows_added=%d；核验=%s" %
              (new_idx, d["diff"]["rows_added"], d["verify_status"]))
        check("插入行不改动原有整数点序", new_idx == "1.5" and d["diff"]["rows_added"] == 1)
        check("插入行不误报丢失行", d["diff"]["rows_lost"] == 0)
        undo()
        code, d = commit([{"op": "delete", "curve": c, "point_index": 2}], "测试：删除行")
        check("删除行报 rows_lost=1", d["diff"]["rows_lost"] == 1)
        undo()

        print("\n[6] 排除必须写理由；批量排除逐点记录")
        code, bad = commit([{"op": "include", "curve": c, "point_index": i0,
                             "include": False}], "测试：无理由排除")
        check("无理由排除被拦截（HTTP 500）", code == 500)
        check("整批回滚：diff 不变", W.workbook(N, S)["diff"]["include_flipped"] == 0)
        ops = [{"op": "include", "curve": c, "point_index": k, "include": False,
                "reason": "测试：高频接插件瞬态"} for k in (1, 2)]
        code, d = commit(ops, "测试：批量排除 2 点")
        tail = d["workbook"]["ledger_tail"]
        ex = [r for r in tail if r.get("action") == "exclude" and r.get("subtype") == "workbook_exclude"]
        print("    include_flipped=%d；台账 exclude 记录 %d 条，逐点理由 %d 条；核验=%s" %
              (d["diff"]["include_flipped"], len(ex),
               len(ex[0]["points"]) if ex else 0, d["verify_status"]))
        check("批量排除生效", d["diff"]["include_flipped"] == 2)
        check("台账逐点写理由", bool(ex) and len(ex[0]["points"]) == 2 and
              all(p["reason"] for p in ex[0]["points"]))
        check("无理由排除清单为空", d["workbook"]["exclusions_without_reason"] == [])
        undo()

        print("\n[7] 图上拖点的写回路径（改 Zpp_ohm）+ 保护性校验")
        code, d = commit([{"op": "cell", "curve": c, "point_index": i0,
                           "field": "Zpp_ohm", "value": -31.25}], "测试：图上拖点 Y 轴")
        print("    导出=%s 核验=%s（%d/%d）；points.json 同步=%s" %
              (d["export_status"], d["verify_status"],
               sum(d["verify_checks"].values()), len(d["verify_checks"]),
               len(d["points"]) == d["n_points"]))
        check("拖点写回后矢量核验仍合格", d["verify_status"] == "合格" and d["export_status"] == "合格")
        check("热区点数与绘制点数一致", len(d["points"]) == d["n_points"])
        undo()
        idxs = [r["point_index"] for r in wb["rows"] if r["curve"] == c]
        many = [{"op": "delete", "curve": c, "point_index": k} for k in idxs[:-3]]
        code, bad = commit(many, "测试：删到不足 4 点")
        check("剩余参与点 <4 被拒绝（保护弧顶判定）", code == 500,
              str(bad.get("error", ""))[:70])

        print("\n[8] 台账四类动作与最终干净状态")
        code, lg = req("GET", "/api/ledger?figure=" + FIG)
        print("    台账 %d 条；动作分布 %s" % (lg["n"], lg["counts"]))
        check("台账只含四类动作", set(lg["counts"]).issubset({"ingest", "modify", "exclude", "export"}))
        wb2 = W.workbook(N, S)
        check("最终四类比对全部归零", all(v == 0 for v in wb2["diff"].values()))
        check("最终无理由排除为 0", wb2["exclusions_without_reason"] == [])
        # 逐字段比对而不是逐字节：工作副本由台账写入器重排过，BOM/行序正常，
        # 只要七个字段完全一致就说明没有残留改动。
        from figlab.data.dataset import read_long
        raw_rows = read_long(paths.raw_long(N), S)
        wok_rows = read_long(paths.working(N), S)
        fields = ("curve", "point_index", "freq_Hz", "Zp_ohm", "Zpp_ohm",
                  "include", "note")
        same = (len(raw_rows) == len(wok_rows) and
                all(str(a.get(f, "")) == str(b.get(f, ""))
                    for a, b in zip(raw_rows, wok_rows) for f in fields))
        if not same:
            for n, (a, b) in enumerate(zip(raw_rows, wok_rows)):
                d = {f: (a.get(f), b.get(f)) for f in fields if str(a.get(f, "")) != str(b.get(f, ""))}
                if d:
                    print("    首个不一致 行%d %s: %s" % (n, (a.get("curve"), a.get("point_index")), d))
                    break
        check("工作副本七个字段与原始快照一致（raw/ 全程未写）", same,
              "%d 行 / %d 行" % (len(raw_rows), len(wok_rows)))
        print("    工作副本 %d 行（摄取时 %d 行）" % (wb2["n_rows"], wb["n_rows"]))

        print("\n" + LINE)
        print("工作台：PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
        if FAIL:
            print("未通过：" + "、".join(FAIL))
        print(LINE)
    finally:
        # 收尾只删临时副本；真实数据集全程没被写过，不需要任何「恢复」
        srv.shutdown()
        srv.server_close()
        teardown_isolated()
        print("[收尾] 临时数据集与规格已删除；真实数据集 %s 全程只读" % SRC_DS)


if __name__ == "__main__":
    main()
