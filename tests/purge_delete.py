# -*- coding: utf-8 -*-
"""删除两种模式的回归：只移除 / 连源文件一起删掉。

全程在临时数据根里跑，不碰真实的 datasets/ 与 Desktop。
用法： python tests/purge_delete.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.dirname(HERE)
# 示例数据可能已经不在代码目录（数据根被指到别处、或安装后清理过示例），
# 所以先记下真实的 FIGLAB_DATA_ROOT，稍后把它也当作候选来源。
REAL_ROOT = os.environ.get("FIGLAB_DATA_ROOT", "").strip()

tmp = tempfile.mkdtemp(prefix="figlab-purge-")
os.environ["FIGLAB_DATA_ROOT"] = tmp          # 必须在 import figlab.paths 之前设
sys.path.insert(0, CODE_ROOT)

from figlab import paths                      # noqa: E402
from figlab.web import api                    # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))


def sample_dataset(name: str = "eis_20261107") -> str:
    """示例数据集可能在代码目录，也可能在真实数据根；都没有就返回空串。"""
    bases = [os.path.join(CODE_ROOT, "datasets")]
    if REAL_ROOT:
        bases.append(os.path.join(REAL_ROOT, "datasets"))
    for base in bases:
        p = os.path.join(base, name)
        if os.path.isdir(p):
            return p
    return ""


def sample_spec(name: str = "eis_wide.json") -> str:
    bases = [os.path.join(CODE_ROOT, "specs")]
    if REAL_ROOT:
        bases.append(os.path.join(REAL_ROOT, "specs"))
    for base in bases:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return ""


def seed(fig_id: str, export_dir: str, src_ds: str, src_spec: str) -> str:
    """把示例数据集与示例规格复制进临时根，返回规格路径。"""
    dst_ds = os.path.join(paths.DATASETS, "eis_20261107")
    if not os.path.isdir(dst_ds):
        shutil.copytree(src_ds, dst_ds)
    with open(src_spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    spec["id"] = fig_id
    spec["export"]["dir"] = export_dir
    os.makedirs(paths.SPECS, exist_ok=True)
    p = os.path.join(paths.SPECS, fig_id + ".json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=1)
    # 规格里导出目录指向哪就造一个，模拟「已经导出过」
    out = os.path.join(paths.ROOT, export_dir)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "figure.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4 stub\n" * 512)
    return p


def exists(*parts: str) -> bool:
    return os.path.exists(os.path.join(paths.ROOT, *parts))


def main() -> int:
    src_ds, src_spec = sample_dataset(), sample_spec()
    if not src_ds or not src_spec:
        print("SKIP 找不到示例数据（datasets/eis_20261107 或 specs/eis_wide.json）；"
              "清理过示例数据的安装可以不跑这一项。")
        return 0
    os.makedirs(paths.DATASETS, exist_ok=True)
    seed("t_shared", "outputs/t_shared", src_ds, src_spec)
    seed("t_solo", "outputs/t_solo", src_ds, src_spec)

    # 1) 两张图共用同一数据集：第一张按「只移除」处理，文件必须都还在。
    plan = api.delete_plan("t_shared")
    check("计划里认出共用数据集", plan.get("dataset_shared") == "eis_20261107",
          str(plan))
    check("共用时不给独占数据集", not plan.get("dataset"), str(plan))
    res = api.delete_figure("t_shared", purge=False)
    check("只移除：规格已删", not os.path.exists(os.path.join(paths.SPECS,
                                                             "t_shared.json")))
    check("只移除：数据集保留", exists("datasets", "eis_20261107", "working.csv"))
    check("只移除：导出件保留", exists("outputs", "t_shared", "figure.pdf"))
    check("只移除：报告未清源文件", (res.get("purged") is False), str(res)[:200])

    # 2) 第二张是最后一个引用者：purge 要把数据集和导出目录一起带走。
    plan = api.delete_plan("t_solo")
    check("独占时给出数据集", plan.get("dataset") == "eis_20261107", str(plan))
    res = api.delete_figure("t_solo", purge=True)
    freed = res.get("freed") or {}
    check("purge：导出目录已删", not exists("outputs", "t_solo"))
    check("purge：数据集已删", not exists("datasets", "eis_20261107"))
    check("purge：报出释放字节", (freed.get("bytes") or 0) > 0, str(freed))
    check("purge：报出删掉的数据集", "eis_20261107" in (freed.get("datasets") or []),
          str(freed))

    # 3) 不存在的 id 不能抛异常。
    res = api.delete_figure("t_missing", purge=True)
    check("删不存在的图不报错", res.get("ok") is True, str(res))

    bad = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(("  ok  " if ok else "  FAIL") + "  " + name + (
            "" if ok else "   " + detail[:200]))
    print("\n%d/%d 通过" % (len(checks) - len(bad), len(checks)))
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(rc)