# -*- coding: utf-8 -*-
"""第八层：项目管理器 + 一键出 PPT（用户 2026-11-13 第二轮要求）。

隔离原则同第七层：真正的写操作只碰临时规格 _selftest8 与临时归档目录，
真实数据集 eis_20261107 全程只读，测完把临时文件全部清掉。

验收口径：
  1 项目管理器：文件夹可建可改可删；删文件夹时图退回、不丢；图可改名、可换夹；
  2 需求单后端（界面已按第三轮要求移除，只留模块与命令行）：能提交/改状态/拒非法；
  3 出 PPT：16:9 单页、图按版面等比放大、图片名 figlab:<图ID>、图片上挂回链；
     追加模式在末尾加一页而不是覆盖；目标不存在时如实报错；
  4 页面：左栏项目树、出 PPT、移线按钮在；需求单控件必须不存在。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths, project, tasks                       # noqa: E402
from figlab.data.diff import compare                           # noqa: E402
from figlab.spec.merge import load_spec                        # noqa: E402
from figlab import pptx_out                                    # noqa: E402

BASE = "http://127.0.0.1:8778"
SRC_FIG = "eis_wide"
TMP_FIG = "_selftest8"
TMP_OUT = os.path.join(paths.OUTPUTS, TMP_FIG)
TMP_ARC = os.path.join(ROOT, "tmp_test_archive8")
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _rmtree(p):
    def onerr(func, path, exc):
        try:
            os.chmod(path, 0o700)
            func(path)
        except Exception:
            pass
    if os.path.isdir(p):
        shutil.rmtree(p, onerror=onerr)


def cleanup():
    _rmtree(TMP_OUT)
    _rmtree(TMP_ARC)
    p = paths.spec_file(TMP_FIG)
    if os.path.isfile(p):
        os.remove(p)


print("=" * 80)
print("第八层：项目管理器 / 一键出 PPT / 需求单（仅后端）")
print("=" * 80)

cleanup()
before_diff = compare("eis_20261107", "eis")["counts"]
figs_before = [f["id"] for f in project.snapshot()["figures"]]
print("\n[0] 起点：项目里有 %d 个窗口，真实数据集改动计数 = %s"
      % (len(figs_before), json.dumps(before_diff, ensure_ascii=False)))

# ---------------------------------------------------------------- 1 项目管理器
print("\n[1] 项目管理器（文件夹 / 窗口 / 归类）")
n0 = len(project.snapshot()["folders"])
f1 = project.new_folder("阻抗组")
f2 = project.new_folder("阻抗组")          # 同名要自动区分，不能挤成两个同名夹
names = [f["name"] for f in project.snapshot()["folders"]]
check("新建文件夹", f1["ok"] and len(names) == n0 + 2, "、".join(names))
check("同名文件夹自动区分", names.count("阻抗组") == 1 and (f1["name"] != f2["name"]),
      "%s / %s" % (f1["name"], f2["name"]))

mv = project.move_figure(SRC_FIG, f1["id"])
snap = project.snapshot()
where = {f["id"]: f["folder"] for f in snap["figures"]}
check("图可以拖进文件夹", mv["ok"] and where[SRC_FIG] == f1["id"], str(where))

rn = project.rename_figure(SRC_FIG, "Nyquist 主图")
title = {f["id"]: f["title"] for f in project.snapshot()["figures"]}
check("窗口可改名", rn["ok"] and title[SRC_FIG] == "Nyquist 主图", title[SRC_FIG])

# 重绘一次不能把用户改的名字刷回去（这是最容易回归的地方）
spec = load_spec(SRC_FIG)
from figlab.spec.merge import save_spec                          # noqa: E402
save_spec(spec)
title2 = {f["id"]: f["title"] for f in project.snapshot()["figures"]}
check("保存规格不覆盖窗口名", title2[SRC_FIG] == "Nyquist 主图", title2[SRC_FIG])

tg = project.toggle_folder(f1["id"])
check("文件夹可折叠", tg["ok"] and tg["open"] is False, "open=%s" % tg["open"])
project.toggle_folder(f1["id"])

dl = project.delete_folder(f1["id"])
snap2 = project.snapshot()
check("删文件夹不删图（退回第一个）",
      dl["ok"] and dl["moved"] == 1 and
      len(snap2["figures"]) == len(figs_before) and
      {f["id"]: f["folder"] for f in snap2["figures"]}[SRC_FIG] == snap2["folders"][0]["id"],
      "退回 %d 张，图 %d 个" % (dl["moved"], len(snap2["figures"])))

bad = project.move_figure(SRC_FIG, "不存在的夹")
check("挪到不存在的文件夹会被拒", (not bad["ok"]) and "没有这个文件夹" in bad["error"],
      bad.get("error", ""))
project.rename_figure(SRC_FIG, SRC_FIG)          # 还原显示名
project.delete_folder(f2["id"])
snap3 = project.snapshot()
check("一轮折腾后文件夹仍是展开的（不然树里就空了）",
      all(f["open"] for f in snap3["folders"]),
      str([(f["name"], f["open"]) for f in snap3["folders"]]))
check("所有窗口仍挂在一个存在且展开的文件夹下",
      all(any(f["id"] == fig["folder"] and f["open"] for f in snap3["folders"])
          for fig in snap3["figures"]),
      "%d 个窗口" % len(snap3["figures"]))

# ---------------------------------------------------------------- 2 需求单
print("\n[2] 需求单（说一句 → AI 去做）")
r1 = tasks.add(SRC_FIG, "8 条曲线按 Rs 从大到小排，颜色换成冷色")
check("提交需求拿到编号", r1["ok"] and r1["request"]["id"].count("-") == 2,
      r1["request"]["id"] if r1["ok"] else str(r1))
check("新需求是待处理", r1["request"]["status"] == "pending")
lst = tasks.listing(SRC_FIG)
check("列表里能查到", any(x["id"] == r1["request"]["id"] for x in lst["requests"]),
      "待处理 %d 条" % lst["pending"])
u1 = tasks.update(r1["request"]["id"], "done", "已按 Rs 降序重排，配色改为冷色系，标注未动")
check("能标成已完成并写回摘要", u1["ok"] and u1["request"]["status"] == "done"
      and "冷色" in u1["request"]["reply"], u1["request"]["reply"][:24])
u2 = tasks.update(r1["request"]["id"], "乱写", "")
check("非法状态被拒", (not u2["ok"]) and "状态只能" in u2["error"], u2.get("error", ""))
empty = tasks.add(SRC_FIG, "   ")
check("空需求被拒", (not empty["ok"]), empty.get("error", ""))
tasks.drop(r1["request"]["id"])                  # 自测不留噪音在真实需求单里
check("自测需求已清掉", tasks.listing(SRC_FIG)["n"] == 0,
      "剩 %d 条" % tasks.listing(SRC_FIG)["n"])

# ---------------------------------------------------------------- 3 一键出 PPT
print("\n[3] 一键出 PPT（回链 / 追加 / 等比放大）")
src = load_spec(SRC_FIG)
tmp = json.loads(json.dumps(src))
tmp["id"] = TMP_FIG
tmp["export"].update({"dir": TMP_OUT, "base": "_selftest8作图",
                      "auto_name": False, "formats": ["pdf"],
                      # 成品根目录指到临时目录：测试不许往用户桌面写
                      "handoff_root": TMP_ARC, "archive_root": TMP_ARC})
with open(paths.spec_file(TMP_FIG), "w", encoding="utf-8") as fh:
    json.dump(tmp, fh, ensure_ascii=False, indent=2)

d = post(BASE + "/api/pptx", {"figure": TMP_FIG, "mode": "new",
                              "url": BASE + "/?fig=" + TMP_FIG,
                              "caption": "自测页", "subtitle": ""})
check("生成成功", d.get("ok") and os.path.isfile(d.get("path", "")),
      "%s KB" % round((d.get("bytes") or 0) / 1024))
ins = d.get("inspect") or {}
check("只有一页", ins.get("n") == 1, "n=%s" % ins.get("n"))
check("16:9 版面", abs(ins.get("slide_w_in", 0) - 13.333) < .01 and
      abs(ins.get("slide_h_in", 0) - 7.5) < .01,
      "%s×%s 英寸" % (ins.get("slide_w_in"), ins.get("slide_h_in")))
pic = (ins.get("slides") or [{}])[0].get("pics") or [{}]
pic = pic[0]
check("图片名带图 ID（便于以后找回）", pic.get("name") == "figlab:" + TMP_FIG,
      str(pic.get("name")))
check("图片上有回链", pic.get("hyperlink") == BASE + "/?fig=" + TMP_FIG,
      str(pic.get("hyperlink")))
# 页面比例不同，贴边的那一边不一样：宽图顶满高度、方图顶满宽度，都算合格
fill = max(pic.get("w_in", 0) / 12.09, pic.get("h_in", 0) / 5.68)
check("图按版面等比放大到贴边（≥97%）", fill > 0.97,
      "%.2f×%.2f 英寸，占满 %.0f%%" % (pic.get("w_in", 0), pic.get("h_in", 0),
                                      fill * 100))
from PIL import Image                                            # noqa: E402
png = os.path.join(TMP_OUT, "_selftest8作图_ppt.png")
with Image.open(png) as im:
    iw, ih = im.size
check("内嵌位图 1200 dpi（宽 ≥ 3000 px）", iw >= 3000,
      "%d×%d px = %.0f dpi" % (iw, ih, iw / (src["page"]["w_cm"] / 2.54)))
ho = d.get("handoff") or {}
check("PPT 落进成品文件夹（与 PDF 同一处）",
      bool(ho.get("ok")) and os.path.isfile(ho.get("path", "")) and
      os.path.dirname(ho["path"]) == os.path.join(TMP_ARC, "_selftest8作图"),
      str(ho.get("path")))
check("页面脚注写了回链", "figlab" in ((ins.get("slides") or [{}])[0].get("notes") or ""),
      "备注含图 ID 与入口")

ap = post(BASE + "/api/pptx", {"figure": TMP_FIG, "mode": "append",
                               "path": d["path"], "url": BASE + "/?fig=" + TMP_FIG})
ins2 = ap.get("inspect") or {}
check("追加模式在末尾加一页", ap.get("ok") and ins2.get("n") == 2,
      "n=%s" % ins2.get("n"))
check("新页同样带图与回链",
      ((ins2.get("slides") or [{}, {}])[1].get("pics") or [{}])[0].get("hyperlink")
      == BASE + "/?fig=" + TMP_FIG)
nope = post(BASE + "/api/pptx", {"figure": TMP_FIG, "mode": "append",
                                 "path": os.path.join(TMP_OUT, "没有这份.pptx")})
check("目标不存在时如实报错", (not nope.get("ok")) and "找不到" in nope.get("error", ""),
      nope.get("error", ""))

# ---------------------------------------------------------------- 4 页面控件
print("\n[4] 页面控件")
with urllib.request.urlopen(BASE + "/", timeout=30) as r:
    html = r.read().decode("utf-8")
for key in ('id="proj"', 'id="projTree"', 'id="projNewFolder"', 'id="toggleProj"',
            'id="btnPptx"', 'id="btnPptxAppend"', 'id="pptTarget"', '项目管理器',
            'id="moveToggle"', 'id="layerToggle"'):
    check("页面含 %s" % key, key in html)
# 2026-11-13 第三轮：用户要求把「需求单」整个模块从界面拿掉，直接在对话里说
for key in ('id="reqText"', 'id="reqSend"', 'id="reqList"', 'id="reqTop"', 'id="reqSec"'):
    check("页面已无 %s" % key, key not in html)
check("表格支持整块选中与 Delete 删行",
      "extendCellSel" in html and "deleteSelectedRows" in html)
check("PPT 回链支持 ?fig= 直达",
      "qs.get('fig')" in html or 'get("fig")' in html)

# ---------------------------------------------------------------- 5 收尾
print("\n[5] 收尾：真实数据与项目不被测试改动")
after_diff = compare("eis_20261107", "eis")["counts"]
check("真实数据集四类比对未变", after_diff == before_diff,
      json.dumps(after_diff, ensure_ascii=False))
check("项目窗口数未变（临时图不进项目）",
      len(project.snapshot()["figures"]) == len(figs_before),
      "%d 个" % len(project.snapshot()["figures"]))
cleanup()
check("临时规格已删", not os.path.isfile(paths.spec_file(TMP_FIG)))
check("临时输出目录已删", not os.path.isdir(TMP_OUT))
check("临时成品目录已删", not os.path.isdir(TMP_ARC))

print("\n" + "=" * 80)
print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：" + "、".join(FAIL))
print("=" * 80)
sys.exit(1 if FAIL else 0)
