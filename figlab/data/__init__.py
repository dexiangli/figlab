# -*- coding: utf-8 -*-
"""数据层：原始快照只读、工作副本可改、台账可追溯。

长表列由谱型决定。阻抗谱严格用规范 §一.5 的七字段；其他谱型按同一范式
扩展，共享「曲线名 / 点序 / 参与标记 / 备注」四个通用列，数值列按谱型另写，
不把未测得的量硬塞进 impedance 列。
"""
from __future__ import annotations

# 通用四列（所有谱型都必须有）
COMMON = ["curve", "point_index", "include", "note"]

SPECTRUM_COLUMNS = {
    "xps": ["curve", "point_index", "binding_energy_eV", "intensity_cps", "include", "note"],
    "fscv": ["curve", "point_index", "potential_V", "current_nA", "include", "note"],
    "uvvis": ["curve", "point_index", "wavelength_nm", "absorbance", "include", "note"],
    # 规范 §一.5：曲线名、点序、频率、实部、虚部、参与标记、备注
    "eis": ["curve", "point_index", "freq_Hz", "Zp_ohm", "Zpp_ohm", "include", "note"],
    # 光热：时间由畸形时间戳解析为秒；只有温度一个测得量
    "photothermal": ["curve", "point_index", "time_s", "temp_C", "include", "note"],
    "mott_schottky": ["curve", "point_index", "freq_Hz", "potential_V", "Zp_ohm",
                      "Zpp_ohm", "phase_deg", "include", "note"],
}

NUMERIC_COLUMNS = {
    "xps": ["binding_energy_eV", "intensity_cps"],
    "fscv": ["potential_V", "current_nA"],
    "uvvis": ["wavelength_nm", "absorbance"],
    "eis": ["freq_Hz", "Zp_ohm", "Zpp_ohm"],
    "photothermal": ["time_s", "temp_C"],
    "mott_schottky": ["freq_Hz", "potential_V", "Zp_ohm", "Zpp_ohm", "phase_deg"],
}


def columns(spectrum: str) -> list[str]:
    if spectrum not in SPECTRUM_COLUMNS:
        raise ValueError("未知谱型 %r；已实现：%s" % (spectrum, list(SPECTRUM_COLUMNS)))
    return list(SPECTRUM_COLUMNS[spectrum])
