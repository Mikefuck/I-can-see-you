"""Short, interruptible UI motion. Control values always change before their animation."""
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QPushButton, QStackedWidget,
    QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyledItemDelegate, QWidget,
)

from .ambient import animations_enabled
from .theme import colors_for


class MotionValue(QObject):
    """Retarget from the current frame instead of queuing animations on repeated input."""

    def __init__(self, widget, value=0.0, duration=180, parent=None):
        super().__init__(parent or widget)
        self.widget, self.value, self.target = widget, float(value), float(value)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._update)
        widget.destroyed.connect(self.animation.stop)
        widget.installEventFilter(self)

    def _update(self, value):
        self.value = float(value)
        self.widget.update()

    def to(self, target):
        self.animation.stop()
        self.target = float(target)
        if not self.widget.isVisible() or not animations_enabled():
            self._update(self.target)
            return
        self.animation.setStartValue(self.value)
        self.animation.setEndValue(self.target)
        self.animation.start()

    def jump(self, value):
        self.animation.stop()
        self.target = float(value)
        self._update(value)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Hide:
            self.animation.stop()
            self._update(self.target)
        return False


class _PageFrame(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.before, self.after = QPixmap(), QPixmap()
        self.progress, self.direction = 0.0, 1
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(colors_for(self)["paper"]))
        # Twelve logical pixels communicate direction without moving the actual layout or focus.
        painter.setOpacity(1 - self.progress)
        painter.drawPixmap(QPointF(-12 * self.direction * self.progress, 0), self.before)
        painter.setOpacity(self.progress)
        painter.drawPixmap(QPointF(12 * self.direction * (1 - self.progress), 0), self.after)


class PageStack(QStackedWidget):
    """Animate cached frames; the live destination is already usable underneath."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = _PageFrame(self)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(220)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self.finish_transition)
        QApplication.instance().installEventFilter(self)

    def setCurrentIndex(self, index):
        if index == self.currentIndex() or not 0 <= index < self.count():
            return
        animate = self.isVisible() and animations_enabled() and self.currentWidget() is not None
        previous = self.currentIndex()
        before = self.grab() if animate else QPixmap()
        self.finish_transition()
        super().setCurrentIndex(index)
        if not animate:
            return
        self.layout().activate()
        self.frame.before, self.frame.after = before, self.grab()
        self.frame.direction = 1 if index > previous else -1
        self.frame.progress = 0.0
        self.frame.setGeometry(self.rect())
        self.frame.show()
        self.frame.raise_()
        self.animation.start()

    def setCurrentWidget(self, widget):
        self.setCurrentIndex(self.indexOf(widget))

    def _advance(self, value):
        self.frame.progress = float(value)
        self.frame.update()

    def finish_transition(self):
        self.animation.stop()
        self.frame.hide()
        self.frame.before, self.frame.after = QPixmap(), QPixmap()

    def eventFilter(self, watched, event):
        # A live control must never respond behind an obsolete snapshot, even on a very fast click.
        if (self.frame.isVisible() and isinstance(watched, QWidget)
                and (watched is self or self.isAncestorOf(watched))
                and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel)):
            self.finish_transition()
        return False

    def resizeEvent(self, event):
        self.finish_transition()
        super().resizeEvent(event)

    def hideEvent(self, event):
        self.finish_transition()
        super().hideEvent(event)


class MotionCheckBox(QCheckBox):
    """Keep Qt's keyboard/accessibility semantics, with a filling box and drawn check."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selection = MotionValue(self)
        self.toggled.connect(lambda checked: self.selection.to(int(checked)))

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        label = QStyleOptionButton(option)
        label.rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, option, self)
        self.style().drawControl(QStyle.ControlElement.CE_CheckBoxLabel, label, painter, self)
        rect = QRectF(self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)).adjusted(1, 1, -1, -1)
        draw_check(painter, rect, colors_for(self), self.selection.value, self.isEnabled(), self.hasFocus())


def draw_check(painter, rect, colors, progress, enabled=True, focused=False):
    painter.save()
    ink = QColor(colors["ink"] if enabled else colors["faded"])
    paper = QColor(colors["paper"])
    fill = QColor.fromRgbF(*(a + (b - a) * progress for a, b in zip(paper.getRgbF()[:3], ink.getRgbF()[:3])))
    painter.setPen(QPen(QColor(colors["red"]) if focused else ink, 2))
    painter.setBrush(fill)
    painter.drawRect(rect)
    if progress > 0:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        points = [QPointF(rect.x() + rect.width() * x, rect.y() + rect.height() * y)
                  for x, y in ((.20, .52), (.43, .75), (.82, .25))]
        path = QPainterPath(points[0])
        first = min(1.0, progress / .35)
        path.lineTo(points[0] + (points[1] - points[0]) * first)
        if progress > .35:
            path.lineTo(points[1] + (points[2] - points[1]) * ((progress - .35) / .65))
        painter.setPen(QPen(paper, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.restore()


class CheckDelegate(QStyledItemDelegate):
    """Animate the process picker's check column while retaining Qt's item editing behavior."""

    def __init__(self, table):
        super().__init__(table)
        self.table, self.values = table, {}
        table.model().dataChanged.connect(self._changed)
        table.model().modelReset.connect(self._reset)
        table.model().rowsRemoved.connect(self._reset)

    def _reset(self, *_):
        for value in self.values.values():
            value.animation.stop()
            value.deleteLater()
        self.values.clear()

    def _changed(self, top, bottom, roles):
        if top.column() > 0 or (roles and Qt.ItemDataRole.CheckStateRole not in roles):
            return
        for row in range(top.row(), bottom.row() + 1):
            if row in self.values:
                checked = self.table.model().index(row, 0).data(Qt.ItemDataRole.CheckStateRole)
                self.values[row].to(int(checked == Qt.CheckState.Checked.value))

    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        style = self.table.style()
        rect = QRectF(style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self.table)).adjusted(1, 1, -1, -1)
        option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, self.table)
        if index.row() not in self.values:
            self.values[index.row()] = MotionValue(self.table.viewport(), int(option.checkState == Qt.CheckState.Checked), parent=self)
        draw_check(painter, rect, colors_for(self.table), self.values[index.row()].value,
                   bool(option.state & QStyle.StateFlag.State_Enabled))


class MotionButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.press = MotionValue(self, duration=130)
        self.pressed.connect(lambda: self.press.jump(1))
        self.released.connect(lambda: self.press.to(0))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.press.value and self.isEnabled():
            painter = QPainter(self)
            color = QColor(colors_for(self)["red"])
            color.setAlphaF(.16 * self.press.value)
            painter.fillRect(self.rect().adjusted(2, 2, -2, -2), color)


class MotionComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selection = MotionValue(self, duration=220)
        self.activated.connect(self._selected)

    def _selected(self, index):
        self.selection.jump(1.0)
        self.selection.to(0)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.selection.value:
            painter = QPainter(self)
            color = QColor(colors_for(self)["red"])
            color.setAlphaF(.12 * self.selection.value)
            painter.fillRect(self.rect(), color)
