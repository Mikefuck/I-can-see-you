"""Form controls that leave mouse-wheel input to the surrounding page."""
from PySide6.QtWidgets import QSpinBox


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        # Ignore even while focused; Qt can then scroll the parent instead of changing a setting.
        event.ignore()
