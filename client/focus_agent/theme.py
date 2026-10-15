"""Per-window colours shared by the stylesheet, native controls and painted timelines."""
from PySide6.QtGui import QColor, QPalette


THEME_LABELS = {"system": "跟随系统", "light": "浅色", "dark": "深色"}
THEMES = {
    "light": dict(ink="#30312c", paper="#f6f1df", red="#eb0000", graphite="#66675c",
                  rule="#d7d1bd", field="#eee7d0", faded="#8b897d", signal="#eb0000",
                  scrollbar="#c4bda8", glow_warm=("#e8ca80", .22), glow_pearl=("#fffef5", .78)),
    "dark": dict(ink="#e6e3d5", paper="#282925", red="#ff6b61", graphite="#bab9ac",
                 rule="#4b4d43", field="#33352e", faded="#918f82", signal="#c62b23",
                 scrollbar="#626557", glow_warm=("#d3bd82", .10), glow_pearl=("#e5e7cc", .05)),
}


def colors_for(widget):
    return getattr(widget.window(), "theme_colors", THEMES["light"])


def palette_for(colors):
    palette = QPalette()
    roles = {
        "Window": "paper", "WindowText": "ink", "Base": "paper", "AlternateBase": "field",
        "Text": "ink", "Button": "paper", "ButtonText": "ink", "ToolTipBase": "ink",
        "ToolTipText": "paper", "Highlight": "ink", "HighlightedText": "paper",
        "Link": "red", "LinkVisited": "red", "PlaceholderText": "graphite", "Accent": "red",
        "Light": "rule", "Midlight": "field", "Mid": "rule", "Dark": "rule", "Shadow": "rule",
    }
    for role, key in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(colors[key]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    for role in ("WindowText", "Text", "ButtonText", "PlaceholderText"):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor(colors["faded"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(colors["rule"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(colors["ink"]))
    return palette
