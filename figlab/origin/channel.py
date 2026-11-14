# -*- coding: utf-8 -*-
"""可选的 Origin 自动化通道：仅作第二出口，默认关闭，不得作为主路径（§六）。

启用前必须逐项核验：图例位置、刻度方向、字号继承、导出目录。
已知现象：
  - 图例对象没有可直接定位的属性，只能通过图例位置命令以 1/600 英寸设置；
  - 刻度方向命令常返回成功但图像不变，必须看渲染结果，不能只看返回值；
  - 导出目录用相对路径会写到 Origin 自己的工作目录，而校验用当前进程目录，
    结果判为失败并留下 0 字节文件。
本模块不会自行拉起 Origin 或打开任何窗口；ENABLED 需由使用者显式打开。
"""
from __future__ import annotations

import importlib.util
import os

ENABLED = False
ORIGIN_UNIT_PER_INCH = 600          # Origin 内部长度单位：1/600 英寸


def preflight(export_dir: str = "") -> dict:
    """逐项核验，返回可核对的状态，不声称「成功」。"""
    items = {
        "originpro_installed": importlib.util.find_spec("originpro") is not None,
        "origin_process_running": _origin_running(),
        "legend_position": "需实机核验：只能用图例位置命令，单位 1/600 英寸；无直接定位属性",
        "tick_direction": "需实机核验：命令常返回成功但图像不变，必须看渲染结果",
        "font_size_inheritance": "需实机核验：画布缩到 8 cm 后刻度字号是否跟着缩放",
        "export_dir_absolute": bool(export_dir) and os.path.isabs(export_dir),
        "export_dir": os.path.abspath(export_dir) if export_dir else "",
    }
    items["ready"] = bool(items["originpro_installed"] and
                          items["origin_process_running"] and
                          items["export_dir_absolute"] and ENABLED)
    return items


def _origin_running() -> bool:
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Origin64.exe"],
                             capture_output=True, text=True, timeout=10).stdout
        return "Origin64.exe" in out
    except Exception:
        return False


def cm_to_origin_unit(cm: float) -> float:
    return cm / 2.54 * ORIGIN_UNIT_PER_INCH


def send_to_origin(spec: dict, export_dir: str):
    """第二出口占位：未通过 preflight 一律拒绝，绝不静默产生 0 字节文件。"""
    chk = preflight(export_dir)
    if not ENABLED:
        raise RuntimeError("Origin 通道默认关闭；主路径是 figlab 渲染层，不需要它")
    if not chk["ready"]:
        raise RuntimeError("Origin 通道 preflight 未通过：%s" % chk)
    raise NotImplementedError(
        "逐项核验通过后，再由使用者在此接入建表建图；本版不自动开窗、不写 Origin 项目")


if __name__ == "__main__":
    import json
    import os
    _out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "outputs")
    print(json.dumps(preflight(_out), ensure_ascii=False, indent=2))
