"""Quiet, warm light behind the native pages; no network or image assets required."""
import ctypes
import math
import time
from ctypes import wintypes

from PySide6.QtCore import QEvent, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from .theme import colors_for


def animations_enabled():
    """Respect Windows Accessibility > Visual effects > Animation effects.

    https://learn.microsoft.com/en-us/windows/win32/winauto/client-area-animation
    """
    enabled = wintypes.BOOL()
    try:
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    except (AttributeError, OSError):
        pass
    return False  # Keep the static wash when the preference cannot be read.


class AmbientBackground(QWidget):
    """Paint cached soft gradients behind ordinary, fully interactive Qt controls."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.phase = 0.0
        self._last_step = time.monotonic()
        self._next_preference_check = 0.0
        self._animated = False
        self._glow_key = None
        self._glows = ()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)
        parent.installEventFilter(self)

    def stop_motion(self):
        self.timer.stop()

    def _sync_motion(self):
        if not self.isVisible() or self.window().isMinimized() or getattr(self.window(), "quitting", False):
            self.stop_motion()
            return
        self._animated = animations_enabled()
        self._last_step = time.monotonic()
        self._next_preference_check = self._last_step + 2
        # A slow preference check lets an already-open window notice accessibility changes.
        # Only the animated mode repaints, at 12.5 fps for this very slow drift.
        self.timer.start(80 if self._animated else 2000)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_motion()

    def hideEvent(self, event):
        self.stop_motion()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.window() and event.type() == QEvent.Type.WindowStateChange:
            self._sync_motion()
        return super().eventFilter(watched, event)

    def _advance(self):
        now = time.monotonic()
        elapsed = min(now - self._last_step, .25)
        self._last_step = now
        if now >= self._next_preference_check:
            self._animated = animations_enabled()
            self._next_preference_check = now + 2
            self.timer.setInterval(80 if self._animated else 2000)
        if self._animated:
            self.phase = (self.phase + elapsed * math.tau / 56) % math.tau
            self.update()

    @staticmethod
    def _glow(color, opacity):
        # Cache small radial textures: scaling them is cheaper than rebuilding large gradients each frame.
        pixmap = QPixmap(256, 256)
        pixmap.fill(Qt.GlobalColor.transparent)
        gradient = QRadialGradient(128, 128, 128)
        for position, strength in ((0, 1), (.35, .7), (.7, .22), (1, 0)):
            stop = QColor(color)
            stop.setAlphaF(opacity * strength)
            gradient.setColorAt(position, stop)
        painter = QPainter(pixmap)
        painter.fillRect(pixmap.rect(), gradient)
        painter.end()
        return pixmap

    def paintEvent(self, event):
        colors = colors_for(self)
        key = (colors["glow_warm"], colors["glow_pearl"])
        if key != self._glow_key:
            self._glows = tuple(self._glow(*glow) for glow in key)
            self._glow_key = key
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(colors["paper"]))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width, height = self.width(), self.height()
        size = max(width * .88, height * 1.10)
        drift = math.sin(self.phase)
        centers = ((width * (.12 + .055 * drift), height * (.12 + .035 * math.sin(self.phase * 2))),
                   (width * (.88 - .045 * drift), height * (.88 + .04 * math.cos(self.phase))))
        for glow, (x, y) in zip(self._glows, centers):
            target = QRectF(x - size / 2, y - size * .42, size, size * .84)
            painter.drawPixmap(target, glow, QRectF(glow.rect()))
        painter.end()
