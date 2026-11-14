# -*- coding: utf-8 -*-
"""第七层：桌面归档 + 原始/处理后双视图（用户新增需求）。

隔离原则：写操作只在临时数据集 _selftest 上做，绝不碰 datasets/eis_20261107，
因为用户可能正在网页上编辑那份数据。所有写测试结束后临时目录与规格一并删除。

验收口径（2026-11-14 起改为「成品交接」口径）：
  1 成品放 桌面\\FigLab\\<图名>\\，一个图一个文件夹，只放成品
    （PDF / EPS / SVG / PPT / .figlab）；报告 json 与 CSV 留在 outputs，不上桌面；
  2 只有手动导出（deliver=true）才写桌面；后台自动重渲染一个文件都不写；
  3 原始视图必须逐行标出工作副本改了什么，撤销后标记归零；
  4 页面必须同时具备 处理后/原始快照 切换、上下分隔条、可收起侧栏、成品路径显示。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                                   # noqa: E402
from figlab.data import workbook as W                      # noqa: E402
from figlab.data.diff import compare                       # noqa: E402
from figlab.spec.merge import load_spec                    # noqa: E402
from figlab.web import api                                 # noqa: E402

FIG = "eis_wide"
SRC_DS = "eis_20261107"
TMP_DS = "_selftest"
TMP_FIG = "_selftest"
BASE = "http://127.0.0.1:8778"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-44s %s" % ("PASS" if ok else "FAIL", name, detail))


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read().decode("utf-8"))


def _rmtree(p):
    """Windows 上 raw/ 是只读快照，直接 rmtree 会留下残骸；先解锁再删。"""
    def onerr(func, path, exc):
        try:
            os.chmod(path, 0o700)
            func(path)
        except Exception:
            pass
    if os.path.isdir(p):
        shutil.rmtree(p, onerror=onerr)


def cleanup():
    for p in (paths.dataset_dir(TMP_DS), os.path.join(paths.OUTPUTS, TMP_FIG)):
        _rmtree(p)
    for p in (paths.spec_file(TMP_FIG),
              os.path.join(paths.ROOT, "history", TMP_DS + ".json")):
        if os.path.isfile(p):
            os.remove(p)


print("=" * 80)
print("第七层：成品交付与原始/处理后双视图（隔离数据集 %s）" % TMP_DS)
print("=" * 80)

before = compare(SRC_DS, "eis")["counts"]
print("\n[0] 真实数据集当前状态（本层全程只读）")
print("    四类比对 = %s ｜ 无理由排除 %d 处"
      % (json.dumps(before, ensure_ascii=False),
         len(compare(SRC_DS, "eis")["exclusions_without_reason"])))

cleanup()
shutil.copytree(paths.dataset_dir(SRC_DS), paths.dataset_dir(TMP_DS))
spec = load_spec(FIG)
spec["id"] = TMP_FIG
spec["data"]["dataset"] = TMP_DS
spec["export"]["base"] = TMP_FIG
spec["export"]["auto_name"] = False          # 隔离测试用固定名，不跟日期走
spec["export"]["formats"] = ["pdf"]          # 默认只交付 PDF
spec["export"]["archive_root"] = os.path.join(ROOT, "tmp_test_archive")  # 不污染桌面
spec["export"]["handoff_root"] = os.path.join(ROOT, "tmp_test_archive")
spec["export"]["dir"] = os.path.join(paths.OUTPUTS, TMP_FIG)
# 故意不用 save_spec：它会把这个临时图注册进 figures.json，污染页签列表
with open(paths.spec_file(TMP_FIG), "w", encoding="utf-8") as fh:
    json.dump(spec, fh, ensure_ascii=False, indent=2)
print("    临时数据集 = %s（%d 行）" % (paths.dataset_dir(TMP_DS),
                                       len(W.workbook(TMP_DS, "eis")["rows"])))

# ---------------------------------------------------------------- 1 成品交付
print("\n[1] 成品交付：桌面\\FigLab\\<图名>\\，只放成品")
out = post(BASE + "/api/export", {"figure": TMP_FIG, "deliver": True})
h = out.get("handoff") or {}
print("    导出 %s ｜ 核验 %s ｜ 交付 %d 个 ｜ 文件夹 %s"
      % (out.get("export_status"), out.get("verify_status"),
         h.get("n", 0), h.get("dir", "")))
check("导出与核验都合格",
      out.get("export_status") == "合格" and out.get("verify_status") == "合格")
fdir = h.get("dir") or ""
check("成品根可指定（自测用临时目录）", os.path.isdir(fdir) and fdir.startswith(
    os.path.join(ROOT, "tmp_test_archive")), fdir)
check("文件夹名就是图名", os.path.basename(fdir) == TMP_FIG, os.path.basename(fdir))

files = sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []
check("有 PDF 成品", TMP_FIG + ".pdf" in files, "、".join(files))
check("同时存了 .figlab 项目文件", TMP_FIG + ".figlab" in files, "、".join(files))
check("没有报告 json / csv", not [f for f in files
                              if f.endswith((".json", ".csv"))], "、".join(files))
check("没有再套日期/类别子目录",
      not [f for f in files if os.path.isdir(os.path.join(fdir, f))], "、".join(files))
check("PNG 预览仍在 outputs 里（供缩略图与核验）",
      os.path.isfile(os.path.join(paths.OUTPUTS, TMP_FIG, TMP_FIG + ".png")))

# 勾选 SVG 后必须真的产出并交付，取消后不再出现
post(BASE + "/api/spec", {"figure": TMP_FIG,
                          "patch": {"export": {"formats": ["pdf", "svg"]}}})
out2 = post(BASE + "/api/export", {"figure": TMP_FIG, "deliver": True})
files2 = sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []
check("勾选 SVG 后成品里出现 svg", TMP_FIG + ".svg" in files2, "、".join(files2))
post(BASE + "/api/spec", {"figure": TMP_FIG,
                          "patch": {"export": {"formats": ["pdf"]}}})
out3 = post(BASE + "/api/export", {"figure": TMP_FIG, "deliver": True})
with urllib.request.urlopen(BASE + "/api/figure?id=" + TMP_FIG, timeout=30) as r:
    live = json.loads(r.read().decode("utf-8"))["spec"]
check("取消 SVG 后规格里只剩 pdf", live["export"]["formats"] == ["pdf"],
      str(live["export"]["formats"]))

# 自动导出（页面停手 1.2 s 自动补的那次）不许往桌面写
before_n = len(files2)
auto = post(BASE + "/api/export", {"figure": TMP_FIG, "spec": live, "deliver": False})
after_n = len(os.listdir(fdir)) if os.path.isdir(fdir) else 0
check("后台自动导出不写成品文件夹", not auto.get("handoff") and after_n <= before_n,
      "%d → %d" % (before_n, after_n))

# 报告与数据仍在 outputs 内部，桌面看不到
odir = os.path.join(paths.OUTPUTS, TMP_FIG)
for name in ("export_report.json", "verify_report.json", "points.json", "geometry.json"):
    check("报告留在 outputs：%s" % name, os.path.isfile(os.path.join(odir, name)))
check("桌面成品里没有报告类文件",
      not any(f.endswith(".json") for f in os.listdir(fdir)))

# ---------------------------------------------------------------- 2 双视图
print("\n[2] 原始快照 / 工作副本 双视图（在临时数据集上改值）")
rv = api.raw_view(TMP_FIG)
wb = api.get_workbook(TMP_FIG)
check("原始视图行数与工作副本一致", rv["n_rows"] == wb["n_rows"],
      "原始 %d 行 / 工作 %d 行" % (rv["n_rows"], wb["n_rows"]))
check("原始视图给出三个数值列",
      rv["numeric_columns"] == ["freq_Hz", "Zp_ohm", "Zpp_ohm"], str(rv["numeric_columns"]))
check("原始视图曲线数与工作副本一致", len(rv["curves"]) == len(wb["curves"]),
      "%d / %d" % (len(rv["curves"]), len(wb["curves"])))
check("初始状态原始视图无差异标记",
      sum(1 for r in rv["rows"] if r.get("_changed")) == 0)

target = rv["curves"][0]["curve"]
row0 = next(r for r in rv["rows"] if r["curve"] == target)
origin = float(row0["Zp_ohm"])
W.apply_ops(TMP_DS, "eis", [{"op": "cell", "curve": target,
                             "point_index": row0["point_index"],
                             "field": "Zp_ohm", "value": origin + 1.5}],
            "自测改值", "自测改值")
rv2 = api.raw_view(TMP_FIG)
hit = [r for r in rv2["rows"] if r.get("_changed")]
check("改值后原始视图出现差异标记", len(hit) == 1,
      "标记 %d 行：原始 %s → 当前 %s" %
      (len(hit), hit[0]["Zp_ohm"] if hit else "-",
       list(hit[0]["_changed"].values())[0] if hit else "-"))
check("差异只出现在被改字段",
      bool(hit) and list(hit[0]["_changed"].keys()) == ["Zp_ohm"],
      str(list(hit[0]["_changed"].keys())) if hit else "-")
check("原始视图保留的是原始值（不是工作值）",
      bool(hit) and abs(float(hit[0]["Zp_ohm"]) - origin) < 1e-9,
      "原始 %s ｜ 工作 %s" % (hit[0]["Zp_ohm"] if hit else "-",
                              list(hit[0]["_changed"].values())[0] if hit else "-"))

W.apply_ops(TMP_DS, "eis", [{"op": "include", "curve": target,
                             "point_index": row0["point_index"],
                             "include": False, "reason": "自测：接触不良"}],
            "自测排除", "自测排除")
rv3 = api.raw_view(TMP_FIG)
flip = [r for r in rv3["rows"] if r.get("_flip")]
check("排除后原始视图标出「现被排除」", len(flip) == 1,
      "原始参与 %s → 当前 %s" % (flip[0]["include"], flip[0]["_flip"]["to"]) if flip else "-")

W.undo(TMP_DS, "eis")
W.undo(TMP_DS, "eis")
rv4 = api.raw_view(TMP_FIG)
check("两次撤销后差异标记归零",
      sum(1 for r in rv4["rows"] if r.get("_changed") or r.get("_flip")) == 0,
      json.dumps(rv4["diff"], ensure_ascii=False))

# ---------------------------------------------------------------- 3 命名与图层
print("\n[3] 文件命名与图上图层（标注改名/拖动锁定、自由文字）")
from datetime import datetime as _dt                              # noqa: E402
from figlab.spec.merge import (data_date, default_base,           # noqa: E402
                               resolve_name, sanitize_base)

nb = default_base("eis_20261107", "eis", "")
check("默认文件名 = 数据日期+类别+作图", nb.endswith("阻抗作图") and nb[:8].isdigit(), nb)
check("命名日期取数据自身的日期，不是导出当天", nb[:8] == "20261107", nb)
check("data_date 认得数据集名里的日期", data_date("eis_20261107") == "20261107",
      data_date("eis_20261107"))
check("文件名清掉非法字符", "/" not in sanitize_base('a/b:c*?"<>|'), sanitize_base('a/b:c*?"<>|'))

auto = {"data": {"dataset": "eis_20261107", "spectrum": "eis"},
        "export": {"auto_name": True, "base": "旧名字", "name_suffix": ""}}
auto2, changed = resolve_name(auto, at=None)
check("auto_name 首次按数据日期定名", changed and auto2["export"]["base"] == nb,
      auto2["export"]["base"])
check("定名同时把数据日期冻进规格", auto2["export"].get("name_date") == "20261107",
      str(auto2["export"].get("name_date")))

# 用户的核心抱怨：同一个数据，隔天导出变成另一个名字/另一个文件夹
c1 = {"data": {"dataset": "eis_20261107", "spectrum": "eis"},
      "export": {"auto_name": True, "base": "x", "name_suffix": ""}}
c1, _ = resolve_name(c1, at=_dt(2026, 11, 13, 22, 14))
day1 = c1["export"]["base"]
c1, ch2 = resolve_name(c1, at=_dt(2026, 11, 14, 8, 56))
c1, ch3 = resolve_name(c1, at=_dt(2027, 3, 1, 9, 0))
check("同一份数据隔两天再导出，名字一个字都不变（不再一天一个新文件夹）",
      day1 == c1["export"]["base"] == "20261107阻抗作图" and not (ch2 or ch3),
      "%s -> %s" % (day1, c1["export"]["base"]))

fixed, changed2 = resolve_name({"data": {"dataset": "eis_20261107"},
                                "export": {"auto_name": False, "base": "我的图"}})
check("auto_name 关闭时不改名", (not changed2) and fixed["export"]["base"] == "我的图")

with urllib.request.urlopen(BASE + "/api/figure?id=" + TMP_FIG, timeout=30) as r:
    sp = json.loads(r.read().decode("utf-8"))["spec"]
series = json.loads(json.dumps(sp["series"]))
# 用第一条「参与绘制」的曲线：隐藏的曲线不会在图上产生标注
si = next(i for i, x in enumerate(series) if x.get("include", True))
series[si].update({"annot_text": "微藻1", "annot_locked": True,
                   "annot_dx_pt": 9.0, "annot_dy_pt": -10.0})
texts = [{"id": "t1", "text": "10 kHz", "nx": 0.62, "ny": 0.93,
          "size_pt": 8, "color": "#333333"}]
d = post(BASE + "/api/spec", {"figure": TMP_FIG, "patch": {"series": series, "texts": texts}})
an0 = next(a for a in d.get("annotations", []) if a["curve"] == series[si]["curve"])
check("标注可改名", an0["text"] == "微藻1", an0["text"])
check("标注可拖定位置并锁定", an0["locked"] and an0["dx_pt"] == 9.0 and an0["dy_pt"] == -10.0,
      "dx=%.1f dy=%.1f" % (an0["dx_pt"], an0["dy_pt"]))
check("自由文字写入成功", len(d.get("texts", [])) == 1, str(d.get("texts")))
check("中文文字能嵌进 PDF（无缺字告警即通过）", d.get("export_status") == "合格",
      "导出=%s 核验=%s" % (d.get("export_status"), d.get("verify_status")))
check("拖定标注没越框（核验仍合格）", d.get("verify_status") == "合格",
      "、".join(d.get("verify_failures") or []) or "无失败项")
reset = json.loads(json.dumps(sp["series"]))
d2 = post(BASE + "/api/spec", {"figure": TMP_FIG,
                               "patch": {"series": reset, "texts": []}})
check("标注可复位为自动避让（与初始锁定状态一致）",
      all(a["locked"] == {x["curve"]: bool(x.get("annot_locked"))
                         for x in sp["series"]}.get(a["curve"], False)
          for a in d2.get("annotations", [])) and not d2.get("texts"),
      "标注 %d 个 ｜ 初始锁定 %d 条" % (len(d2.get("annotations", [])),
                                sum(1 for x in sp["series"] if x.get("annot_locked"))))

# ---------------------------------------------------------------- 4 页面控件
print("\n[4] 页面控件")
with urllib.request.urlopen(BASE + "/", timeout=30) as r:
    html = r.read().decode("utf-8")
for key in ("原始快照", "处理后", 'id="splitter"', 'id="toggleSide"',
            'id="archiveBox"', "/api/raw", "/api/open-folder", "setRatio", "setSide",
            'id="layerToggle"', 'id="expName"', 'id="expAuto"', 'id="objList"',
            'id="addText"', 'id="applyAxis"'):
    check("页面含 %s" % key, key in html)
check("页面不再有只能二选一的 viewFigure/viewSheet",
      'id="viewFigure"' not in html and 'id="viewSheet"' not in html)

# ---------------------------------------------------------------- 5 收尾
print("\n[5] 收尾：真实数据集必须原样")
after = compare(SRC_DS, "eis")["counts"]
check("真实数据集四类比对未被本层改动", after == before,
      json.dumps(after, ensure_ascii=False))
cleanup()
cleanup()
_rmtree(os.path.join(ROOT, "tmp_test_archive"))
check("临时成品目录已清除", not os.path.isdir(os.path.join(ROOT, "tmp_test_archive")))
check("临时数据集已清除", not os.path.isdir(paths.dataset_dir(TMP_DS)))
check("临时规格已清除", not os.path.isfile(paths.spec_file(TMP_FIG)))

print("\n" + "=" * 80)
print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：" + "、".join(FAIL))
print("=" * 80)
sys.exit(0 if not FAIL else 1)
