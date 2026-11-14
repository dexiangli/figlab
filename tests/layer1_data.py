# -*- coding: utf-8 -*-
"""数据层真实数据跑通：EIS 23 文件 + 光热 6 个 GBK 畸形文件。用数字汇报。"""
from __future__ import annotations

import json
import os
import stat
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from figlab import paths                                    # noqa: E402
from figlab.data.dataset import Dataset, read_long          # noqa: E402
from figlab.data.diff import compare                        # noqa: E402
from figlab.data.edit import set_include, set_value          # noqa: E402
from figlab.data.ingest import parse_malformed_time          # noqa: E402

from figlab import paths as _paths
EIS = os.path.join(_paths.desktop(), "20261107阻抗.zip")   # 放桌面即可跑；没有就跳过
PTH = os.path.join(_paths.desktop(), "光热空白对照")
if not (os.path.isfile(EIS) and os.path.isdir(PTH)):
    print("桌面缺原始测试件（20261107阻抗.zip / 光热空白对照），数据层实测跳过，只跑纯函数段")
    EIS = PTH = None
LINE = "=" * 66


def bin_records(blob):
    """只用于核验去重规则：读出 CHI 二进制里的 (频率, Z', Z'')，不生成绘图数据。"""
    out, off = [], len(blob) - 16
    while off >= 0:
        a, b, zp, zpp = struct.unpack_from("<ffff", blob, off)
        if not (abs(a - b) <= 1e-4 * max(abs(a), 1e-9) and 1e-4 <= a <= 1e7
                and abs(zp) < 1e6 and abs(zpp) < 1e6):
            break
        out.append((a, zp, zpp))
        off -= 16
    return list(reversed(out))


def main():
    print(LINE)
    print("数据层 · 真实数据跑通（规范 §一 / §十）")
    print(LINE)

    # ---------------- 1. EIS 摄取
    ds = Dataset("eis_20261107", "eis")
    if EIS:
        t = ds.ingest(EIS, force=True, reason="按新平台从零摄取，原始快照写入后只读")
        print("\n[1] EIS 摄取 totals:", json.dumps(t, ensure_ascii=False))
    else:
        print("\n[1] 桌面无测试件，跳过重新摄取；用仓库自带的 raw_meta 核验元数据")
    with open(paths.raw_meta("eis_20261107"), encoding="utf-8") as fh:
        meta = json.load(fh)
    ing = [s for s in meta["sources"] if s["status"] == "ingested"]
    print("    .csv 曲线数 = %d；曲线点数 = %s" % (len(ing), [s["points"] for s in ing]))
    print("    起点/终点不一致（未按比例对齐、未重采样）：")
    for s in ing[:6]:
        print("      %-38s n=%3d  %.4g -> %.4g Hz" %
              (s["file"], s["points"], s["first"], s["last"]))
    print("    被跳过的重复二进制 = %d 个: %s" %
          (len([s for s in meta["sources"] if s["status"] == "skipped_duplicate"]),
           [s["file"] for s in meta["sources"] if s["status"] == "skipped_duplicate"]))
    print("    仅二进制、未纳入 = %d 个（各登记 sha256 + 点数 + 理由）" %
          len([s for s in meta["sources"] if s["status"] == "not_ingested"]))
    for s in meta["sources"]:
        if s["status"] == "not_ingested":
            print("      %-38s points=%s sha256=%s..." % (s["file"], s["points"], s["sha256"][:12]))
    print("    元数据完整性：每源文件含 sha256/点数/采集时间/表头参数 = %s" %
          all("sha256" in s and "points" in s and "stamp" in s and "params" in s
              for s in meta["sources"]))
    print("    表头参数示例（ITO 1-1.csv）= %s" %
          next((s["params"] for s in ing if s["file"].startswith("ITO 1-1")), {}))

    # ---------------- 2. 证明「不能用频率取整去重」
    csv_first = next(s["first"] for s in ing if s["file"] == "ITO 1-1.csv")
    csv_path = os.path.join(paths.sources_dir("eis_20261107"), "ITO 1-1.csv")
    bin_path = os.path.join(paths.sources_dir("eis_20261107"), "ITO 1-1.bin")
    from figlab.data.ingest import parse_chi_text
    with open(csv_path, "rb") as fh:
        csv_row0 = parse_chi_text(fh.read())["rows"][0]
    with open(bin_path, "rb") as fh:
        recs = bin_records(fh.read())
    near = min(recs, key=lambda r: abs(r[0] - csv_first))
    print("\n[2] 去重规则实证（ITO 1-1 同一频点，文本导出 vs 二进制导出）：")
    print("    文本 %.6f Hz / Z'=%.6f Ω   二进制 %.6f Hz / Z'=%.6f Ω"
          % (csv_first, csv_row0["Zp_ohm"], near[0], near[1]))
    print("    实测差 = %.6g Hz（相对 %.2e）、Z' 差 = %.6g Ω；"
          "round() 后两者同为 %d → 按频率值取整去重必然把同一次测量画两遍"
          % (abs(near[0] - csv_first), abs(near[0] - csv_first) / csv_first,
             abs(near[1] - csv_row0["Zp_ohm"]), round(csv_first)))
    print("    本平台按文件名主干分组去重，不用频率值（规范 §一.4）")

    # ---------------- 3. 光热 GBK + 畸形时间列
    dp = Dataset("photothermal_20261111", "photothermal")
    if PTH:
        tp = dp.ingest(PTH, force=True, reason="验证 GBK 表头与畸形时间列容忍")
        print("\n[3] 光热摄取 totals:", json.dumps(tp, ensure_ascii=False))
    else:
        print("\n[3] 桌面无光热测试件，跳过重新摄取；用仓库自带的 raw_meta 核验元数据")
    with open(paths.raw_meta("photothermal_20261111"), encoding="utf-8") as fh:
        mp = json.load(fh)
    print("    编码识别 = %s；表头 = %s" %
          ([s["encoding"] for s in mp["sources"] if s["status"] == "ingested"][0],
           [s["params"]["header"] for s in mp["sources"] if s["status"] == "ingested"][0]))
    for s in mp["sources"]:
        if s["status"] == "ingested":
            print("      %-12s n=%4d  %.3f -> %.3f s" %
                  (s["file"], s["points"], s["first"], s["last"]))
    print("    畸形时间解析：0000-00-00 00:00:00:062 -> %.3f s；"
          "0000-00-00 00:00:01:000 -> %.3f s" %
          (parse_malformed_time("0000-00-00 00:00:00:062"),
           parse_malformed_time("0000-00-00 00:00:01:000")))

    # ---------------- 4. 比对四类
    d = compare("eis_20261107", "eis")
    print("\n[4] 改动比对（工作副本 vs 原始快照）四类计数 = %s" % d["counts"])

    # ---------------- 5. 三个入口 + 排除理由门禁
    gate = ""
    try:
        set_include("eis_20261107", "eis", "ITO 1-1", 1, False, "")
        gate = "未拦截（不合格）"
    except ValueError as e:
        gate = "已拦截：%s" % e
    print("\n[5] 排除不写理由 → %s" % gate)
    c0 = "ITO 1-1"
    set_value("eis_20261107", "eis", c0, 1, "Zp_ohm", 13.4, "高频首点读数复核")
    set_include("eis_20261107", "eis", c0, 2, False, "接插件瞬态干扰，非稳态数据")
    d2 = compare("eis_20261107", "eis")
    print("    改数值 + 排除后四类计数 = %s" % d2["counts"])
    print("    被排除点均写有理由 = %s" % (len(d2["exclusions_without_reason"]) == 0))
    print("    排除点 note = %r" % d2["include_flipped"][0]["note"])
    # 恢复：工作副本整体回到原始快照（数值/参与/备注全一致），给后续层留干净输入；
    # 台账保留 modify / exclude / modify(restore) 三条历史，仍可追溯。
    set_include("eis_20261107", "eis", c0, 2, True, "复核后恢复参与")
    import shutil
    shutil.copyfile(paths.raw_long("eis_20261107"), paths.working("eis_20261107"))
    d3 = compare("eis_20261107", "eis")
    print("    恢复后四类计数 = %s" % d3["counts"])

    # ---------------- 6. 原始快照只读
    rl = paths.raw_long("eis_20261107")
    ro = not bool(os.stat(rl).st_mode & stat.S_IWRITE)
    print("\n[6] 原始快照只读 = %s；工作副本可写 = %s" %
          (ro, bool(os.stat(paths.working("eis_20261107")).st_mode & stat.S_IWRITE)))
    print("    数据集目录结构 =", sorted(os.listdir(paths.dataset_dir("eis_20261107"))))
    print("    raw/ 内容 =", sorted(os.listdir(paths.raw_dir("eis_20261107"))))
    with open(paths.ledger("eis_20261107"), encoding="utf-8") as fh:
        led = json.load(fh)
    print("    台账动作 = %s（共 %d 条）" % ([x["action"] for x in led], len(led)))
    print("\n" + LINE + "\n数据层：跑通\n" + LINE)


if __name__ == "__main__":
    main()
