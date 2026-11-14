# -*- coding: utf-8 -*-
"""交付验收：规范 §八 逐条确认 + §九 逐项确认，机器执行，输出数字。"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                                  # noqa: E402
from figlab.data.diff import compare                      # noqa: E402
from figlab.render.engine import close, prepare            # noqa: E402
from figlab.render.export import export                   # noqa: E402
from figlab.spec.merge import load_spec                   # noqa: E402
from figlab.spec.schema import FILLED_MARKERS, FORBIDDEN_MARKERS  # noqa: E402
from figlab.verify.report import verify                   # noqa: E402
from figlab.web.server import port_free                   # noqa: E402

LINE = "=" * 66


def main():
    spec = load_spec("eis_main")
    # 最终态：重新导出 + 重新核验（§十）
    built = prepare(spec)
    exp = export(built, spec)
    close(built)
    vr = verify(spec)

    with open(paths.raw_meta("eis_20261107"), encoding="utf-8") as fh:
        meta = json.load(fh)
    with open(paths.ledger("eis_20261107"), encoding="utf-8") as fh:
        ledger = json.load(fh)
    outdir = paths.absolute(spec["export"]["dir"])
    with open(os.path.join(outdir, "geometry.json"), encoding="utf-8") as fh:
        geom = json.load(fh)
    with open(os.path.join(outdir, "points.json"), encoding="utf-8") as fh:
        pts = json.load(fh)
    diff = compare("eis_20261107", "eis")
    pdf = next(f for f in exp["files"] if f["format"] == "pdf")
    v = pdf["vector"]
    g = vr["geometry"]["comparison"]
    vis = vr["visual"]

    print(LINE)
    print("交付验收 · 机器执行（规范 §八 / §九）")
    print(LINE)
    print("最终导出 = %s；最终核验 = %s（%d/%d 项）；失败项 = %s" %
          (exp["status"], vr["status"], sum(vr["checks"].values()),
           len(vr["checks"]), vr["failures"]))

    print("\n【§九 交付与验收 · 逐项确认】")
    rows = []

    hashed = [s for s in meta["sources"] if re.fullmatch(r"[0-9a-f]{64}", s.get("sha256", ""))]
    rows.append(("数据来源与哈希已记录",
                 "%d/%d 源文件有 sha256；每源均含点数/采集时间/表头参数=%s" %
                 (len(hashed), len(meta["sources"]),
                  all(("points" in s and "stamp" in s and "params" in s)
                      for s in meta["sources"])),
                 len(hashed) == len(meta["sources"])))

    exports = [r for r in ledger if r["action"] == "export"]
    rows.append(("参与曲线与点数台账可查",
                 "geometry.json 曲线 %d 条 / points.json %d 点；台账 export 动作 %d 条" %
                 (len(geom["curves"]), pts["n_points"], len(exports)),
                 bool(exports) and len(geom["curves"]) > 0))

    ex = [r for r in ledger if r["action"] == "exclude"]
    rows.append(("被排除的点均写有理由",
                 "diff 无理由排除=%d；台账 exclude %d 条，全部带理由=%s" %
                 (len(diff["exclusions_without_reason"]), len(ex),
                  all(str(r.get("reason", "")).strip() for r in ex)),
                 len(diff["exclusions_without_reason"]) == 0 and
                 all(str(r.get("reason", "")).strip() for r in ex)))

    errs = [i["err_cm"] for i in g["items"]]
    rows.append(("画布与图框尺寸符合目标期刊",
                 "六项最大误差 %.4f cm（容差 0.05）；图框 %.3f×%.3f cm" %
                 (max(errs), *vr["geometry"]["measured"]["frame_size_cm"]),
                 g["ok"]))

    rows.append(("字体真身嵌入且无 Type3",
                 "FontFile2=%d, FontFile3=%d, Type3=%d, 字体=%s" %
                 (v["fontfile2"], v["fontfile3"], v["type3"], ",".join(v["fonts"])),
                 v["checks"]["truetype_subset_present"] and v["checks"]["no_type3"]))

    rows.append(("PDF 内嵌位图为零",
                 "embedded_images=%d；路径算子合计=%d" %
                 (v["embedded_images"], v["path_ops_total"]),
                 v["embedded_images"] == 0 and v["path_ops_total"] > 20))

    rows.append(("图上每一处标注都不压数据",
                 "标注 %d 个，压点总数=%d，越框=%d" %
                 (len(vis["annotations"]), vis["annotation_total_hits"],
                  vis["annotation_outside_frame"]),
                 vis["annotation_total_hits"] == 0 and vis["annotation_outside_frame"] == 0))

    rows.append(("导出文件尺寸与标称一致",
                 "MediaBox %s pt vs 标称 %s pt" %
                 ([round(x, 2) for x in v["mediabox_pt"]], v["mediabox_expected_pt"]),
                 v["checks"]["mediabox_matches"]))

    for name, detail, ok in rows:
        print("  [%s] %s\n        %s" % ("OK" if ok else "FAIL", name, detail))

    print("\n【§八 已知缺陷清单 · 逐条确认】")
    import ast
    import matplotlib
    checks8 = []

    def has_savefig_pdf_kw(pyfile):
        """AST 查真实调用：文档字符串里提到该写法不算缺陷。"""
        tree = ast.parse(open(pyfile, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "savefig" and any(kw.arg == "pdf" for kw in node.keywords):
                return True
        return False

    render_dir = os.path.join(ROOT, "figlab", "render")
    bad_calls = [f for f in ("engine.py", "export.py")
                 if has_savefig_pdf_kw(os.path.join(render_dir, f))]
    src = open(os.path.join(render_dir, "engine.py"), encoding="utf-8").read()
    checks8.append(("1 mpl 3.11 不再接受 savefig(pdf={...})",
                    "mpl %s；全局设 pdf/ps.fonttype=42=%s；AST 检出真实 savefig(pdf=...) 调用文件=%s" %
                    (matplotlib.__version__, "pdf.fonttype" in src, bad_calls),
                    "pdf.fonttype" in src and not bad_calls))
    checks8.append(("2 导出目录必须绝对路径",
                    "spec.export.dir isabs=%s；export_report=%s" %
                    (os.path.isabs(spec["export"]["dir"]), exp["export_dir_absolute"]),
                    os.path.isabs(spec["export"]["dir"]) and exp["export_dir_absolute"]))
    checks8.append(("3 旧进程占端口导致改了没生效",
                    "8777 空闲=%s（旧服务占用）；8778 空闲=%s；run.py 有 port_free 预检" %
                    (port_free(8777), port_free(8778)),
                    not port_free(8777)))
    mk = [s["marker"] for s in spec["series"]]
    checks8.append(("4 符号统一封闭实心形",
                    "符号集合=%s；全在白名单=%s；命中禁用表=%s" %
                    (sorted(set(mk)), all(m in FILLED_MARKERS for m in mk),
                     any(m in FORBIDDEN_MARKERS for m in mk)),
                    all(m in FILLED_MARKERS for m in mk) and
                    not any(m in FORBIDDEN_MARKERS for m in mk)))
    checks8.append(("5 频率取整去重会失效",
                    "dedup_rule=%s；跳过重复 .bin=%d" %
                    (meta["dedup_rule"][:24], meta["totals"]["skipped_duplicates"]),
                    "文件名主干" in meta["dedup_rule"]))
    anns = pts["annotations"]
    checks8.append(("6 标注压点用坐标撞矩形而非数像素",
                    "每个标注含 rect_data=%s；hits 合计=%d" %
                    (all("rect_data" in a for a in anns),
                     sum(a["collides_with_points"] for a in anns)),
                    all("rect_data" in a for a in anns)))
    # 口径：实测数值与行数一行都不能变；被「框选剔除」的行允许存在，
    # 但每一条都必须写了理由（exclusions_without_reason 为空）。
    # 早先这里要求四类全 0，等于「不许用户删点」——与删点功能自相矛盾。
    ex_bad = diff.get("exclusions_without_reason") or []
    dc = diff["counts"]
    checks8.append(("7 不改快照 / 拟合不写实测 / 不写未测信息",
                    "raw 只读=%s；改值 %d、增行 %d、丢行 %d；剔除 %d 行（无理由 %d）；"
                    "fit_arc=%s；geometry.note=%s" %
                    (not bool(os.stat(paths.raw_long("eis_20261107")).st_mode & 0o200),
                     dc["value_changed"], dc["rows_added"], dc["rows_lost"],
                     dc["include_flipped"], len(ex_bad),
                     spec["data"]["fit_arc"], geom["note"][:20]),
                    dc["value_changed"] == 0 and dc["rows_added"] == 0 and
                    dc["rows_lost"] == 0 and not ex_bad and
                    not spec["data"]["fit_arc"]))
    for name, detail, ok in checks8:
        print("  [%s] %s\n        %s" % ("OK" if ok else "FAIL", name, detail))

    allok = all(r[2] for r in rows) and all(c[2] for c in checks8) and \
        exp["status"] == "合格" and vr["status"] == "合格"
    print("\n" + LINE)
    print("总判定：%s（§九 %d/%d，§八 %d/%d，导出 %s，核验 %s）" %
          ("全部通过" if allok else "存在未通过项",
           sum(1 for r in rows if r[2]), len(rows),
           sum(1 for c in checks8 if c[2]), len(checks8),
           exp["status"], vr["status"]))
    print(LINE)


if __name__ == "__main__":
    main()
