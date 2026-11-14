# -*- coding: utf-8 -*-
"""交互层真实 HTTP 跑通：本机服务、服务端 SVG、改数据、改版式、多图页签。"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                                  # noqa: E402
from figlab.data.dataset import read_long                  # noqa: E402
from figlab.web.server import Handler, port_free           # noqa: E402

PORT = 8779
LINE = "=" * 66
SPEC_BACKUP = os.path.join(ROOT, "tmp_layer4_eis_main.json")


def req(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (PORT, path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=120) as f:
            raw = f.read()
            ctype = f.headers.get("Content-Type", "")
            return (200, json.loads(raw) if "application/json" in ctype else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return (e.code, json.loads(raw))
        except Exception:
            return (e.code, raw[:200])


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print(LINE)
    print("交互层 · 真实 HTTP 跑通（规范 §五 / §十）")
    print(LINE)

    try:
        # 主图规格留底：测试可能改到它，收尾一律按原字节还原
        with open(paths.spec_file("eis_main"), "rb") as fh:
            with open(SPEC_BACKUP, "wb") as out:
                out.write(fh.read())

        print("\n[1] 端口占用预检（缺陷清单第 3 条）")
        print("    127.0.0.1:8777 空闲=%s（旧 scifig 服务仍占用，符合预期）" % port_free(8777))
        print("    127.0.0.1:8778 空闲=%s（新平台端口）" % port_free(8778))
        print("    127.0.0.1:%d 空闲=%s（本测试已启动服务占用，预检函数应判为占用）" %
              (PORT, port_free(PORT)))

        code, html = req("GET", "/")
        print("\n[2] GET / → HTTP %d，HTML %d 字符；含左图右栏=%s，含服务端 SVG 容器=%s" %
              (code, len(html), b"hotlayer" in html if isinstance(html, bytes) else False,
               b"svgbox" in html if isinstance(html, bytes) else False))

        code, d = req("GET", "/api/figures")
        print("\n[3] 多图页签 GET /api/figures → %s" % [f["id"] for f in d["figures"]])

        code, d = req("GET", "/api/figure?id=eis_main")
        print("\n[4] GET /api/figure?id=eis_main")
        print("    HTTP %d；SVG %d 字符，含 <svg> = %s，<text> 真文字 = %s" %
              (code, len(d["svg"]), "<svg" in d["svg"], "<text" in d["svg"]))
        print("    热区点 = %d；生效坐标范围 = %s" %
              (len(d["points"]), d["effective_range"]))
        print("    标注压点 = %d" %
              sum(a["collides_with_points"] for a in d["annotations"]))

        q = urllib.parse.quote("ITO 1-1")
        code, tb = req("GET", "/api/table?figure=eis_main&curve=" + q)
        print("\n[5] 打开数据表 → %s 共 %d 行，参与 %d 行" %
              (tb["curve"], tb["n"], tb["n_included"]))

        code, d = req("POST", "/api/point", {
            "figure": "eis_main", "curve": "ITO 1-1", "point_index": 1,
            "action": "exclude", "reason": ""})
        print("\n[6] 排除不写理由 → HTTP %d，拦截=%s，消息=%s" %
              (code, code == 500, str(d.get("error", ""))[:70]))

        code, d = req("POST", "/api/point", {
            "figure": "eis_main", "curve": "ITO 1-1", "point_index": 1,
            "action": "exclude", "reason": "网页联动测试：接插件瞬态干扰"})
        print("\n[7] 带理由排除 → HTTP %d，导出=%s，核验=%s，四类比对=%s" %
              (code, d.get("export_status"), d.get("verify_status"), d.get("diff")))
        print("    核验通过 %d/%d 项" %
              (sum(d.get("verify_checks", {}).values()), len(d.get("verify_checks", {}))))

        code, d = req("POST", "/api/point", {
            "figure": "eis_main", "curve": "ITO 1-1", "point_index": 1,
            "action": "restore", "reason": "网页联动测试：复核后恢复"})
        print("\n[8] 恢复 → 四类比对=%s，核验=%s" %
              (d.get("diff"), d.get("verify_status")))

        code, d = req("POST", "/api/spec", {
            "figure": "eis_main", "patch": {"style": {"tick_pt": 10.0}}})
        print("\n[9] 视图改刻度字号 → HTTP %d，导出=%s，核验=%s；覆盖项写入规格=%s" %
              (code, d.get("export_status"), d.get("verify_status"),
               "style" in d.get("spec", {}).get("overrides", {}) if d.get("spec") else "见 specs/*.json"))
        code, d = req("POST", "/api/spec", {
            "figure": "eis_main", "patch": {"style": {"tick_pt": 9.0}}})

        code, d = req("POST", "/api/figure/add", {"id": "web_probe", "preset": "generic"})
        code2, f2 = req("GET", "/api/figures")
        print("\n[10] 增页签 → ok=%s，页签=%s" % (d.get("ok"), [f["id"] for f in f2["figures"]]))
        code, d = req("POST", "/api/figure/delete", {"id": "web_probe"})
        code3, f3 = req("GET", "/api/figures")
        print("     删页签 → 页签=%s" % [f["id"] for f in f3["figures"]])

        code, th = req("GET", "/api/thumbs?id=eis_main")
        code, rp = req("GET", "/api/reports?id=eis_main")
        vr = rp.get("verify_report.json", {})
        print("\n[11] 缩略图栏=%s；核验报告 status=%s，通过 %d/%d 项" %
              (th["files"], vr.get("status"),
               sum(vr.get("checks", {}).values()), len(vr.get("checks", {}))))

        # 收尾：把主图规格按测试开始前的**原始字节**写回。
        # 以前这里用 build_spec("eis_main", ...) 重建一份"干净"规格，等于把用户的
        # 定制（标注/平移/画法）全抹掉，还会因为 next_suffix 重新计数把图名从
        # 「20261107阻抗作图」漂成「20261107阻抗作图3」——测试不该改用户的图。
        with open(SPEC_BACKUP, "rb") as fh:
            orig = fh.read()
        with open(paths.spec_file("eis_main"), "wb") as fh:
            fh.write(orig)
        code, d = req("POST", "/api/export", {"figure": "eis_main"})
        print("\n[12] 收尾：主图规格按测试前原字节还原（不改用户定制/图名），重新导出=%s，核验=%s，点=%d" %
              (d.get("export_status"), d.get("verify_status"), d.get("n_points")))

        # 收尾：本测试的排除/恢复会在 note 里留下测试理由，清回原始快照备注，
        # 避免污染交付数据（清理也走事务，台账留痕、可撤销）。
        from figlab.data.workbook import apply_ops
        raw = {(r["curve"], str(r["point_index"])): r
               for r in read_long(paths.raw_long("eis_20261107"), "eis")}
        ops = []
        for r in read_long(paths.working("eis_20261107"), "eis"):
            k = (r["curve"], str(r["point_index"]))
            if r.get("note", "") != raw[k].get("note", ""):
                ops.append({"op": "note", "curve": k[0], "point_index": k[1],
                            "note": raw[k].get("note", "")})
        if ops:
            apply_ops("eis_20261107", "eis", ops,
                      "交互层测试收尾：清除测试备注", "测试收尾")
        same = (open(paths.raw_long("eis_20261107"), "rb").read()
                == open(paths.working("eis_20261107"), "rb").read())
        print("\n[13] 收尾：工作副本与原始快照逐字节相同=%s（清除 %d 条测试备注）"
              % (same, len(ops)))

        print("\n" + LINE + "\n交互层：跑通\n" + LINE)
    finally:
        srv.shutdown()
        srv.server_close()
        if os.path.isfile(SPEC_BACKUP):
            os.remove(SPEC_BACKUP)


if __name__ == "__main__":
    main()
