# -*- coding: utf-8 -*-
r"""figlab 启动入口。

    python run.py 8778

服务只监听 127.0.0.1；启动前会探测端口，被占用则直接报错退出（缺陷清单第 3 条）。
"""
from __future__ import annotations

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from figlab.web.server import main  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="启动 FigLab")
    parser.add_argument("port", nargs="?", type=int, default=8778)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.port, open_browser=args.browser))
