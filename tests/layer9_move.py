# -*- coding: utf-8 -*-
"""第九层：整条曲线平移 + 快速渲染通道 + 需求单已从界面移除。

只读真实数据集 eis_wide，所有写操作都落在临时规格 `_selftest_move` 上，
跑完删掉，真实规格与真实导出目录一概不动。
"""
from __future__ import annotations

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths, project                      # noqa: E402
from figlab.render.engine import close, prepare        # noqa: E402
from figlab.spec.merge import load_spec, save_spec     # noqa: E402
from figlab.spec.schema import validate                # noqa: E402
from figlab.web import api                             # noqa: E402

OK = FAIL = 0
SRC = "eis_wide"
TMP = "_selftest_move"


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  [通过] %s%s" % (name, ("  " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        print("  [失败] %s%s" % (name, ("  " + str(detail)) if detail else ""))


def cleanup():
    p = paths.spec_file(TMP)
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass
    project.drop(TMP)


def main() -> int:
    cleanup()
    base = copy.deepcopy(load_spec(SRC))
    base["id"] = TMP
    base["export"]["auto_name"] = False
    base["export"]["base"] = "_selftest_move"
    base["export"]["dir"] = os.path.join(ROOT, "tmp_move_out")
    base["export"]["formats"] = ["pdf"]
    for s in base["series"]:
        s["off_x"] = 0.0
        s["off_y"] = 0.0
        s["annot_locked"] = False
        s["annot_text"] = s["letter"]
    os.makedirs(base["export"]["dir"], exist_ok=True)
    save_spec(base)

    try:
        first = [s for s in base["series"] if s.get("include")][0]["curve"]
        spec0 = load_spec(TMP)
        v = validate(spec0)
        check("带 off_x/off_y 的规格通过校验", v["ok"], "%d 项检查" % v["checks"])

        # --- 纯显示偏移：渲染出来的点整体平移，数据字段跟着交代原始值
        a = prepare(spec0)
        p0 = [p for p in a["points_norm"] if p["curve"] == first]
        close(a)
        spec1 = copy.deepcopy(spec0)
        for s in spec1["series"]:
            if s["curve"] == first:
                s["off_x"], s["off_y"] = 25.0, 40.0
        b = prepare(spec1)
        p1 = [p for p in b["points_norm"] if p["curve"] == first]
        close(b)
        dx = p1[0]["Zp_ohm"] - p0[0]["Zp_ohm"]
        dy = p1[0]["Zpp_neg_ohm"] - p0[0]["Zpp_neg_ohm"]
        check("图上的点按 Δ 平移", abs(dx - 25.0) < 1e-6 and abs(dy - 40.0) < 1e-6,
              "Δ=(%.3f, %.3f)" % (dx, dy))
        check("实测值字段未被平移污染",
              abs(p1[0]["Zp_data"] - p0[0]["Zp_ohm"]) < 1e-6
              and abs(p1[0]["Zpp_data"] - p0[0]["Zpp_ohm"]) < 1e-6,
              "Zp_data=%.3f  Zpp_data=%.3f" % (p1[0]["Zp_data"], p1[0]["Zpp_data"]))

        # --- 快速通道：只出 SVG，不写文件、不核验
        fast = api.re_render(TMP, full=False)
        check("fast 渲染返回 SVG 与点位", fast["ok"] and fast.get("fast") is True
              and len(fast["svg"]) > 2000 and len(fast["points"]) > 0,
              "%d 字节 / %d 点" % (len(fast["svg"]), len(fast["points"])))
        check("fast 不产生导出状态", fast.get("export_status") is None
              and fast.get("verify_status") is None)
        check("fast 不写 PDF", not os.path.isfile(
            os.path.join(base["export"]["dir"], "_selftest_move.pdf")))

        # --- 平移接口：小载荷、只动这一条、写回规格
        r = api.curve_shift(TMP, first, 12.5, -8.0)
        check("平移接口成功", r["ok"], "Δ=(%.2f, %.2f)" % (r.get("off_x", 0), r.get("off_y", 0)))
        cur = [s for s in load_spec(TMP)["series"] if s["curve"] == first][0]
        check("偏移写进规格", abs(cur["off_x"] - 12.5) < 1e-9
              and abs(cur["off_y"] + 8.0) < 1e-9,
              "(%.2f, %.2f)" % (cur["off_x"], cur["off_y"]))
        others = [s for s in load_spec(TMP)["series"] if s["curve"] != first]
        check("其它曲线没被带着动",
              all(abs(float(s.get("off_x", 0))) < 1e-12
                  and abs(float(s.get("off_y", 0))) < 1e-12 for s in others),
              "%d 条" % len(others))
        p2 = [p for p in r["points"] if p["curve"] == first]
        check("返回的点位就是平移后的",
              abs(p2[0]["Zp_data"] - p0[0]["Zp_ohm"]) < 1e-6, "Zp_data=%.3f" % p2[0]["Zp_data"])

        # --- 拖动时锁轴：范围只按实测值算，不会跟着平移跳刻度
        lock = api.re_render(TMP, full=False, lock_axis=True)
        sp = load_spec(TMP)
        for s in sp["series"]:
            if s["curve"] == first:
                s["off_x"], s["off_y"] = 30.0, 30.0
        a2 = prepare(sp, lock_axis=True)
        b2 = prepare(sp, lock_axis=False)
        r_lock, r_free = a2["limits"]["y"][:2], b2["limits"]["y"][:2]
        close(a2); close(b2)
        check("锁轴时范围不受平移影响", abs(r_lock[0] - lock["effective_range"]["y"][0]) < 1e-9
              and abs(r_lock[1] - lock["effective_range"]["y"][1]) < 1e-9,
              "锁轴 y=%s" % [round(x, 1) for x in r_lock])
        check("不锁轴时范围含平移", r_free != r_lock,
              "自由 y=%s vs 锁轴 y=%s" % ([round(x, 1) for x in r_free],
                                         [round(x, 1) for x in r_lock]))

        # --- 归零
        r0 = api.curve_shift(TMP, first, 0, 0)
        check("可一键归零", r0["ok"]
              and abs([s for s in load_spec(TMP)["series"]
                       if s["curve"] == first][0]["off_x"]) < 1e-12)
        check("不存在的曲线被拒", not api.curve_shift(TMP, "没有这条", 1, 1)["ok"])

        # --- 需求单已从服务端接口移除
        from figlab.web import server
        check("需求单 HTTP 接口已移除",
              not hasattr(api, "requests_view") and "/api/requests" not in
              (server.HEAVY_GET | server.HEAVY_POST))
        with open(os.path.join(ROOT, "figlab", "web", "ui.html"), encoding="utf-8") as fh:
            ui = fh.read()
        check("界面里不再有需求单区块", "reqSec" not in ui and "reqText" not in ui)
        check("界面里有移线按钮", "moveToggle" in ui and "curve-shift" in ui)
        check("表格支持整块选中与 Delete 删行",
              "extendCellSel" in ui and "deleteSelectedRows" in ui and "selcell" in ui)
    finally:
        cleanup()
        try:
            import shutil
            shutil.rmtree(os.path.join(ROOT, "tmp_move_out"), ignore_errors=True)
        except Exception:
            pass

    print("\n第九层：%d 通过 / %d 失败" % (OK, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
