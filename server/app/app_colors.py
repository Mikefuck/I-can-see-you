"""Device-scoped program colours, separate from immutable uploaded events."""
import hashlib
import json
from pathlib import PureWindowsPath


# ID, label, light theme, dark theme. Keep in sync with client/focus_agent/app_colors.py.
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


def process_key(process):
    return process.strip().replace("/", "\\").rsplit("\\", 1)[-1].casefold()


def default_color(process):
    key = process_key(process).removesuffix(".exe")
    index = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest(), "big") % len(PALETTE)
    return PALETTE[index][0]


def color_for(colors, process):
    key = process_key(process)
    return colors.get(key) or colors.get(PureWindowsPath(key).stem) or default_color(process)


def device_colors(db, device_id):
    row = db.execute("SELECT colors FROM device_app_colors WHERE device_id=?", (device_id,)).fetchone()
    return json.loads(row[0]) if row else {}
