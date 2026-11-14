# -*- coding: utf-8 -*-
"""figlab：本地科研绘图平台。

分五层，层间以文件为契约，不引入数据库：
    data / process / spec / render / web
另有一条默认关闭的 origin 第二出口，以及独立 verify 核验层。
"""
__version__ = "1.0.0"
