# -*- coding: utf-8 -*-
"""一条命令：新数据进站 → 建图 → 导出 PDF（桌面同名文件夹）。

用户 2026-11-14 的要求：「后面作图时自动就是这个平台」。所以这个脚本是
**默认出图入口**，不要把数据拿去另写 matplotlib 脚本。

用法：
    # 1) 一包仪器导出文件（目录里有 csv/bin/txt）
    python scripts/new_figure.py "D:/数据/20261201阻抗" --kind eis

    # 2) 已经进站过的数据集，直接按默认模板再出一张图
    python scripts/new_figure.py eis_20261107 --kind eis

    # 3) 只看会做什么，不动磁盘
    python scripts/new_figure.py "D:/数据/20261201阻抗" --dry-run

参数：
    --id       指定数据集 ID（默认从路径里的 8 位日期推：<类别>_<日期>）
    --kind     eis | photothermal（默认 eis）
    --preset   inhouse | generic | dark_outline（默认 inhouse）
    --fig      图 ID（默认同数据集 ID）
    --force    已存在原始快照时重摄取（会覆盖 raw_long，谨慎）
    --no-export  只建图、不导出（调试用）
    --dry-run  只打印计划

出来的东西：
    规格  specs/<图ID>.json
    成品  桌面/FigLab/<数据日期><类别>作图/<同名>.pdf
    报告  outputs/<图ID>/verify_report.json
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                                  # noqa: E402
from figlab.data import SPECTRUM_COLUMNS                   # noqa: E402
from figlab.data.dataset import Dataset, read_long         # noqa: E402
from figlab.spec.merge import build_spec, save_spec        # noqa: E402

def guess_id(kind: str, src: str) -> str:
    """数据集 ID = <类别>_<8位日期>；日期取路径里出现的那个（数据自身日期）。"""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", os.path.basename(os.path.normpath(src)))
    if not m:
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", src)
    day = "".join(m.groups()) if m else date.today().strftime("%Y%m%d")
    return "%s_%s" % (kind, day)


def curves_of(ds_name: str, kind: str) -> list[str]:
    """按工作副本里的出现顺序取曲线名（不重排，颜色顺序就按这个来）。"""
    out: list[str] = []
    for r in read_long(paths.working(ds_name), kind):
        c = str(r.get("curve") or "").strip()
        if c and c not in out:
            out.append(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="新数据一键进站出图")
    ap.add_argument("src", help="数据目录，或已存在的数据集 ID")
    ap.add_argument("--kind", default="eis", choices=sorted(SPECTRUM_COLUMNS))
    ap.add_argument("--id", default="")
    ap.add_argument("--preset", default="inhouse")
    ap.add_argument("--fig", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    # ---- 是「已有数据集 ID」还是「一包新数据」
    as_dataset = os.path.isdir(paths.dataset_dir(a.src)) and not os.path.isdir(a.src)
    if as_dataset:
        ds_name = a.src
        if not os.path.isfile(paths.working(ds_name)):
            print("数据集目录在，但没有工作副本：%s" % paths.working(ds_name))
            return 2
        print("[1] 复用已进站数据集：%s" % ds_name)
    else:
        if not os.path.isdir(a.src):
            print("找不到这个目录：%s" % a.src)
            return 2
        ds_name = a.id or guess_id(a.kind, a.src)
        snapshot = paths.raw_long(ds_name)
        if os.path.isfile(snapshot) and not a.force:
            print("数据集 %s 已有原始快照（写入后只读）。" % ds_name)
            print("  想重摄取加 --force；想换名字加 --id <新ID>")
            return 2
        print("[1] 新数据集：%s（源：%s）" % (ds_name, a.src))
        if a.dry_run:
            print("    （dry-run）会执行 ingest → raw_long.csv / working.csv / ledger.json")
        else:
            total = Dataset(ds_name, a.kind).ingest(
                a.src, force=a.force, reason="命令行一键进站（scripts/new_figure.py）")
            print("    摄取完成：曲线 %s 条，点 %s 个"
                  % (total.get("curves"), total.get("points")))

    fig_id = a.fig or ds_name
    if os.path.isfile(paths.spec_file(fig_id)):
        print("图 ID %r 已存在（specs/%s.json）。换一个：--fig %s_2"
              % (fig_id, fig_id, fig_id))
        return 2

    # 谱型必须有处理层才能画：只有数据层（列定义）还不够
    try:
        from figlab.process.base import get_processor
        get_processor(a.kind)
    except NotImplementedError as e:
        print("这个谱型还不能出图：%s" % e)
        print("  数据已经进站（可以看表），但要画图得先在 figlab/process/ 里加处理器，")
        print("  并在 render/engine.py 的取点处认识它的列。目前只有 eis 能出图。")
        return 3

    curves = curves_of(ds_name, a.kind)
    if not curves:
        print("工作副本里没有曲线：%s" % paths.working(ds_name))
        return 2
    print("[2] 曲线 %d 条：%s" % (len(curves), "、".join(curves)))

    spec = build_spec(fig_id, ds_name, curves, preset=a.preset, spectrum=a.kind)
    print("[3] 规格：preset=%s，画布 %.1f×%.1f cm，导出 %s"
          % (a.preset, spec["page"]["w_cm"], spec["page"]["h_cm"],
             "/".join(spec["export"]["formats"])))
    print("    成品名：%s（数据日期 %s，之后不再改）"
          % (spec["export"]["base"], spec["export"].get("name_date")))

    if a.dry_run:
        print("\n（dry-run）到此为止，什么都没写。")
        return 0

    save_spec(spec)
    print("[4] 已写规格：specs/%s.json" % fig_id)

    if a.no_export:
        print("\n完成（--no-export）：在 http://127.0.0.1:8778 里打开这张图继续调。")
        return 0

    from figlab.web import api
    res = api.re_render(fig_id, full=True, deliver=True)
    if not res.get("ok"):
        print("导出失败：%s" % res.get("error") or res.get("problems"))
        return 1
    hand = res.get("handoff") or {}
    print("[5] 导出目录：%s" % res.get("output_dir"))
    print("    成品文件夹：%s" % (hand.get("dir") or res.get("figure_dir")))
    v = res.get("verify") or {}
    if v:
        print("    核验：%s（%s 项）" % (v.get("status", "?"), len(v.get("items") or [])))
    print("\n打开 http://127.0.0.1:8778 可以继续在图上改数据、调样式。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
