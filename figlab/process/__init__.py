# -*- coding: utf-8 -*-
"""处理层：当前实现阻抗谱，其他谱型按 base.SpectrumProcessor 范式另写。"""
from .base import SpectrumProcessor, get_processor, register  # noqa: F401
from . import eis  # noqa: F401  注册 EISProcessor
