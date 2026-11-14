# -*- coding: utf-8 -*-
"""处理层范式接口：每种谱型按同一范式另写（规范 §二）。

统一要求：
  - 扫描方向由物理量确定（阻抗：频率由高到低），点序保持仪器采集顺序
  - 几何量只描述实测点，不得把拟合结果写成实测
  - 截尾用固定长度（物理量单位），不用固定比例
  - 任何拟合产物都必须带 disclaimer，声明为处理结果而非实测数据
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SpectrumProcessor(ABC):
    name = "base"

    @abstractmethod
    def geometry(self, rows: list[dict]) -> dict:
        """从一条曲线的实测行计算该谱型的特征几何量。"""

    @abstractmethod
    def truncate(self, rows: list[dict], geom: dict, tail) -> list[dict]:
        """按固定长度截尾，返回保留的实测行（仍按采集顺序）。"""

    def fit(self, rows: list[dict], geom: dict) -> dict | None:
        """可选参考拟合；返回必须含 kind="fit" 与 disclaimer 字段。"""
        return None


REGISTRY = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


def get_processor(spectrum: str):
    if spectrum not in REGISTRY:
        raise NotImplementedError("谱型 %r 的处理层尚未实现；已实现：%s"
                                 % (spectrum, list(REGISTRY)))
    return REGISTRY[spectrum]()
