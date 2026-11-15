"""Publish editable SVG and a reusable file reference to the Windows clipboard."""
import ctypes
import hashlib
import os
import struct
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from .. import paths


def copy_svg(svg):
    if os.name != "nt":
        raise ValueError("当前系统可使用「下载 SVG」")
    key = hashlib.sha256(os.fsencode(os.path.normcase(paths.ROOT))).hexdigest()[:12]
    cache = Path(tempfile.gettempdir(), "FigLab", key)
    cache.mkdir(parents=True, exist_ok=True)
    file = cache / "FigLab 剪贴板.svg"
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(svg)
    try:
        temp.replace(file)
    finally:
        temp.unlink(missing_ok=True)

    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def bind(library, name, result, *args):
        function = getattr(library, name)
        function.restype, function.argtypes = result, args
        return function

    ptr, uint, integer = ctypes.c_void_p, wintypes.UINT, ctypes.c_int
    create = bind(user, "CreateWindowExW", ptr, wintypes.DWORD, wintypes.LPCWSTR,
                  wintypes.LPCWSTR, wintypes.DWORD, integer, integer, integer, integer,
                  ptr, ptr, ptr, ptr)
    destroy = bind(user, "DestroyWindow", wintypes.BOOL, ptr)
    open_clipboard = bind(user, "OpenClipboard", wintypes.BOOL, ptr)
    set_data = bind(user, "SetClipboardData", ptr, uint, ptr)
    register = bind(user, "RegisterClipboardFormatW", uint, wintypes.LPCWSTR)
    allocate = bind(kernel, "GlobalAlloc", ptr, uint, ctypes.c_size_t)
    lock = bind(kernel, "GlobalLock", ptr, ptr)
    unlock = bind(kernel, "GlobalUnlock", wintypes.BOOL, ptr)
    free = bind(kernel, "GlobalFree", ptr, ptr)
    svg_format = register("image/svg+xml")
    if not svg_format:
        raise ctypes.WinError(ctypes.get_last_error())
    formats = [(svg_format, svg + b"\0"),
               (15, struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(file) + "\0\0").encode("utf-16-le"))]
    window = create(0, "STATIC", "FigLab clipboard", 0, 0, 0, 0, 0, ptr(-3), None, None, None)
    if not window:
        raise ctypes.WinError(ctypes.get_last_error())
    allocated = {}
    try:
        for fmt, data in formats:
            memory = allocate(2, len(data))
            if not memory:
                raise ctypes.WinError(ctypes.get_last_error())
            allocated[fmt] = memory
            address = lock(memory)
            if not address:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(address, data, len(data))
            unlock(memory)
        for _ in range(12):
            if open_clipboard(window):
                break
            time.sleep(.025)
        else:
            raise ValueError("剪贴板正被其他程序占用，请再试一次")
        try:
            if not user.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            for fmt in list(allocated):
                if not set_data(fmt, allocated[fmt]):
                    raise ctypes.WinError(ctypes.get_last_error())
                del allocated[fmt]
        finally:
            user.CloseClipboard()
    finally:
        for memory in allocated.values():
            free(memory)
        destroy(window)
