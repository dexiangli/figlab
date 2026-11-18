# -*- coding: utf-8 -*-
"""摄取：容忍畸形输入，按文件名主干去重，保留仪器采集顺序。

必须容忍（规范 §一.3）：
  1. GBK 编码表头（用 gb18030 覆盖 GBK/GB18030）
  2. 形如 0000-00-00 00:00:00:062 的时间戳（日期位全零、毫秒以冒号续接）
  3. 各文件起点与采样间隔不一致 —— 不重采样、不对齐，点序照抄文件行序

去重（规范 §一.4）：按文件名主干分组；同一次测量若文本与二进制并存，只取
文本导出，被跳过的文件写进元数据。**禁止用频率值取整去重**：两份导出同一
频点的浮点值有 3.9e-04 量级差异，取整去重会失效，导致同一次测量画两遍。
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import struct
import zipfile

TEXT_EXT = {".csv", ".txt", ".dat"}
BIN_EXT = {".bin"}
TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}):(\d{3})\s*$")


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sniff_decode(blob: bytes):
    """依次尝试 utf-8-sig / gb18030 / latin-1，返回 (文本, 编码)。"""
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return blob.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return blob.decode("latin-1"), "latin-1"


def parse_malformed_time(s: str) -> float:
    """0000-00-00 00:00:00:062 -> 0.062 秒；日期位全零部分忽略。"""
    m = TIME_RE.search(s.strip())
    if not m:
        raise ValueError("无法解析畸形时间列：%r" % s)
    h, mi, sec, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + sec + ms / 1000.0


def load_sources(src: str) -> list[tuple[str, bytes]]:
    """Read a source directory, a ZIP archive, or a single text export."""
    out = []
    if os.path.isdir(src):
        for name in sorted(os.listdir(src)):
            p = os.path.join(src, name)
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    out.append((name, fh.read()))
    elif src.lower().endswith(".zip"):
        with zipfile.ZipFile(src) as zf:
            for info in sorted(zf.infolist(), key=lambda z: z.filename):
                if info.is_dir() or info.filename.startswith("__MACOSX"):
                    continue
                out.append((os.path.basename(info.filename), zf.read(info)))
    elif os.path.isfile(src) and os.path.splitext(src)[1].lower() in TEXT_EXT:
        with open(src, "rb") as fh:
            out.append((os.path.basename(src), fh.read()))
    else:
        raise ValueError("源须为目录、ZIP 或文本数据文件：%s" % src)
    return out


# ---------------------------------------------------------------- 阻抗谱文本
def _is_data_line(line: str) -> bool:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 3:
        return False
    try:
        float(parts[0]); float(parts[1]); float(parts[2])
        return True
    except ValueError:
        return False


def parse_chi_text(blob: bytes):
    """CHI760E 交流阻抗文本导出：参数区 + 5 列数据区。

    数据列为 Freq / Z' / Z'' / |Z| / Phase。长表只收前三个测得量；|Z| 与
    Phase 是仪器算出的派生量，不进长表（原始字节副本仍在 raw/sources 可复核）。
    """
    text, enc = sniff_decode(blob)
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    params, stamp = {}, ""
    if lines and lines[0].strip():
        stamp = lines[0].strip()
        params["_first_line"] = stamp
    start = None
    for i, ln in enumerate(lines):
        if i == 0:
            continue  # 首行是采集时间戳，已存 stamp，不再当参数拆
        s = ln.strip()
        if not s:
            continue
        if _is_data_line(s):
            start = i
            break
        m = re.match(r"^([^:=]+?)\s*[=:]\s*(.*)$", s)
        if m:
            params[m.group(1).strip()] = m.group(2).strip()
        elif "Freq" in s and "," in s:
            params["column_header"] = s   # 仪器给出的完整列名行，属于表头参数
        else:
            params["_header_%d" % i] = s
    if start is None:
        raise ValueError("未找到数据起始行")

    rows = []
    for ln in lines[start:]:
        s = ln.strip()
        if not s or not _is_data_line(s):
            continue
        p = [x.strip() for x in s.split(",")]
        rows.append({
            "freq_Hz": float(p[0]),
            "Zp_ohm": float(p[1]),
            "Zpp_ohm": float(p[2]),   # 仪器原值，负号保留；绘图时才取 -Z''
        })
    return {"encoding": enc, "stamp": stamp, "params": params,
            "rows": rows, "extra_columns_dropped": ["|Z|", "Phase(deg)"],
            "freq_first": rows[0]["freq_Hz"] if rows else None,
            "freq_last": rows[-1]["freq_Hz"] if rows else None}


def count_chi_bin_points(blob: bytes) -> int:
    """只数点、不产出数据行（本版 BIN-only 文件不纳入绘图，见交付说明）。

    CHI760E 二进制数值段紧贴文件末尾，每条 16 字节 = 频率、频率、Z'、Z''，
    小端 float32。判据沿用仪器格式本身，不参与去重判断。
    """
    n, off, prev = 0, len(blob) - 16, None
    while off >= 0:
        try:
            a, b, zp, zpp = struct.unpack_from("<ffff", blob, off)
        except struct.error:
            break
        if not (abs(a - b) <= 1e-4 * max(abs(a), 1e-9) and 1e-4 <= a <= 1e7
                and abs(zp) < 1e6 and abs(zpp) < 1e6):
            break
        # 从文件末尾往前读，频率应单调升高；与「上一条」比较，不是与第一条比较
        if prev is not None and not a > prev:
            break
        prev = a
        n += 1
        off -= 16
    return n


# ---------------------------------------------------------------- 光热文本
def parse_photothermal(blob: bytes):
    """GBK 表头「时间,Ar1.平均值 (℃)」+ 畸形时间列。"""
    text, enc = sniff_decode(blob)
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("空文件")
    header = [h.strip() for h in lines[0].split(",")]
    rows = []
    for ln in lines[1:]:
        p = [x.strip() for x in ln.split(",")]
        if len(p) < 2:
            continue
        try:
            t = parse_malformed_time(p[0])
            v = float(p[1])
        except ValueError:
            continue
        # 保留绝对秒，不减首点：各文件起点本来就不同，抹平等于改写数据
        rows.append({"time_s": round(t, 6), "temp_C": v})
    return {"encoding": enc, "stamp": "", "params": {"header": header},
            "rows": rows, "extra_columns_dropped": [],
            "time_first_s": rows[0]["time_s"] if rows else None,
            "time_last_s": rows[-1]["time_s"] if rows else None}


def parse_mott_schottky(blob: bytes):
    text, encoding = sniff_decode(blob)
    header, separator, body = text.partition('Potential/V, Z\'/ohm, Z"/ohm, Z/ohm, Phase/deg')
    if not separator:
        raise ValueError("Expected a CHI impedance–potential export")
    stamp, *params_lines = header.strip().splitlines()
    params = dict(tuple(part.strip() for part in line.split("=", 1))
                  for line in params_lines if "=" in line)
    frequency = float(params["Frequency (Hz)"])
    if frequency <= 0:
        raise ValueError("Frequency must be positive")
    rows = []
    for line in body.strip().splitlines():
        potential, real, imag, _, phase = map(float, line.split(","))
        rows.append(dict(freq_Hz=frequency, potential_V=potential, Zp_ohm=real,
                         Zpp_ohm=imag, phase_deg=phase))
    return dict(encoding=encoding, stamp=stamp, params=params, rows=rows)


def parse_uvvis(blob: bytes):
    text, encoding = sniff_decode(blob)
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "nm,A"), None)
    if start is None:
        raise ValueError("Expected a UV–Vis CSV with nm,A columns")
    rows = []
    for line in lines[start + 1:]:
        if not re.fullmatch(r"\s*\d+(?:\.\d+)?,\s*[+-]?\d+(?:\.\d+)?\s*", line):
            continue
        wavelength, absorbance = map(float, line.split(","))
        rows.append(dict(wavelength_nm=wavelength, absorbance=absorbance))
    if not rows or any(row["wavelength_nm"] <= 0 for row in rows):
        raise ValueError("Expected positive wavelengths")
    return dict(encoding=encoding, stamp="", params={"column_header": "nm,A"}, rows=rows)


def parse_fscv(blob: bytes):
    text, encoding = sniff_decode(blob)
    reader = csv.reader(text.splitlines())
    header = next(reader, [])
    if len(header) < 2 or header[0] != "potential_V" or len(set(header)) != len(header):
        raise ValueError("Expected potential_V and distinct FSCV current columns")
    concentrations = [re.fullmatch(r"(.+)_([0-9]+(?:\.[0-9]+)?)uM_nA", name)
                      for name in header[1:]]
    if not all(concentrations):
        raise ValueError("Expected FSCV current columns named <analyte>_<concentration>uM_nA")
    labels = [f"{match[1]} {match[2]} μM" for match in concentrations]
    rows = []
    for index, values in enumerate(reader, start=1):
        try:
            finite = all(math.isfinite(float(value)) for value in values)
        except ValueError:
            finite = False
        if len(values) != len(header) or not finite:
            raise ValueError(f"Invalid FSCV data at CSV row {index + 1}")
        rows.extend(dict(curve=label, point_index=index, potential_V=values[0], current_nA=current)
                    for label, current in zip(labels, values[1:]))
    if not rows:
        raise ValueError("FSCV CSV contains no data")
    return dict(encoding=encoding, stamp="", params={"column_header": header}, rows=rows)


PARSERS = {"eis": parse_chi_text, "photothermal": parse_photothermal, "uvvis": parse_uvvis,
           "fscv": parse_fscv,
           "mott_schottky": parse_mott_schottky}


def group_by_stem(files: list[tuple[str, bytes]]):
    """按文件名主干分组；组内文本导出优先，二进制记为被跳过。"""
    groups = {}
    for name, blob in files:
        stem, ext = os.path.splitext(name)
        groups.setdefault(stem, []).append((name, ext.lower(), blob))
    chosen, skipped, bin_only = [], [], []
    for stem, items in sorted(groups.items()):
        texts = [it for it in items if it[1] in TEXT_EXT]
        bins = [it for it in items if it[1] in BIN_EXT]
        if texts:
            chosen.append((stem, texts[0]))
            for b in bins:
                skipped.append({"file": b[0], "reason": "同主干已有文本导出，只取文本"})
        elif bins:
            bin_only.append((stem, bins[0]))
        else:
            skipped.append({"file": items[0][0], "reason": "扩展名不支持，非文本亦非二进制"})
    return chosen, skipped, bin_only
