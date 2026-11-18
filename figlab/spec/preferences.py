"""Local drawing preferences, stored with this installation's data."""
import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile

from .. import paths


def settings():
    path = Path(paths.ROOT) / "style_settings.json"
    if not path.exists():
        return {"configured": False}
    return json.loads(path.read_text(encoding="utf-8"))


def save_settings(body):
    from .merge import load_preset

    preset = load_preset(body["preset"])
    for field in ("page", "layer", "style"):
        preset[field].update(body.get(field, {}))
    preset["palette"] = body.get("palette", preset["palette"])
    numeric = [(preset["page"][key], 3, 30) for key in ("w_cm", "h_cm")]
    numeric += [(preset["layer"][key], .1, 99) for key in ("left", "top", "width", "height")]
    numeric += [(preset["style"][key], .1, 36) for key in
                ("tick_pt", "title_pt", "line_width_pt", "marker_size_pt", "frame_line_width_pt")]
    if any(type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high
           for value, low, high in numeric):
        raise ValueError("尺寸、字号和线宽超出范围")
    layer = preset["layer"]
    if layer["left"] + layer["width"] > 100 or layer["top"] + layer["height"] > 100:
        raise ValueError("绘图区超出画布")
    style = preset["style"]
    if (style["font"] not in ("Arial", "Times New Roman", "DejaVu Sans")
            or style["spines"] not in ("all", "left_bottom")
            or style["tick_dir"] not in ("in", "out")):
        raise ValueError("字体或坐标轴样式无效")
    if not 1 <= len(preset["palette"]) <= 12 or any(
            not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            for color in preset["palette"]):
        raise ValueError("配色须为 1–12 个六位十六进制颜色")
    result = {"configured": True, "preset": body["preset"], "template": preset}
    first_setup = not settings().get("configured")
    demo = Path(paths.spec_file("fscv_demo"))
    if first_setup and demo.exists():
        from .merge import save_spec
        spec = json.loads(demo.read_text(encoding="utf-8"))
        for field in ("page", "layer", "legend"):
            spec[field] = copy.deepcopy(preset[field])
        spec["style"].update(preset["style"])
        for index, series in enumerate(spec["series"]):
            series["color"] = preset["palette"][index % len(preset["palette"])]
        spec["overrides"] = {key: copy.deepcopy(spec[key]) for key in
                             ("page", "layer", "legend", "style", "series", "data", "axis", "export")}
        save_spec(spec, register=False)
    root = Path(paths.ROOT)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=root, mode="w", encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(result, handle, ensure_ascii=False, indent=2)
    try:
        os.replace(temporary, root / "style_settings.json")
    finally:
        temporary.unlink(missing_ok=True)
    return result


def preferred_template():
    choice = settings()
    return copy.deepcopy(choice.get("template")) if choice.get("configured") else None
