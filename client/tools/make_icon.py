"""Write the program icon (the tray mark in its recording colour) as a multi-size .ico for PyInstaller."""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication
from focus_agent.gui import icon_image

SIZES = (16, 20, 24, 32, 40, 48, 64, 256)


def png(size):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert icon_image(size).save(buffer, "PNG")
    return bytes(buffer.data())


def ico(images):
    """ICO container with PNG-compressed entries (supported since Windows Vista); 256 is stored as 0."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, data = b"", b""
    for size, image in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset + len(data))
        data += image
    return header + entries + data


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else CLIENT / "build" / "icon" / "FocusLedger.ico"
    app = QGuiApplication.instance() or QGuiApplication([])  # painting the icon needs a GUI application
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ico([(size, png(size)) for size in SIZES]))
    print(target)


if __name__ == "__main__":
    main()
