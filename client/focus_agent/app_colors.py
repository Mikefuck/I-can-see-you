"""A restrained palette shared with the web timetable (IDs are part of the API)."""
import hashlib

from .aliases import alias_for, process_key


# ID, label, light theme, dark theme. Keep in sync with server/app/app_colors.py.
PALETTE = (
    ("slate", "雾蓝", "#597486", "#8faebe"),
    ("teal", "灰青", "#487f7a", "#83b5a9"),
    ("olive", "橄榄", "#7a8050", "#b0b77b"),
    ("ochre", "赭黄", "#a08142", "#ccb276"),
    ("terracotta", "陶土", "#ac6e52", "#d49a7b"),
    ("rose", "豆沙", "#a06472", "#ce94a1"),
    ("mauve", "灰紫", "#886f92", "#b8a1c2"),
    ("indigo", "靛灰", "#65719b", "#9faacf"),
    ("steel", "钢蓝", "#4b829a", "#86b8cb"),
    ("sage", "鼠尾草", "#6d8b69", "#a0bc96"),
    ("cocoa", "可可", "#876d59", "#baa18a"),
    ("plum", "梅灰", "#936582", "#c799b5"),
)
COLOR_IDS = frozenset(color[0] for color in PALETTE)


def default_color(process):
    """Stable pseudo-random assignment, independent of aliases, devices and refreshes."""
    key = process_key(process).removesuffix(".exe")
    index = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest(), "big") % len(PALETTE)
    return PALETTE[index][0]


def color_for(colors, process):
    return alias_for(colors, process) or default_color(process)


def normalize_colors(colors):
    if not isinstance(colors, dict) or len(colors) > 500:
        raise ValueError("程序颜色最多支持 500 条")
    result = {}
    for process, color in colors.items():
        if not isinstance(process, str) or not isinstance(color, str):
            raise ValueError("程序颜色必须使用文本键和值")
        key = process_key(process)
        if not 1 <= len(key) <= 200 or color not in COLOR_IDS:
            raise ValueError("程序颜色须使用预设配色，进程名须为 1–200 个字符")
        if key in result:
            raise ValueError("程序颜色中的进程名重复")
        result[key] = color
    return result
