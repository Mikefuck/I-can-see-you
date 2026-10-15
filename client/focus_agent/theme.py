"""Per-window colours shared by the stylesheet, native controls and painted timelines."""
from PySide6.QtGui import QColor, QPalette


THEME_LABELS = {"system": "跟随系统", "light": "浅色", "dark": "深色"}
THEMES = {
    "light": dict(ink="#101010", paper="#ffffff", red="#eb0000", graphite="#5e5e5e",
                  rule="#d0d0d0", field="#f0f0f0", faded="#a3a3a3", signal="#eb0000",
                  scrollbar="#c4c4c4"),
    "dark": dict(ink="#e8e8e5", paper="#161616", red="#ff6b61", graphite="#b0b0ad",
                 rule="#414141", field="#242424", faded="#858582", signal="#c62b23",
                 scrollbar="#555555"),
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
