# -*- coding: utf-8 -*-
"""标准库 HTTP 服务：只监听 127.0.0.1，不做鉴权、不联网、不需要 Node。

对应缺陷清单第 3 条：启动前先探测端口；若已被旧进程占用，直接报错退出，
绝不出现「新进程绑定失败而旧进程继续应答」的假生效。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import handoff, paths
from . import api, board, clipboard
from ..spec import preferences

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")

# matplotlib 的 rcParams / figure 注册表是进程级全局状态，多线程同时渲染会互相
# 踩踏（表现为连接被直接断开、进程却还活着）。本地单用户场景串行化最稳。
RENDER_LOCK = threading.RLock()

# 只有真正碰 matplotlib 的接口才排队。以前整台服务（连 ui.html 和缩略图）都排在
# 同一把锁后面，一次导出（约 0.9 s）就把所有点击卡住，表现成「按钮点了没反应」。
HEAVY_GET = {"/api/figure", "/api/reports", "/api/board/preview", "/api/board/revision", "/api/svg"}
HEAVY_POST = {"/api/point", "/api/workbook", "/api/undo", "/api/redo",
              "/api/spec", "/api/export", "/api/curve-shift", "/api/pptx",
              "/api/project/open", "/api/board/create", "/api/board/save", "/api/clipboard", "/api/style-settings"}


class Handler(BaseHTTPRequestHandler):
    server_version = "figlab/1.0"

    def _send(self, code, body, ctype="application/json; charset=utf-8", attachment=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(attachment))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, e):
        return self._send(500, {"error": "%s: %s" % (type(e).__name__, e),
                               "trace": traceback.format_exc()})

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path in HEAVY_GET:
            with RENDER_LOCK:
                return self._do_get()
        return self._do_get()

    def _do_get(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        try:
            if p in ("/", "/index.html"):
                with open(UI, encoding="utf-8") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if p == "/api/style-settings":
                from ..spec.merge import load_preset
                from ..spec.schema import PRESET_NAMES
                return self._send(200, {**preferences.settings(),
                                       "presets": {name: load_preset(name) for name in PRESET_NAMES}})
            if p in ("/board.js", "/board.html", "/theme.js", "/theme.css", "/style.html"):
                name = p[1:]
                ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[os.path.splitext(name)[1]]
                with open(os.path.join(os.path.dirname(UI), name), encoding="utf-8") as fh:
                    return self._send(200, fh.read(), ctype + "; charset=utf-8")
            if p == "/api/locations":
                return self._send(200, {"project": paths.ROOT, "datasets": paths.DATASETS,
                                        "outputs": paths.OUTPUTS, "desktop": handoff.out_root()})
            if p == "/api/svg":
                fid = q["id"][0]
                svg = board.preview(fid)
                spec = board.figure_spec(fid)
                return self._send(200, svg, "image/svg+xml", attachment=spec["export"]["base"] + ".svg")
            if p == "/api/board/settings":
                return self._send(200, {"ai": board.ai_available()})
            if p == "/api/board":
                spec = board.figure_spec(q["id"][0])
                if spec.get("kind") != "board":
                    return self._send(400, {"error": "请选择组图窗口"})
                return self._send(200, spec["layout"])
            if p == "/api/board/preview":
                return self._send(200, board.preview(q["id"][0]), "image/svg+xml")
            if p == "/api/board/revision":
                return self._send(200, {"revision": board.revision(q["id"][0])})
            if p == "/api/figures":
                return self._send(200, {"figures": api.figure_list()})
            if p == "/api/project":
                return self._send(200, api.project_view())
            if p == "/api/pptx/list":
                return self._send(200, api.pptx_list())
            if p == "/api/figure":
                return self._send(200, api.get_figure(q.get("id", ["eis_main"])[0]))
            if p == "/api/figure/delete-plan":
                return self._send(200, api.delete_plan(q.get("id", [""])[0]))
            if p == "/api/table":
                return self._send(200, api.table(q.get("figure", [""])[0],
                                                 q.get("curve", [""])[0]))
            if p == "/api/workbook":
                return self._send(200, api.get_workbook(q.get("figure", [""])[0]))
            if p == "/api/raw":
                return self._send(200, api.raw_view(q.get("figure", [""])[0]))
            if p == "/api/archive":
                return self._send(200, api.archive_view())
            if p == "/api/ledger":
                return self._send(200, api.ledger_view(q.get("figure", [""])[0]))
            if p == "/api/reports":
                return self._send(200, api.reports(q.get("id", [""])[0]))
            if p == "/api/thumbs":
                return self._send(200, {"files": api.thumbs(q.get("id", [""])[0])})
            if p == "/api/thumb":
                fid = q.get("id", [""])[0]
                name = os.path.basename(q.get("file", [""])[0])
                fp = os.path.join(paths.out_dir(fid), name)
                with open(fp, "rb") as fh:
                    return self._send(200, fh.read(), "image/png")
            return self._send(404, {"error": "未知接口 %s" % p})
        except Exception as e:
            return self._err(e)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path in HEAVY_POST:
            with RENDER_LOCK:
                return self._do_post()
        return self._do_post()

    def _do_post(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        q = urllib.parse.parse_qs(u.query)
        n = int(self.headers.get("Content-Length", 0))
        try:
            if p == "/api/clipboard" and (self.headers.get("Origin") != "http://" + self.headers.get("Host", "")
                                          or not self.headers.get("Content-Type", "").startswith("application/json")):
                return self._send(403, {"error": "请在 FigLab 页面内复制"})
            if p.startswith("/api/board/"):
                origin = self.headers.get("Origin")
                if origin and origin != "http://" + self.headers.get("Host", ""):
                    return self._send(403, {"error": "请在 FigLab 页面内执行此操作"})
                if not 0 <= n <= 64 * 1024 * 1024:
                    return self._send(413, {"error": "文件过大，请分批导入"})
            body = json.loads(self.rfile.read(n) or b"{}")
            if p == "/api/style-settings":
                origin = self.headers.get("Origin")
                if origin and origin != "http://" + self.headers.get("Host", ""):
                    return self._send(403, {"error": "请在 FigLab 页面内配置"})
                return self._send(200, preferences.save_settings(body))
            if p == "/api/clipboard":
                clipboard.copy_svg(board.preview(body["figure"]).encode("utf-8"))
                return self._send(200, {"ok": True})
            if p in ("/api/board/create", "/api/board/save"):
                return self._send(200, board.save_layout(body, create=p.endswith("/create")))
            if p == "/api/board/ai":
                return self._layout_stream(body)
            # ?fast=1 或 body.fast：只渲染 SVG，不导出/不核验，供拖动与勾选即时反馈
            fast = bool(body.get("fast")) or q.get("fast", ["0"])[0] not in ("", "0")
            if p == "/api/point":
                return self._send(200, api.edit_point(body["figure"], body))
            if p == "/api/workbook":
                return self._send(200, api.commit_workbook(body["figure"], body))
            if p == "/api/undo":
                return self._send(200, api.history_step(body["figure"], "undo", fast))
            if p == "/api/redo":
                return self._send(200, api.history_step(body["figure"], "redo", fast))
            if p == "/api/spec":
                return self._send(200, api.patch_spec(body["figure"], body["patch"], fast))
            if p == "/api/curve-shift":
                return self._send(200, api.curve_shift(body["figure"], body["curve"],
                                                       body.get("dx", 0), body.get("dy", 0),
                                                       bool(body.get("lock_axis"))))
            if p == "/api/export":
                # spec：页面当前那份规格，导出就照它来（所见即所得）
                # deliver：用户亲手点导出才往桌面复制成品
                return self._send(200, api.re_render(
                    body["figure"], full=not fast,
                    spec=body.get("spec") if isinstance(body.get("spec"), dict) else None,
                    deliver=bool(body.get("deliver"))))
            if p == "/api/project/save":
                return self._send(200, api.save_project_file(body["figure"], body))
            if p == "/api/project/open":
                return self._send(200, api.open_project_file(body))
            if p == "/api/figure/add":
                return self._send(200, api.add_figure(body["id"],
                                                      body.get("preset", "inhouse"),
                                                      body.get("dataset", "eis_20261107"),
                                                      body.get("folder", "")))
            if p == "/api/project":
                return self._send(200, api.project_op(body))
            if p == "/api/pptx":
                return self._send(200, api.export_pptx(body["figure"], body))
            if p == "/api/figure/delete":
                return self._send(200, api.delete_figure(body["id"],
                                                         bool(body.get("purge"))))
            if p == "/api/verify":
                return self._send(200, api.reports(body["figure"]))
            if p == "/api/open-folder":
                return self._send(200, api.open_folder(body.get("figure", ""),
                                                       body.get("which", "archive")))
            return self._send(404, {"error": "未知接口 %s" % p})
        except Exception as e:
            return self._err(e)

    def _layout_stream(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(event):
            self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        events = board.layout_events(body)
        try:
            for event in events:
                emit(event)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            try:
                message = f"AI 请求失败（HTTP {error.code}）" if hasattr(error, "code") else "AI 未返回有效的布局，请重试"
                emit({"error": message})
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            events.close()

    def log_message(self, fmt, *args):
        pass  # 本地工具，不刷屏


def port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main(port: int = 8778, open_browser: bool = False) -> int:
    if not port_free(port):
        print("端口 127.0.0.1:%d 已被占用。" % port)
        print("按缺陷清单第 3 条，重启前必须先结束监听该端口的进程，")
        print("否则新进程绑定失败而旧进程继续应答，表现为「改了没生效」。")
        print("查进程： Get-NetTCPConnection -LocalPort %d | Select OwningProcess" % port)
        return 2
    os.chdir(paths.ROOT)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("figlab 已启动： http://127.0.0.1:%d  （仅本机监听，Ctrl+C 结束）" % port)
    print("数据集目录： %s" % paths.DATASETS)
    print("规格目录：   %s" % paths.SPECS)
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(f"http://127.0.0.1:{port}",), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8778
    sys.exit(main(port))
