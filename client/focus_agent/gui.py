import bisect
import logging
import tempfile
import time
import uuid
import webbrowser
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from queue import Empty
from string import Template

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QSystemTrayIcon, QTableWidget,
    QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from . import __version__
from .config import save_config
from .network import Uploader, check_connection
from .store import PENDING, SENT
from .tracker import SessionTracker
from .winapi import BatteryReader, ForegroundReader, SystemEventWindow, encrypt, set_startup, startup_enabled


STATUS_REASONS = {"startup": "程序启动", "periodic": "电池采样", "shutdown": "关机前",
                  "suspend": "睡眠 / 休眠前", "resume": "唤醒恢复"}
# Lifecycle nodes on the day strip, read like a timetable: ▲ the machine came on, ▼ it went off.
DAY_MARKS = {"startup": True, "resume": True, "shutdown": False, "suspend": False}
WEEKDAYS = "一二三四五六日"


# Swiss / International Typographic Style, set as a railway timetable: white paper, black type and rules on a
# two-column grid (hanging section labels, content to their right), and one signal red reserved for what is
# live: the recording lamp, the session still being recorded, the action to take next and keyboard focus.
INK, PAPER, RED = "#101010", "#ffffff", "#eb0000"
GRAPHITE, RULE, FIELD, FADED = "#5e5e5e", "#d0d0d0", "#f0f0f0", "#a3a3a3"

# Latin text comes from the first grotesque that is installed, Chinese falls through to YaHei. Times, counts and
# the hour scale use Bahnschrift, whose DIN figures are the ones on station signage.
UI_FONTS = ["Helvetica Neue", "Helvetica", "Arial", "Microsoft YaHei UI"]
FIGURE_FONTS = ["Bahnschrift", "Arial", "Microsoft YaHei UI"]

# The grid: outer margin, the column that holds the hanging section labels, and the gutter beside it.
MARGIN, LABEL_COLUMN, GUTTER = 32, 148, 24

# QSS can only draw arrows and check marks from files, so these small SVGs are written to a temp directory.
GLYPHS = {
    "arrow-up": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6"><path d="M0 6L5 0L10 6Z" fill="%s"/></svg>' % INK,
    "arrow-down": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6"><path d="M0 0L10 0L5 6Z" fill="%s"/></svg>' % INK,
    "check": '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><path d="M2 6.5L5 9.5L10.5 2.5" fill="none" '
             'stroke="%s" stroke-width="2"/></svg>' % PAPER,
}


def glyph_directory():
    directory = Path(tempfile.gettempdir()) / "focus-ledger-ui"
    directory.mkdir(exist_ok=True)
    for name, svg in GLYPHS.items():
        path = directory / (name + ".svg")
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
    return directory.as_posix()


# Buttons take their emphasis from the "primary" property, not from object names: a #id selector would outrank
# the :hover / :focus rules. Labels that show figures get their font in code (see figure_font), because QSS keeps
# only the first font family and would drop the Chinese fallback.
STYLE = Template("""
QMainWindow,QWidget#root,QWidget#page,QScrollArea#scroll{background:$paper;border:0;}
QWidget{color:$ink;}
QLabel{background:transparent;}
QDialog,QMessageBox{background:$paper;}
QToolTip{background:$ink;color:$paper;border:0;padding:6px 8px;}

QFrame#heavyRule{background:$ink;border:0;}
QFrame#rule{background:$ink;border:0;}
QFrame#hairline{background:$rule;border:0;}
QFrame#section{border:0;border-top:1px solid $ink;}
QFrame#section[first="true"]{border-top:0;}

QLabel#wordmark{font-size:17px;font-weight:700;}
QLabel#edition,QLabel#sectionEnglish{color:$graphite;}
QLabel#stateWord{font-size:30px;font-weight:700;}
QLabel#stateWord[state="error"]{color:$red;}
QLabel#stateDetail{font-size:12px;color:$graphite;}
QLabel#sectionTitle{font-size:17px;font-weight:700;}
QLabel#caption{font-size:11px;font-weight:700;color:$graphite;}
QLabel#value{font-size:14px;font-weight:700;}
QLabel#meta,QLabel#hint{font-size:12px;color:$graphite;}
QLabel#unsaved{font-size:12px;font-weight:700;}

QLineEdit,QSpinBox,QComboBox{background:$field;border:0;border-bottom:2px solid $ink;border-radius:0;padding:7px 10px;min-height:22px;selection-background-color:$ink;selection-color:$paper;}
QLineEdit:focus,QSpinBox:focus,QComboBox:focus{border-bottom-color:$red;}
QLineEdit:disabled,QSpinBox:disabled,QComboBox:disabled{color:$faded;border-bottom-color:$rule;}
QSpinBox{padding:7px 0 7px 10px;}
QSpinBox QLineEdit{background:transparent;border:0;padding:0 0 0 10px;}
QSpinBox::up-button,QSpinBox::down-button{subcontrol-origin:padding;width:26px;border:0;background:transparent;}
QSpinBox::up-button{subcontrol-position:top right;}
QSpinBox::down-button{subcontrol-position:bottom right;}
QSpinBox::up-button:hover,QSpinBox::down-button:hover{background:$rule;}
QSpinBox::up-arrow{image:url("$glyphs/arrow-up.svg");width:9px;height:5px;}
QSpinBox::down-arrow{image:url("$glyphs/arrow-down.svg");width:9px;height:5px;}
QComboBox::drop-down{subcontrol-origin:padding;subcontrol-position:center right;width:28px;border:0;}
QComboBox::down-arrow{image:url("$glyphs/arrow-down.svg");width:9px;height:5px;}
QComboBox QAbstractItemView{background:$paper;border:2px solid $ink;selection-background-color:$ink;selection-color:$paper;outline:0;}
QComboBox QAbstractItemView::item{min-height:30px;padding-left:10px;}
QComboBox QAbstractItemView::item:selected{background:$ink;color:$paper;}

QPushButton{background:$paper;color:$ink;border:2px solid $ink;border-radius:0;padding:8px 18px;font-weight:700;min-height:20px;}
QPushButton:hover{background:$ink;color:$paper;}
QPushButton:focus{border-color:$red;}
QPushButton:disabled{color:$faded;border-color:$rule;background:$paper;}
QPushButton[primary="true"]{background:$red;color:$paper;border-color:$red;}
QPushButton[primary="true"]:hover{background:$ink;border-color:$ink;}
QPushButton[primary="true"]:focus{border-color:$ink;}
QPushButton[primary="true"]:disabled{background:$rule;color:$faded;border-color:$rule;}
QPushButton#link{background:transparent;color:$ink;border:0;padding:2px 0;min-height:0;font-weight:400;text-align:left;text-decoration:underline;}
QPushButton#link:hover,QPushButton#link:focus{background:transparent;color:$red;}

QCheckBox{spacing:12px;padding:4px 0;}
QCheckBox::indicator{width:16px;height:16px;border:2px solid $ink;background:$paper;}
QCheckBox::indicator:checked{background:$ink;image:url("$glyphs/check.svg");}
QCheckBox::indicator:focus{border-color:$red;}

QTableWidget{background:transparent;border:0;outline:0;gridline-color:transparent;selection-background-color:$field;selection-color:$ink;}
QTableWidget::item{padding:0 12px 0 0;border-bottom:1px solid $rule;}
QTableWidget::item:selected{background:$field;color:$ink;}
QTableWidget QLineEdit{border-bottom-color:$red;padding:0 8px;min-height:0;}
QHeaderView{background:transparent;border:0;}
QHeaderView::section{background:transparent;color:$graphite;border:0;border-bottom:1px solid $ink;padding:6px 12px 6px 3px;font-size:11px;font-weight:700;}

QScrollBar:vertical{background:transparent;width:8px;margin:0;}
QScrollBar::handle:vertical{background:#c4c4c4;min-height:36px;}
QScrollBar::handle:vertical:hover{background:$ink;}
QScrollBar:horizontal{background:transparent;height:8px;margin:0;}
QScrollBar::handle:horizontal{background:#c4c4c4;min-width:36px;}
QScrollBar::handle:horizontal:hover{background:$ink;}
QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0;}
QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}

QMenu{background:$paper;color:$ink;border:2px solid $ink;padding:4px 0;}
QMenu::item{padding:8px 28px;}
QMenu::item:selected{background:$ink;color:$paper;}
QMenu::separator{height:1px;background:$rule;margin:4px 0;}
""")


def stylesheet():
    return STYLE.substitute(ink=INK, paper=PAPER, red=RED, graphite=GRAPHITE, rule=RULE, field=FIELD, faded=FADED,
                            glyphs=glyph_directory())


def apply_typography(app):
    font = QFont()
    font.setFamilies(UI_FONTS)
    font.setPixelSize(13)
    app.setFont(font)


def figure_font(size, weight=QFont.Weight.Normal):
    font = QFont()
    font.setFamilies(FIGURE_FONTS)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def restyle(widget):
    """Re-apply the stylesheet after a property used in a selector has changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def icon_image(size, active=True):
    """Three flush-left ledger lines on a red (recording) or grey (paused) square, drawn on a 16-unit grid."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    unit = size / 16
    painter.fillRect(QRectF(0, 0, size, size), QColor(RED if active else GRAPHITE))
    for row, length in ((4, 10), (7, 6), (10, 8)):
        painter.fillRect(QRectF(3 * unit, row * unit, length * unit, 2 * unit), QColor(PAPER))
    painter.end()
    return image


def app_icon(active=True):
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 256):
        icon.addPixmap(QPixmap.fromImage(icon_image(size, active)))
    return icon


class StatusLamp(QWidget):
    """Signal lamp hanging in the margin: solid red while recording, an outline when paused, solid ink on failure."""

    def __init__(self):
        super().__init__()
        self.state = "stopped"
        self.setFixedSize(22, 22)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.state == "stopped":
            painter.setPen(QPen(QColor(INK), 2))
            painter.drawRect(QRectF(1, 1, 20, 20))
        else:
            painter.fillRect(self.rect(), QColor(RED if self.state == "running" else INK))
        painter.end()


class NavTab(QAbstractButton):
    """Masthead page switch. The current page's bar rests on the masthead rule; a red square flags unsaved edits."""

    BAR = 4

    def __init__(self, text):
        super().__init__()
        self.setText(text)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.flagged = False
        font = QFont()
        font.setPixelSize(15)
        font.setBold(True)
        self.setFont(font)

    def set_flagged(self, flagged):
        self.flagged = flagged
        self.update()

    def sizeHint(self):
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 12, 54)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        width = metrics.horizontalAdvance(self.text())
        text_height = self.height() - self.BAR
        color = RED if self.hasFocus() else INK if self.isChecked() or self.underMouse() else GRAPHITE
        painter.setFont(self.font())
        painter.setPen(QColor(color))
        painter.drawText(QRectF(0, 0, width + 2, text_height), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.text())
        if self.isChecked():
            painter.fillRect(QRectF(0, text_height, width, self.BAR), QColor(INK))
        if self.flagged:
            top = (text_height - metrics.capHeight()) / 2 - 1
            painter.fillRect(QRectF(width + 3, top, 6, 6), QColor(RED))
        painter.end()


class DayStrip(QWidget):
    """Today on a 24-hour scale, read like a timetable: recorded time as ink blocks between hour lines, the session
    still being recorded in red up to the "now" line, and ▲ / ▼ where the machine came on or went off."""

    SCALE, BAR, MARKS = 18, 30, 16  # heights of the hour figures, the bar and the row of lifecycle marks

    def __init__(self):
        super().__init__()
        self.day = (0.0, 86400.0)
        self.segments = []  # (start, end, app name, process name), oldest first
        self.starts = []
        self.marks = []  # (moment, came on)
        self.live = None  # start of the segment that is still open
        self.now = 0.0
        self.recording = False
        self.figures = figure_font(11)
        self.setMouseTracking(True)
        self.setMinimumWidth(24 * 10)
        self.setFixedHeight(self.SCALE + self.BAR + self.MARKS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_day(self, start, end, segments, marks):
        self.day = (start, end)
        self.segments = sorted(segments)
        self.starts = [segment[0] for segment in self.segments]
        self.marks = marks
        self.update()

    def set_live(self, start, now, recording):
        self.live, self.now, self.recording = start, now, recording
        self.update()

    def x_at(self, moment):
        start, end = self.day
        return (moment - start) / (end - start) * (self.width() - 1)

    def moment_at(self, x):
        start, end = self.day
        return start + x / max(self.width() - 1, 1) * (end - start)

    def pixel_seconds(self):
        start, end = self.day
        return (end - start) / max(self.width() - 1, 1)

    def blocks(self):
        """Merge segments less than a pixel apart into the blocks that are drawn; the last flag marks the live one."""
        tolerance = self.pixel_seconds()
        items = [(start, end) for start, end, *_ in self.segments]
        if self.recording and self.live is not None:
            items.append((max(self.live, self.day[0]), self.now))
        merged = []
        for start, end in sorted(items):
            if merged and start - merged[-1][1] <= tolerance:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        live_from = self.now - tolerance - 2
        return [(start, end, self.recording and self.live is not None and end >= live_from) for start, end in merged]

    def paintEvent(self, event):
        painter = QPainter(self)
        width = self.width() - 1
        top, bottom = self.SCALE, self.SCALE + self.BAR
        painter.setFont(self.figures)
        for hour in range(25):
            x = round(hour * width / 24)
            if hour % 3:
                painter.fillRect(x, top, 1, self.BAR, QColor(RULE))
                continue
            painter.fillRect(x, 2, 1, bottom - 2, QColor(FADED))
            text = QRectF(x + 4, 0, 30, top - 4) if hour < 24 else QRectF(x - 34, 0, 30, top - 4)
            align = Qt.AlignmentFlag.AlignLeft if hour < 24 else Qt.AlignmentFlag.AlignRight
            painter.setPen(QColor(GRAPHITE))
            painter.drawText(text, align | Qt.AlignmentFlag.AlignTop, str(hour))
        for start, end, live in self.blocks():
            left = round(self.x_at(start))
            painter.fillRect(left, top, max(round(self.x_at(end)) - left, 1), self.BAR, QColor(RED if live else INK))
        painter.fillRect(0, bottom, width + 1, 1, QColor(INK))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(INK))
        for moment, came_on in self.marks:
            x = self.x_at(moment)
            tip, base = (bottom + 4, bottom + 11) if came_on else (bottom + 11, bottom + 4)
            painter.drawPolygon(QPolygonF([QPointF(x, tip), QPointF(x - 4, base), QPointF(x + 4, base)]))
        if self.day[0] <= self.now < self.day[1]:
            painter.fillRect(QRectF(round(self.x_at(self.now)) - 1, 2, 2, bottom + 3),
                             QColor(RED if self.recording else GRAPHITE))
        painter.end()

    def run_at(self, index):
        """Join the 30-second segments around index that belong to one app without a break."""
        start, end, *app = self.segments[index]
        first = last = index
        while first > 0 and self.segments[first - 1][2:] == tuple(app) and start - self.segments[first - 1][1] <= 2:
            first -= 1
            start = self.segments[first][0]
        while last + 1 < len(self.segments) and self.segments[last + 1][2:] == tuple(app) and \
                self.segments[last + 1][0] - end <= 2:
            last += 1
            end = self.segments[last][1]
        return start, end, app

    def describe(self, x, y):
        moment, tolerance = self.moment_at(x), self.pixel_seconds() * 2
        stamp = lambda value, pattern="%H:%M:%S": datetime.fromtimestamp(value).strftime(pattern)
        if y >= self.SCALE + self.BAR:
            near = [(abs(self.x_at(m) - x), m, on) for m, on in self.marks if abs(self.x_at(m) - x) <= 6]
            if near:
                _, mark, came_on = min(near)
                reason = "开机 / 唤醒" if came_on else "关机 / 睡眠"
                return f"{stamp(mark, '%H:%M')}  {reason}"
            return ""
        if self.recording and self.live is not None and self.live - tolerance <= moment <= self.now + tolerance:
            return f"正在记录  {stamp(self.live)} 起"
        index = bisect.bisect_right(self.starts, moment + tolerance) - 1
        for candidate in (index, index - 1):
            if 0 <= candidate < len(self.segments) and \
                    self.segments[candidate][0] - tolerance <= moment <= self.segments[candidate][1] + tolerance:
                start, end, (name, process) = self.run_at(candidate)
                return f"{name}\n{process}  {stamp(start)}–{stamp(end)}"
        return ""

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            text = self.describe(event.pos().x(), event.pos().y())
            if text:
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)


class ConnectionJob(QObject):
    finished = Signal(object, str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            self.finished.emit(check_connection(self.config), "")
        except Exception as exc:
            self.finished.emit(None, str(exc))


def battery_summary(status):
    fields = ("battery_percent", "charging", "ac_online", "battery_life_seconds")
    if all(status.get(field) is None for field in fields):
        return "未记录电池信息"
    percent = status.get("battery_percent")
    parts = ["未检测到电池"] if percent is None else [f"电量 {percent}%"]
    if status.get("charging"):
        parts.append("充电中")
    if status.get("ac_online") is True:
        parts.append("交流电源")
    elif status.get("ac_online") is False:
        parts.append("电池供电")
    life = status.get("battery_life_seconds")
    if life and status.get("ac_online") is False:
        parts.append(f"预计剩余 {life // 3600} 小时 {life % 3600 // 60} 分")
    return " · ".join(parts)


class MainWindow(QMainWindow):
    LEDGER, SETTINGS = 0, 1

    def __init__(self, config, config_path, store):
        super().__init__()
        self.config, self.config_path, self.store = config, config_path, store
        self.reader = ForegroundReader()
        if hasattr(self.reader, "set_aliases"):
            self.reader.set_aliases(config.app_aliases)
        self.battery_reader = BatteryReader()
        self.tracker = SessionTracker()
        self.running = False
        self.quitting = False
        self.job_thread = None
        self.job = None
        self.job_result = None
        self.job_candidate = None
        self.job_saving = False
        self.last_refresh = 0
        self.last_battery = 0
        self.last_power_check = 0
        self.last_power_source = None
        self.last_app = None
        self.retry_sampling_at = 0
        self.startup_recorded = False
        self.shutdown_saved = False
        self.suspended = False
        self.suspended_at = 0.0
        self.last_resume = -60.0
        self.day_recorded = 0.0
        self.dirty = False
        self.setWindowTitle("专注记录 · Focus Ledger")
        self.setWindowIcon(app_icon())
        self.resize(1080, 820)
        self.setMinimumSize(860, 560)
        self.setStyleSheet(stylesheet())
        self._build_ui()
        self._build_tray()
        self._populate()
        self._watch_settings()
        self.set_state("stopped", "尚未开始采集")
        self.show_page(self.LEDGER if config.configured else self.SETTINGS)
        self.uploader = Uploader(store, config)
        self.uploader.start()
        try:
            self.system_events = SystemEventWindow(self.handle_system_event)
        except Exception:
            self.system_events = None
            logging.exception("Unable to listen for shutdown and power events")
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.about_to_quit)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.refresh_history()
        if config.configured:
            self.start_collection()

    # ---- layout -------------------------------------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_masthead())
        layout.addWidget(self._build_state_band())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._scrolling(self._build_ledger_page()))
        self.pages.addWidget(self._build_settings_page())
        layout.addWidget(self.pages, 1)
        # Focus rings are for keyboard navigation: a mouse click should not leave a button or box marked.
        for control in self.findChildren(QPushButton) + self.findChildren(QCheckBox):
            control.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # The window itself holds the initial focus, so nothing is ringed until the user presses Tab.
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        root.setFocus()
        # QSS padding does not reach the line edit inside a spin box; align its text with the other fields.
        for spin in self.findChildren(QSpinBox):
            spin.lineEdit().setTextMargins(10, 0, 0, 0)
        save = QShortcut(QKeySequence("Ctrl+S"), self)
        save.activated.connect(lambda: self.connection_job(True))

    def _build_masthead(self):
        """Wordmark on the left, the two pages on the right, a heavy rule beneath that the current tab rests on."""
        head = QWidget()
        layout = QVBoxLayout(head)
        layout.setContentsMargins(MARGIN, 0, MARGIN, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(0)
        row.setContentsMargins(0, 0, 0, 0)
        wordmark = QLabel("专注记录")
        wordmark.setObjectName("wordmark")
        wordmark.setFixedWidth(LABEL_COLUMN + GUTTER)
        edition = QLabel(f"Focus Ledger  {__version__}")
        edition.setObjectName("edition")
        edition.setFont(figure_font(13))
        for label in (wordmark, edition):
            label.setContentsMargins(0, 0, 0, NavTab.BAR)
            row.addWidget(label)
        row.addStretch()
        self.ledger_tab, self.settings_tab = NavTab("记录"), NavTab("设置")
        for page, tab in enumerate((self.ledger_tab, self.settings_tab)):
            tab.clicked.connect(lambda checked=False, page=page: self.show_page(page))
            row.addSpacing(28)
            row.addWidget(tab)
        layout.addLayout(row)
        layout.addWidget(self._rule("heavyRule", 3))
        return head

    def _build_state_band(self):
        """The state of the agent, visible on every page: lamp in the margin, state word, and the two actions."""
        band = QWidget()
        outer = QVBoxLayout(band)
        outer.setContentsMargins(MARGIN, 0, MARGIN, 0)
        outer.setSpacing(0)
        grid = QGridLayout()
        grid.setContentsMargins(0, 18, 0, 18)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(2)
        grid.setColumnMinimumWidth(0, LABEL_COLUMN + GUTTER)
        grid.setColumnStretch(1, 1)
        self.lamp = StatusLamp()
        grid.addWidget(self.lamp, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status = QLabel("尚未开始采集")
        self.status.setObjectName("stateWord")
        grid.addWidget(self.status, 0, 1)
        self.status_detail = QLabel()
        self.status_detail.setObjectName("stateDetail")
        self.status_detail.setWordWrap(True)
        grid.addWidget(self.status_detail, 1, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.toggle = QPushButton("开始采集")
        self.toggle.clicked.connect(self.toggle_collection)
        upload = QPushButton("立即上传")
        upload.clicked.connect(lambda: self.upload_now())
        actions.addWidget(self.toggle)
        actions.addWidget(upload)
        grid.addLayout(actions, 0, 2, 2, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(grid)
        outer.addWidget(self._rule("rule", 1))
        return band

    def _build_ledger_page(self):
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(MARGIN, 0, MARGIN, 12)
        layout.setSpacing(0)

        section, content, _ = self._section("今日", "Today", first=True)
        head = QGridLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setVerticalSpacing(0)
        head.addWidget(self._label("caption", "已记录"), 0, 0)
        self.day_total = QLabel("0:00:00")
        self.day_total.setFont(figure_font(34, QFont.Weight.DemiBold))
        head.addWidget(self.day_total, 1, 0)
        self.day_date = QLabel()
        self.day_date.setObjectName("meta")
        head.addWidget(self.day_date, 1, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        head.setColumnStretch(0, 1)
        content.addLayout(head)
        content.addSpacing(6)
        self.day = DayStrip()
        content.addWidget(self.day)
        layout.addWidget(section)

        section, content, _ = self._section("状态", "Status")
        self.current_app = QLabel("—")
        self.current_app.setObjectName("value")
        self.current_process = QLabel()
        self.current_process.setObjectName("meta")
        self.current_process.hide()
        self.upload_status = QLabel("等待配置")
        self.cache_status = QLabel("0 条")
        self.battery_status = QLabel("—")
        readouts = QGridLayout()
        readouts.setHorizontalSpacing(GUTTER)
        readouts.setVerticalSpacing(4)
        for column, (caption, values) in enumerate([("当前应用", [self.current_app, self.current_process]),
                                                    ("上传状态", [self.upload_status]),
                                                    ("待上传缓存", [self.cache_status]),
                                                    ("电池状态", [self.battery_status])]):
            readouts.setColumnStretch(column, 1)
            readouts.addWidget(self._label("caption", caption), 0, column)
            stack = QVBoxLayout()
            stack.setSpacing(2)
            for value in values:
                value.setWordWrap(True)
                stack.addWidget(value)
            stack.addStretch()
            readouts.addLayout(stack, 1, column)
        content.addLayout(readouts)
        layout.addWidget(section)

        section, content, aside = self._section("最近记录", "Recent")
        layout.addWidget(section, 1)
        aside.insertWidget(2, self._label("hint", "已上传的保留 7 天，未上传的最多保留 30 天 / 100,000 条。"
                                                  "双击应用行可为它添加名称翻译。", 12))
        clear = QPushButton("清空未上传缓存")
        clear.setObjectName("link")
        clear.clicked.connect(self.clear_pending)
        aside.addWidget(clear)
        self.history_empty = self._label("hint", "还没有记录。开始采集后，每一段前台应用使用都会出现在这里。")
        self.history_empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        content.addWidget(self.history_empty)
        self.history = self._ledger_table(5, ["应用名称", "进程名", "结束时间", "时长 / 状态", "上传"])
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.history.horizontalHeader()
        for column, mode in enumerate((QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.ResizeToContents)):
            header.setSectionResizeMode(column, mode)
        self.history.setMinimumHeight(240)
        self.history.cellDoubleClicked.connect(self.alias_from_history)
        content.addWidget(self.history, 1)
        return page

    def _build_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        body = QWidget()
        body.setObjectName("page")
        sections = QVBoxLayout(body)
        sections.setContentsMargins(MARGIN, 0, MARGIN, 12)
        sections.setSpacing(0)
        sections.addWidget(self._connection_section())
        sections.addWidget(self._collection_section())
        sections.addWidget(self._aliases_section())
        sections.addWidget(self._scope_section())
        sections.addStretch()
        self.settings_scroll = self._scrolling(body)
        layout.addWidget(self.settings_scroll, 1)
        layout.addWidget(self._build_footer())
        return page

    def _build_footer(self):
        """Saving applies every setting at once, so its bar stays in view while the settings scroll."""
        footer = QWidget()
        outer = QVBoxLayout(footer)
        outer.setContentsMargins(MARGIN, 0, MARGIN, 16)
        outer.setSpacing(0)
        outer.addWidget(self._rule("heavyRule", 3))
        grid = QGridLayout()
        grid.setContentsMargins(0, 14, 0, 0)
        grid.setHorizontalSpacing(0)  # a hidden column would drop its spacing; the width below holds the gutter
        grid.setVerticalSpacing(8)
        self.unsaved = self._label("unsaved", "有未保存的更改")
        self.unsaved.setFixedWidth(LABEL_COLUMN)
        self.unsaved.hide()
        grid.setColumnMinimumWidth(0, LABEL_COLUMN + GUTTER)
        grid.addWidget(self.unsaved, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.save_button = QPushButton("保存设置")
        self.save_button.setProperty("primary", True)
        self.save_button.clicked.connect(lambda: self.connection_job(True))
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(lambda: self.connection_job(False))
        dashboard = QPushButton("打开服务端网页")
        dashboard.clicked.connect(self.open_dashboard)
        actions.addWidget(self.save_button)
        actions.addWidget(self.test_button)
        actions.addWidget(dashboard)
        actions.addStretch()
        grid.addLayout(actions, 0, 1)
        self.connection_note = self._label("hint", "修改后点击「保存设置」或按 Ctrl+S 生效。")
        grid.addWidget(self.connection_note, 1, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)
        return footer

    @staticmethod
    def _scrolling(widget):
        area = QScrollArea()
        area.setObjectName("scroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        return area

    @staticmethod
    def _rule(name, height):
        rule = QFrame()
        rule.setObjectName(name)
        rule.setFixedHeight(height)
        return rule

    @staticmethod
    def _label(name, text, top=0):
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(name == "hint")
        label.setContentsMargins(0, top, 0, 0)
        return label

    @staticmethod
    def _section(title, english, first=False):
        """One row of the grid: the label hangs in the left column, the content runs to its right, a rule above.
        Returns the frame, the content layout and the label column (so a section can add notes under its title)."""
        frame = QFrame()
        frame.setObjectName("section")
        frame.setProperty("first", first)
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 18, 0, 28)
        row.setSpacing(GUTTER)
        holder = QWidget()
        holder.setFixedWidth(LABEL_COLUMN)
        aside = QVBoxLayout(holder)
        aside.setContentsMargins(0, 0, 0, 0)
        aside.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        subtitle = QLabel(english)
        subtitle.setObjectName("sectionEnglish")
        subtitle.setFont(figure_font(12))
        aside.addWidget(heading)
        aside.addWidget(subtitle)
        aside.addStretch()
        row.addWidget(holder)
        content = QVBoxLayout()
        content.setSpacing(10)
        row.addLayout(content, 1)
        return frame, content, aside

    @staticmethod
    def _six_columns():
        """Settings align to six equal columns of the content area: fields span 1, 2, 3, 4 or 6 of them."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        for column in range(6):
            grid.setColumnStretch(column, 1)
        return grid

    def _connection_section(self):
        frame, layout, _ = self._section("连接", "Connection", first=True)
        grid = self._six_columns()
        self.host = QLineEdit()
        self.host.setPlaceholderText("例如 192.168.1.10 或 focus.example.com")
        self.host.setMaxLength(253)
        self.protocol = QComboBox()
        self.protocol.addItems(["http", "https"])
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setMaxLength(256)
        self.key.setPlaceholderText("在服务器网页中生成的上传密钥")
        self.device_name = QLineEdit()
        self.device_name.setMaxLength(100)
        self.account = QLabel("尚未关联账户")
        self.account.setObjectName("value")
        self.account.setMinimumHeight(36)
        grid.addWidget(self._label("caption", "服务器 IP / 域名"), 0, 0, 1, 4)
        grid.addWidget(self.host, 1, 0, 1, 4)
        grid.addWidget(self._label("caption", "连接方式"), 0, 4)
        grid.addWidget(self.protocol, 1, 4)
        grid.addWidget(self._label("caption", "端口"), 0, 5)
        grid.addWidget(self.port, 1, 5)
        grid.addWidget(self._label("caption", "上传密钥", 12), 2, 0, 1, 6)
        grid.addWidget(self.key, 3, 0, 1, 6)
        grid.addWidget(self._label("caption", "设备名称", 12), 4, 0, 1, 4)
        grid.addWidget(self.device_name, 5, 0, 1, 4)
        grid.addWidget(self._label("caption", "所属账户", 12), 4, 4, 1, 2)
        grid.addWidget(self.account, 5, 4, 1, 2)
        layout.addLayout(grid)
        layout.addWidget(self._label("hint", "首次保存或更换连接时会验证密钥，避免将缓存上传到错误账户。"))
        return frame

    def _collection_section(self):
        frame, layout, _ = self._section("采集", "Collection")
        self.idle = QSpinBox()
        self.idle.setRange(0, 3600)
        self.idle.setSuffix(" 秒")
        self.idle.setSpecialValueText("关闭空闲检测")
        self.idle.setToolTip("默认无键鼠操作5分钟后暂停计时；0表示关闭。锁屏仍暂停。")
        self.interval = QSpinBox()
        self.interval.setRange(10, 300)
        self.interval.setSuffix(" 秒")
        self.battery_interval = QSpinBox()
        self.battery_interval.setRange(30, 3600)
        self.battery_interval.setSuffix(" 秒")
        grid = self._six_columns()
        for index, (caption, spin) in enumerate([("空闲暂停阈值", self.idle), ("上传间隔", self.interval),
                                                 ("电池状态间隔", self.battery_interval)]):
            grid.addWidget(self._label("caption", caption), 0, index * 2, 1, 2)
            grid.addWidget(spin, 1, index * 2, 1, 2)
        self.startup = QCheckBox("登录 Windows 后自动启动")
        self.silent = QCheckBox("静默启动（直接进入系统托盘）")
        self.silent.setToolTip("启动时不弹出主窗口，只显示托盘图标。再次运行程序或单击托盘图标可打开主窗口。")
        self.startup_note = self._label("hint", "")
        self.startup_note.setContentsMargins(32, 0, 0, 4)
        self.startup_note.hide()
        self.battery = QCheckBox("采集并上传电池状态")
        self.battery.setToolTip("按间隔记录电量、充电和电源状态；插拔电源时会立即补充一条记录。")
        self.battery.toggled.connect(self.battery_interval.setEnabled)
        self.shutdown_upload = QCheckBox("关机 / 注销前保存并尝试上传状态")
        self.suspend_upload = QCheckBox("睡眠 / 休眠前保存并尝试上传状态")
        self.shutdown_upload.setToolTip("先写入本地缓存，再在约3秒内尝试上传，不会阻止关机。")
        self.suspend_upload.setToolTip("Windows 只给约2秒处理时间；来不及上传的记录会在唤醒后补传。")
        for index, (caption, boxes) in enumerate([("启动", [self.startup, self.startup_note, self.silent]),
                                                  ("设备状态", [self.battery, self.shutdown_upload,
                                                               self.suspend_upload])]):
            column = QVBoxLayout()
            column.setSpacing(0)
            column.addWidget(self._label("caption", caption, 18))
            column.addSpacing(4)
            for box in boxes:
                column.addWidget(box)
            column.addStretch()
            grid.addLayout(column, 2, index * 3, 1, 3)
        layout.addLayout(grid)
        layout.addWidget(self._label("hint", "每秒采样前台应用。锁屏、睡眠及空闲时暂停计时；电源事件会先保存本地状态，再限时尝试上传。"
                                             "关闭窗口后继续在托盘运行。"))
        return frame

    def _ledger_table(self, columns, headers):
        """Table in the ledger style: flush-left columns, a rule under the header and hairlines between rows."""
        table = QTableWidget(0, columns)
        table.setHorizontalHeaderLabels(headers)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.horizontalHeader().setHighlightSections(False)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(34)
        return table

    def _aliases_section(self):
        frame, layout, _ = self._section("应用名翻译", "App names")
        layout.addWidget(self._label("hint", "按进程名匹配（不区分大小写，可省略 .exe），例如 chrome.exe → 浏览器；原始进程名仍会保留。"
                                     "在「记录」页双击最近记录可快速为该应用添加翻译，修改后保存设置生效。"))
        self.aliases = self._ledger_table(2, ["进程名", "自定义显示名"])
        self.aliases.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                     QAbstractItemView.EditTrigger.EditKeyPressed)
        self.aliases.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.fit_aliases()
        layout.addWidget(self.aliases)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        add_alias = QPushButton("添加翻译")
        add_alias.clicked.connect(lambda: self.add_alias())
        remove_alias = QPushButton("删除选中")
        remove_alias.clicked.connect(self.remove_alias)
        actions.addWidget(add_alias)
        actions.addWidget(remove_alias)
        actions.addStretch()
        layout.addLayout(actions)
        return frame

    def _scope_section(self):
        frame, layout, _ = self._section("数据范围", "Data")
        layout.addWidget(self._label("hint", "采集范围：应用名称、进程名、使用时长，以及设置允许的电池和系统状态。"
                                             "不采集窗口标题、截图、键盘输入或文件内容。密钥使用 Windows 账户加密存储。"))
        return frame

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(False), self)
        menu = QMenu(self)
        show = QAction("打开主窗口", self)
        show.triggered.connect(self.show_window)
        menu.addAction(show)
        self.tray_toggle = QAction("开始采集", self)
        self.tray_toggle.triggered.connect(self.toggle_collection)
        menu.addAction(self.tray_toggle)
        upload = QAction("立即上传", self)
        upload.triggered.connect(self.upload_now)
        menu.addAction(upload)
        menu.addSeparator()
        exit_action = QAction("退出程序", self)
        exit_action.triggered.connect(self.quit_app)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.setToolTip("专注记录 · 已暂停")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    # ---- settings -----------------------------------------------------------------------------------------------

    def _populate(self):
        config = self.config
        self.host.setText(config.host)
        self.port.setValue(config.port)
        self.protocol.setCurrentText(config.protocol)
        self.key.setText(config.api_key)
        self.device_name.setText(config.device_name)
        self.show_startup_state(config.startup)
        self.silent.setChecked(config.silent_start)
        self.idle.setValue(config.idle_seconds)
        self.interval.setValue(config.upload_seconds)
        self.battery.setChecked(config.battery_enabled)
        self.battery_interval.setValue(config.battery_seconds)
        self.battery_interval.setEnabled(config.battery_enabled)
        self.shutdown_upload.setChecked(config.upload_on_shutdown)
        self.suspend_upload.setChecked(config.upload_on_suspend)
        self.aliases.setRowCount(0)
        for process, display_name in sorted(config.app_aliases.items()):
            row = self.aliases.rowCount()
            self.aliases.insertRow(row)
            self.aliases.setItem(row, 0, QTableWidgetItem(process))
            self.aliases.setItem(row, 1, QTableWidgetItem(display_name))
        self.fit_aliases()
        self.account.setText(config.username or "尚未关联账户")

    def _watch_settings(self):
        """Any edit on the settings page flags it until the settings are saved. Connected after _populate, and
        only to signals that programmatic updates do not emit (spin boxes are filled before this)."""
        for edit in (self.host, self.key, self.device_name):
            edit.textEdited.connect(self.mark_dirty)
        self.protocol.activated.connect(self.mark_dirty)
        for spin in (self.port, self.idle, self.interval, self.battery_interval):
            spin.valueChanged.connect(self.mark_dirty)
        for box in (self.startup, self.silent, self.battery, self.shutdown_upload, self.suspend_upload):
            box.clicked.connect(self.mark_dirty)
        self.aliases.itemChanged.connect(self.mark_dirty)

    def mark_dirty(self, *_):
        self.set_dirty(True)

    def set_dirty(self, dirty):
        self.dirty = dirty
        self.settings_tab.set_flagged(dirty)
        self.unsaved.setVisible(dirty)

    def show_page(self, page):
        self.pages.setCurrentIndex(page)
        (self.ledger_tab, self.settings_tab)[page].setChecked(True)

    def show_startup_state(self, wanted):
        """Show what Windows will actually do, which can differ from the saved preference."""
        try:
            active = startup_enabled()
        except OSError:
            logging.exception("Unable to read the startup entry")
            active = wanted
        self.startup.setChecked(active)
        self.startup_note.setText("开机启动已在 Windows「启动应用」或任务管理器中被关闭；重新勾选并保存即可恢复。")
        self.startup_note.setVisible(wanted and not active)

    def fit_aliases(self):
        """Grow the table with its rows (two to six visible) instead of leaving an empty block."""
        rows = min(max(self.aliases.rowCount(), 2), 6)
        self.aliases.setFixedHeight(self.aliases.horizontalHeader().sizeHint().height() + rows * 34 + 2)

    def alias_row(self, process):
        for row in range(self.aliases.rowCount()):
            item = self.aliases.item(row, 0)
            if item is not None and item.text().strip().casefold() == process.casefold():
                return row
        return None

    def edit_alias(self, row, column):
        self.show_page(self.SETTINGS)
        self.settings_scroll.ensureWidgetVisible(self.aliases)
        self.aliases.setCurrentCell(row, column)
        self.aliases.editItem(self.aliases.item(row, column))

    def add_alias(self, process="", display_name=""):
        if not process:
            # Suggest the most recent application that has no translation yet.
            seen = [(self.last_app.process_name, self.last_app.app_name)] if self.last_app else []
            seen += [(event["process_name"], event["app_name"]) for event, _ in self.store.recent(self.config.destination)
                     if event.get("kind") == "app_usage"]
            process, display_name = next(((p, n) for p, n in seen if self.alias_row(p) is None), ("", ""))
        row = self.aliases.rowCount()
        self.aliases.insertRow(row)
        self.aliases.setItem(row, 0, QTableWidgetItem(process))
        self.aliases.setItem(row, 1, QTableWidgetItem(display_name))
        self.fit_aliases()
        self.edit_alias(row, 1 if process else 0)

    def alias_from_history(self, row, column):
        name, process = self.history.item(row, 0), self.history.item(row, 1)
        if name is None or process is None or name.data(Qt.ItemDataRole.UserRole) != "app_usage":
            return
        existing = self.alias_row(process.text())
        if existing is None:
            self.add_alias(process.text(), name.text())
        else:
            self.edit_alias(existing, 1)

    def remove_alias(self):
        rows = sorted({index.row() for index in self.aliases.selectedIndexes()}, reverse=True)
        for row in rows:
            self.aliases.removeRow(row)
        self.fit_aliases()
        if rows:
            self.mark_dirty()

    def collect_aliases(self):
        aliases = {}
        for row in range(self.aliases.rowCount()):
            process = self.aliases.item(row, 0)
            display_name = self.aliases.item(row, 1)
            if process and display_name and process.text().strip() and display_name.text().strip():
                key = process.text().strip().casefold()
                if key in aliases:
                    raise ValueError(f"应用名翻译中的进程名重复：{process.text().strip()}")
                aliases[key] = display_name.text().strip()
        return aliases

    def candidate(self):
        config = replace(self.config, host=self.host.text(), port=self.port.value(),
            protocol=self.protocol.currentText(), api_key=self.key.text().strip(), device_name=self.device_name.text(),
            startup=self.startup.isChecked(), silent_start=self.silent.isChecked(),
            idle_seconds=self.idle.value(), upload_seconds=self.interval.value(),
            battery_enabled=self.battery.isChecked(), battery_seconds=self.battery_interval.value(),
            upload_on_shutdown=self.shutdown_upload.isChecked(), upload_on_suspend=self.suspend_upload.isChecked(),
            app_aliases=self.collect_aliases())
        config.validate()
        return config

    def connection_job(self, saving):
        if self.job_thread is not None:
            return
        try:
            candidate = self.candidate()
        except ValueError as exc:
            QMessageBox.warning(self, "设置有误", str(exc))
            return
        connection_changed = (candidate.base_url, candidate.api_key) != (self.config.base_url, self.config.api_key)
        if saving and self.config.configured and not connection_changed:
            self.apply_config(candidate)
            return
        self.job_candidate, self.job_saving = candidate, saving
        self.job_result = None
        self.save_button.setEnabled(False)
        self.test_button.setEnabled(False)
        self.connection_note.setText("正在验证连接，请稍候…")
        self.job_thread = QThread(self)
        self.job = ConnectionJob(candidate)
        self.job.moveToThread(self.job_thread)
        self.job_thread.started.connect(self.job.run)
        self.job.finished.connect(self.connection_result)
        self.job.finished.connect(self.job_thread.quit)
        self.job.finished.connect(self.job.deleteLater)
        self.job_thread.finished.connect(self.connection_finished)
        self.job_thread.finished.connect(self.job_thread.deleteLater)
        self.job_thread.start()

    def connection_result(self, result, error):
        self.job_result = (result, error)

    def connection_finished(self):
        self.job_thread, self.job = None, None
        self.save_button.setEnabled(True)
        self.test_button.setEnabled(True)
        result, error = self.job_result or (None, "连接任务未完成")
        if error:
            self.connection_note.setText("验证失败：" + error)
            return
        candidate = self.job_candidate
        candidate.account_id, candidate.username = result["account_id"], result["username"]
        self.connection_note.setText(f"连接成功 · 账户 {candidate.username} · 服务端保留 {result['retention_days']} 天")
        if self.job_saving:
            if candidate.destination != self.config.destination:
                candidate.device_id = str(uuid.uuid4())
            self.apply_config(candidate)

    def apply_config(self, candidate):
        previous = self.config
        was_running = self.running
        try:
            if was_running:
                self.stop_collection()
            set_startup(candidate.startup)
            save_config(self.config_path, candidate, encrypt)
        except Exception as exc:
            try:
                set_startup(previous.startup)
            except Exception:
                logging.exception("Unable to restore startup configuration")
            if was_running and not self.running:
                self.start_collection()
            QMessageBox.warning(self, "保存失败", f"无法保存设置：{exc}")
            return
        self.config = candidate
        if hasattr(self.reader, "set_aliases"):
            self.reader.set_aliases(candidate.app_aliases)
        self.uploader.configure(candidate)
        self.account.setText(candidate.username)
        self.show_startup_state(candidate.startup)
        self.set_dirty(False)
        self.connection_note.setText("设置已保存。" + ("HTTP 连接适用于可信内网；公网请选择 HTTPS。" if candidate.protocol == "http" else "HTTPS 证书会进行验证。"))
        if was_running:
            self.start_collection()
        else:
            self.set_state("stopped", self.status.text())  # the hint and the start button now know the connection
        self.refresh_history()

    # ---- collection ---------------------------------------------------------------------------------------------

    def start_collection(self):
        if not self.config.configured:
            QMessageBox.information(self, "先连接服务器", "请填写服务器与密钥并保存设置，再开始采集。")
            self.show_window()
            self.show_page(self.SETTINGS)
            return
        self.tracker = SessionTracker()
        if hasattr(self.reader, "set_aliases"):
            self.reader.set_aliases(self.config.app_aliases)
        self.running = True
        self.retry_sampling_at = 0
        self.show_running_state()
        # One "startup" node per program start, not every time collection is resumed or settings are saved.
        if not self.startup_recorded and self.config.status_enabled:
            self.startup_recorded = self.record_status("startup")
        self.tick()

    def state_hint(self, state):
        if state == "running":
            return "每秒记录前台应用；锁屏、睡眠和空闲时暂停计时。关闭窗口后继续在托盘运行。"
        if not self.config.configured:
            return "先在「设置」中填写服务器和上传密钥，保存后即可开始采集。"
        return "已记录的数据保存在本地。点击「开始采集」继续记录。"

    def set_state(self, state, text, detail=""):
        """The lamp, the state word and which action is emphasised follow the state: running, stopped or error."""
        self.status.setText(text)
        self.status.setProperty("state", state)
        restyle(self.status)
        self.status_detail.setText(detail or self.state_hint(state))
        self.lamp.state = state
        self.lamp.update()
        # Starting is the next thing to do while paused; while recording, nothing is asked of the user.
        self.toggle.setProperty("primary", state == "stopped" and self.config.configured)
        restyle(self.toggle)

    def show_current(self, app, state):
        self.current_app.setText(app.app_name if app else state)
        self.current_process.setText(app.process_name if app else "")
        self.current_process.setVisible(app is not None)

    def show_running_state(self):
        self.set_state("running", "正在采集")
        self.toggle.setText("暂停采集")
        self.tray_toggle.setText("暂停采集")
        self.tray.setIcon(app_icon(True))
        self.tray.setToolTip("专注记录 · 正在采集")

    def save_open_segment(self):
        if self.running:
            self.store.add(self.config, self.tracker.stop(time.time(), time.monotonic()))
            self.tracker = SessionTracker()

    def stop_collection(self):
        self.save_open_segment()
        self.running = False
        self.toggle.setText("开始采集")
        self.set_state("stopped", "采集已暂停")
        self.show_current(None, "—")
        self.tray_toggle.setText("开始采集")
        self.tray.setIcon(app_icon(False))
        self.tray.setToolTip("专注记录 · 已暂停")
        self.refresh_history()

    def toggle_collection(self):
        self.stop_collection() if self.running else self.start_collection()

    def tick(self):
        now = time.monotonic()
        try:
            if self.suspended and now - self.suspended_at > 15:
                self.suspended = False  # running again even if the resume notification was missed
            if self.running and now >= self.retry_sampling_at:
                app, state = self.reader.sample(self.config.idle_seconds)
                if app:
                    self.last_app = app
                self.show_current(app, state)
                finished = self.tracker.observe(app, time.time(), now)
                self.store.add(self.config, finished)
                if finished:
                    self.refresh_day()  # the closed segment moves from the live count into the stored total
                if self.retry_sampling_at:
                    self.retry_sampling_at = 0
                    self.show_running_state()
            if now - self.last_power_check >= 5:
                self.check_power()
            while True:
                try:
                    ok, message = self.uploader.messages.get_nowait()
                    self.upload_status.setText(message)
                except Empty:
                    break
            if now - self.last_refresh >= 5:
                self.refresh_history()
            self.show_live()
        except Exception:
            logging.exception("Sampling/storage failed")
            # A locked or full disk is often temporary: keep the agent alive and retry instead of stopping for good.
            self.tracker = SessionTracker()
            self.retry_sampling_at = now + 30
            self.set_state("error", "采集出错", "本地读取或存储失败，30 秒后自动重试")
            self.tray.setToolTip("专注记录 · 采集出错，稍后重试")

    def refresh_day(self):
        """Reload today's records for the day strip and the recorded total."""
        today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today.timestamp()
        end = start + 86400
        segments, marks = [], []
        for event in self.store.between(self.config.destination, start, end):
            if event.get("kind") == "app_usage":
                segments.append((max(datetime.fromisoformat(event["started_at"]).timestamp(), start),
                                 datetime.fromisoformat(event["ended_at"]).timestamp(),
                                 event["app_name"], event["process_name"]))
            elif event.get("reason") in DAY_MARKS:
                marks.append((datetime.fromisoformat(event["occurred_at"]).timestamp(), DAY_MARKS[event["reason"]]))
        self.day_recorded = sum(end - start for start, end, *_ in segments)
        self.day.set_day(start, end, segments, marks)
        self.day_date.setText(f"{today.month} 月 {today.day} 日 · 星期{WEEKDAYS[today.weekday()]}")
        self.show_live()

    def show_live(self):
        """Advance the "now" line and add the segment that is still open to today's total."""
        now = time.time()
        if now >= self.day.day[1]:
            self.refresh_day()  # a new day has begun
            return
        live = self.tracker.start if self.running else None
        self.day.set_live(live, now, self.running)
        open_seconds = now - max(live, self.day.day[0]) if live is not None else 0
        self.day_total.setText(clock(self.day_recorded + max(open_seconds, 0)))

    def refresh_history(self):
        current, total = self.store.counts(self.config.destination)
        self.cache_status.setText(f"当前连接 {current} 条 · 总计 {total} 条" +
            ("（其他连接的缓存保持隔离，需切回原账户上传）" if total > current else ""))
        records = self.store.recent(self.config.destination)
        # Pending rows are set in bold ink, sent rows recede to grey, rejected rows turn red.
        states = {PENDING: ("待上传", INK, True), SENT: ("已上传", GRAPHITE, False)}
        self.history_empty.setVisible(not records)
        self.history.setVisible(bool(records))
        self.history.setRowCount(len(records))
        for row, (event, state) in enumerate(records):
            stamp = event.get("ended_at") or event.get("occurred_at")
            ended = datetime.fromisoformat(stamp).astimezone().strftime("%m-%d %H:%M:%S")
            if event.get("kind") == "device_status":
                values = ["设备状态", STATUS_REASONS.get(event.get("reason"), event.get("reason", "—")), ended,
                          battery_summary(event)]
            else:
                values = [event["app_name"], event["process_name"], ended, f"{event['duration_seconds']:.1f} 秒"]
            label, color, bold = states.get(state, ("服务器拒收", RED, True))
            values.append(label)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, event.get("kind"))
                if column == 2:
                    item.setFont(figure_font(13))
                if column == 4:
                    item.setForeground(QColor(color))
                    if bold:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                self.history.setItem(row, column, item)
        self.refresh_day()
        self.last_refresh = time.monotonic()

    def upload_now(self):
        self.save_open_segment()
        self.uploader.trigger()
        self.refresh_history()

    def check_power(self):
        """Refresh the battery display; record on schedule and right after the power source changes."""
        self.last_power_check = time.monotonic()
        status = self.battery_reader.status()
        if status is None:
            return
        self.battery_status.setText(battery_summary(status))
        source = (status["ac_online"], status["charging"])
        changed = self.last_power_source is not None and source != self.last_power_source
        self.last_power_source = source
        if self.running and self.config.battery_enabled and \
                (changed or self.last_power_check - self.last_battery >= self.config.battery_seconds):
            self.record_status("periodic", status)

    def record_status(self, reason, status=None):
        if not self.config.configured:
            return False
        status = status or self.battery_reader.status()
        if status is None:
            return False
        self.last_power_source = (status["ac_online"], status["charging"])
        self.battery_status.setText(battery_summary(status))
        if not self.config.battery_enabled:
            # Shutdown / sleep nodes are still wanted, but without battery details the user opted out of.
            status = dict.fromkeys(status)
        event = {"id": str(uuid.uuid4()), "kind": "device_status",
                 "occurred_at": datetime.now().astimezone().isoformat(), "reason": reason, **status}
        self.store.add(self.config, [event])
        self.last_battery = time.monotonic()
        return True

    # ---- power and session events -------------------------------------------------------------------------------

    def handle_system_event(self, event):
        if event == "show":
            self.show_window()
        elif event in {"query_end_session", "end_session"}:
            self.prepare_shutdown(final=event == "end_session")
        elif event == "end_session_cancelled":
            self.shutdown_saved = False
        elif event == "suspend":
            self.prepare_suspend()
        elif event == "resume":
            self.after_resume()
        elif event == "power_status":
            self.check_power()

    def prepare_shutdown(self, final):
        # WM_QUERYENDSESSION must be answered at once: save locally and start the upload in the
        # background. WM_ENDSESSION then waits briefly for it, because the process ends afterwards.
        if not self.shutdown_saved:
            self.shutdown_saved = True
            self.save_open_segment()
            if self.config.upload_on_shutdown:
                self.record_status("shutdown")
                self.uploader.trigger()
        if not final or self.quitting:
            return
        self.quitting = True
        self.save_open_segment()
        if self.config.upload_on_shutdown:
            self.uploader.flush(3.0)
        self.running = False
        self.timer.stop()
        self.uploader.stop()
        self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def prepare_suspend(self):
        if self.suspended:
            return  # the broadcast and the explicit subscription can both deliver it
        self.suspended, self.suspended_at = True, time.monotonic()
        self.save_open_segment()
        if self.config.upload_on_suspend:
            self.record_status("suspend")
            self.uploader.flush(1.5)  # Windows allows about two seconds before suspending anyway

    def after_resume(self):
        now = time.monotonic()
        if not self.suspended and now - self.last_resume < 60:
            return  # automatic and user-present resume arrive as a pair
        self.suspended, self.last_resume = False, now
        if self.config.status_enabled:
            self.record_status("resume")
        # Do not block here: the network is often still reconnecting, and the uploader retries.
        self.uploader.trigger()

    def about_to_quit(self):
        if not self.quitting:
            # Not our own "退出程序": when the main window exists, Qt answers WM_ENDSESSION for it
            # (possibly before our event window) and quits, so finish the session-end work here too.
            self.prepare_shutdown(final=True)
        self.release_system_events()

    def release_system_events(self):
        if self.system_events is not None:
            self.system_events.close()

    # ---- window -------------------------------------------------------------------------------------------------

    def clear_pending(self):
        answer = QMessageBox.question(self, "清空本地缓存", "将永久删除所有账户 / 连接下尚未上传的本地记录。已上传的服务端记录不受影响。确定清空？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.store.clear_pending()
            self.refresh_history()

    def open_dashboard(self):
        try:
            config = self.candidate()
        except ValueError:
            if not self.config.configured:
                return
            config = self.config
        webbrowser.open(config.base_url)

    def tray_activated(self, reason):
        if reason in {QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger}:
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        elif not QSystemTrayIcon.isSystemTrayAvailable():
            self.quit_app()
            event.accept()
        else:
            self.hide()
            event.ignore()

    def quit_app(self):
        if self.job_thread is not None:
            self.connection_note.setText("连接验证结束后即可退出（最长约10秒）。")
            self.show_window()
            return
        self.quitting = True
        try:
            self.stop_collection()
            self.uploader.flush(2.0)
        except Exception:
            logging.exception("Failed to flush final segment")
        self.timer.stop()
        self.uploader.stop()
        self.release_system_events()
        self.tray.hide()
        QApplication.instance().quit()
