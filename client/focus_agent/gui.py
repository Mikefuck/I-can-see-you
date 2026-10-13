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

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .config import save_config
from .network import Uploader, check_connection
from .store import PENDING, SENT
from .tracker import SessionTracker
from .winapi import BatteryReader, ForegroundReader, SystemEventWindow, encrypt, set_startup, startup_enabled


STATUS_REASONS = {"startup": "程序启动", "periodic": "电池采样", "shutdown": "关机前",
                  "suspend": "睡眠 / 休眠前", "resume": "唤醒恢复"}


# Swiss / International Typographic Style: one grotesque typeface, a strict grid, black rules on white,
# and a single signal red that is reserved for "recording", the main action and keyboard focus.
INK, PAPER, RED = "#111111", "#ffffff", "#e2001a"
MUTE, HAIRLINE, FIELD = "#6e6e6e", "#d9d9d9", "#f1f1f1"

# Latin glyphs come from the first grotesque that is installed; Chinese glyphs fall through to YaHei.
UI_FONTS = ["Helvetica Neue", "Helvetica", "Arial", "Microsoft YaHei UI"]

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


# The left rail is the state: red while recording, black when paused or failed (see MainWindow.set_state).
STYLE = Template("""
QMainWindow,QWidget#root,QWidget#paneBody,QScrollArea#pane{background:$paper;border:0;}
QWidget{color:$ink;font-size:13px;}
QLabel{background:transparent;}
QDialog,QMessageBox{background:$paper;}
QToolTip{background:$ink;color:$paper;border:0;padding:6px 8px;}

QFrame#rail{background:$ink;}
QFrame#rail[state="running"]{background:$red;}
QFrame#rail QLabel{color:$paper;}
QLabel#railTitle{font-size:24px;font-weight:700;}
QLabel#railSub,QLabel#railMeta,QLabel#heroDetail{font-size:12px;}
QLabel#hero{font-size:36px;font-weight:700;}
QLabel#railCaption{font-size:11px;font-weight:700;}
QLabel#railApp{font-size:16px;font-weight:700;}
QFrame#railRule{background:rgba(255,255,255,0.55);border:0;}
QPushButton#railPrimary{background:$paper;color:$ink;border:2px solid $paper;padding:11px 18px;}
QPushButton#railPrimary:hover{background:$field;border-color:$field;}
QPushButton#railPrimary:focus{background:$ink;color:$paper;border-color:$paper;}
QPushButton#railSecondary{background:transparent;color:$paper;border:2px solid $paper;}
QPushButton#railSecondary:hover,QPushButton#railSecondary:focus{background:$paper;color:$ink;}
QPushButton#railLink{background:transparent;color:$paper;border:0;padding:6px 0;font-weight:400;text-align:left;text-decoration:underline;}
QPushButton#railLink:hover{background:transparent;color:$paper;}
QPushButton#railLink:focus{background:transparent;color:$paper;font-weight:700;}

QFrame#section{border:0;border-top:3px solid $ink;}
QLabel#sectionTitle{font-size:20px;font-weight:700;}
QLabel#caption{font-size:11px;font-weight:700;color:$mute;}
QLabel#hint{font-size:12px;color:$mute;}
QLabel#value{font-weight:700;}

QLineEdit,QSpinBox,QComboBox{background:$field;border:0;border-bottom:2px solid $ink;border-radius:0;padding:7px 10px;min-height:22px;selection-background-color:$ink;selection-color:$paper;}
QLineEdit:focus,QSpinBox:focus,QComboBox:focus{border-bottom-color:$red;}
QLineEdit:disabled,QSpinBox:disabled,QComboBox:disabled{color:#9a9a9a;border-bottom-color:$hairline;}
QSpinBox{padding:7px 0 7px 10px;}
QSpinBox QLineEdit{background:transparent;border:0;padding:0 0 0 10px;}
QSpinBox::up-button,QSpinBox::down-button{subcontrol-origin:padding;width:26px;border:0;background:transparent;}
QSpinBox::up-button{subcontrol-position:top right;}
QSpinBox::down-button{subcontrol-position:bottom right;}
QSpinBox::up-button:hover,QSpinBox::down-button:hover{background:$hairline;}
QSpinBox::up-arrow{image:url("$glyphs/arrow-up.svg");width:9px;height:5px;}
QSpinBox::down-arrow{image:url("$glyphs/arrow-down.svg");width:9px;height:5px;}
QComboBox::drop-down{subcontrol-origin:padding;subcontrol-position:center right;width:28px;border:0;}
QComboBox::down-arrow{image:url("$glyphs/arrow-down.svg");width:9px;height:5px;}
QComboBox QAbstractItemView{background:$paper;border:2px solid $ink;selection-background-color:$ink;selection-color:$paper;outline:0;}
QComboBox QAbstractItemView::item{min-height:30px;padding-left:10px;}
QComboBox QAbstractItemView::item:selected{background:$ink;color:$paper;}

QPushButton{background:transparent;color:$ink;border:2px solid $ink;border-radius:0;padding:9px 18px;font-weight:700;min-height:20px;}
QPushButton:hover{background:$ink;color:$paper;}
QPushButton:focus{border-color:$red;}
QPushButton:disabled{color:#9a9a9a;border-color:$hairline;background:transparent;}
QPushButton#primary{background:$red;color:$paper;border-color:$red;}
QPushButton#primary:hover{background:$ink;border-color:$ink;}
QPushButton#primary:focus{border-color:$ink;}
QPushButton#primary:disabled{background:$hairline;color:#9a9a9a;border-color:$hairline;}

QCheckBox{spacing:12px;padding:3px 0;}
QCheckBox::indicator{width:16px;height:16px;border:2px solid $ink;background:$paper;}
QCheckBox::indicator:checked{background:$ink;image:url("$glyphs/check.svg");}
QCheckBox::indicator:focus{border-color:$red;}

QTableWidget{background:transparent;border:0;outline:0;gridline-color:transparent;selection-background-color:transparent;selection-color:$red;}
QTableWidget::item{padding:0 12px 0 0;border-bottom:1px solid $hairline;}
QTableWidget::item:selected{background:transparent;color:$red;}
QTableWidget QLineEdit{border-bottom-color:$red;padding:0 8px;min-height:0;}
QHeaderView{background:transparent;border:0;}
QHeaderView::section{background:transparent;color:$ink;border:0;border-bottom:2px solid $ink;padding:8px 12px 8px 0;font-size:11px;font-weight:700;}

QScrollBar:vertical{background:transparent;width:10px;margin:0;}
QScrollBar::handle:vertical{background:#c4c4c4;min-height:36px;}
QScrollBar::handle:vertical:hover{background:$ink;}
QScrollBar:horizontal{background:transparent;height:10px;margin:0;}
QScrollBar::handle:horizontal{background:#c4c4c4;min-width:36px;}
QScrollBar::handle:horizontal:hover{background:$ink;}
QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0;}
QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}

QMenu{background:$paper;color:$ink;border:2px solid $ink;padding:4px 0;}
QMenu::item{padding:8px 28px;}
QMenu::item:selected{background:$ink;color:$paper;}
QMenu::separator{height:1px;background:$hairline;margin:4px 0;}
""")


def stylesheet():
    return STYLE.substitute(ink=INK, paper=PAPER, red=RED, mute=MUTE, hairline=HAIRLINE, field=FIELD,
                            glyphs=glyph_directory())


def apply_typography(app):
    font = QFont()
    font.setFamilies(UI_FONTS)
    app.setFont(font)


def app_icon(active=True):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(RED if active else "#8c8c8c"))
    painter.drawRect(0, 0, 64, 64)
    painter.setBrush(QColor(PAPER))
    painter.drawRect(14, 20, 9, 30)
    painter.drawRect(27, 28, 9, 22)
    painter.drawRect(40, 14, 9, 36)
    painter.end()
    return QIcon(pixmap)


class StatusLamp(QWidget):
    """Recording lamp: a solid disc while collecting, a ring while paused, a red disc on failure."""

    def __init__(self):
        super().__init__()
        self.state = "stopped"
        self.setFixedSize(28, 28)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.state == "stopped":
            painter.setPen(QPen(QColor(PAPER), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(2, 2, 24, 24)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(RED if self.state == "error" else PAPER))
            painter.drawEllipse(0, 0, 28, 28)
        painter.end()


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
        self.setWindowTitle("专注记录 · Focus Ledger")
        self.setWindowIcon(app_icon())
        self.resize(1040, 820)
        self.setMinimumWidth(860)  # the height minimum comes from the rail, so its controls are never clipped
        self.setStyleSheet(stylesheet())
        self._build_ui()
        self._build_tray()
        self._populate()
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

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_rail())
        pane = QScrollArea()
        pane.setObjectName("pane")
        pane.setWidgetResizable(True)
        pane.setFrameShape(QFrame.Shape.NoFrame)
        pane.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pane.setWidget(self._build_pane())
        layout.addWidget(pane, 1)
        # Focus rings are for keyboard navigation: a mouse click should not leave a button or box marked.
        for control in self.findChildren(QPushButton) + self.findChildren(QCheckBox):
            control.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # The window itself holds the initial focus, so nothing is ringed until the user presses Tab.
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        root.setFocus()
        # QSS padding does not reach the line edit inside a spin box; align its text with the other fields.
        for spin in self.findChildren(QSpinBox):
            spin.lineEdit().setTextMargins(10, 0, 0, 0)

    def _build_rail(self):
        """Left rail: live state and the controls that act on it. It stays in view while the settings scroll."""
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setProperty("state", "stopped")
        rail.setFixedWidth(288)
        self.rail = rail
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(0)
        title = QLabel("专注记录")
        title.setObjectName("railTitle")
        subtitle = QLabel(f"Focus Ledger  {__version__}")
        subtitle.setObjectName("railSub")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(40)
        self.lamp = StatusLamp()
        layout.addWidget(self.lamp)
        layout.addSpacing(12)
        self.status = QLabel("尚未开始采集")
        self.status.setObjectName("hero")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status_detail = QLabel()
        self.status_detail.setObjectName("heroDetail")
        self.status_detail.setWordWrap(True)
        self.status_detail.hide()
        layout.addSpacing(6)
        layout.addWidget(self.status_detail)
        layout.addSpacing(26)
        self.current_app = QLabel("—")
        self.current_app.setObjectName("railApp")
        self.current_process = QLabel()
        self.current_process.setObjectName("railMeta")
        self.current_process.hide()
        self.upload_status = QLabel("等待配置")
        self.cache_status = QLabel("0 条")
        self.battery_status = QLabel("—")
        readouts = [("当前应用", [self.current_app, self.current_process]), ("上传状态", [self.upload_status]),
                    ("待上传缓存", [self.cache_status]), ("电池状态", [self.battery_status])]
        for caption, values in readouts:
            rule = QFrame()
            rule.setObjectName("railRule")
            rule.setFixedHeight(1)
            layout.addWidget(rule)
            layout.addSpacing(10)
            layout.addWidget(self._label("railCaption", caption))
            layout.addSpacing(3)
            for value in values:
                value.setWordWrap(True)
                layout.addWidget(value)
            layout.addSpacing(14)
        layout.addStretch()
        self.toggle = QPushButton("开始采集")
        self.toggle.setObjectName("railPrimary")
        self.toggle.clicked.connect(self.toggle_collection)
        upload = QPushButton("立即上传")
        upload.setObjectName("railSecondary")
        upload.clicked.connect(lambda: self.upload_now())
        clear = QPushButton("清空未上传缓存")
        clear.setObjectName("railLink")
        clear.clicked.connect(self.clear_pending)
        layout.addWidget(self.toggle)
        layout.addSpacing(8)
        layout.addWidget(upload)
        layout.addSpacing(6)
        layout.addWidget(clear)
        return rail

    def _build_pane(self):
        body = QWidget()
        body.setObjectName("paneBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(40, 28, 40, 28)
        layout.setSpacing(0)
        layout.addWidget(self._connection_section())
        layout.addWidget(self._collection_section())
        layout.addWidget(self._aliases_section())
        layout.addWidget(self._history_section(), 1)
        layout.addWidget(self._label("hint", "采集范围：应用名称、进程名、使用时长，以及设置允许的电池和系统状态。密钥使用 Windows 账户加密存储。"))
        return body

    @staticmethod
    def _label(name, text, top=0):
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(name == "hint")
        label.setContentsMargins(0, top, 0, 0)
        return label

    @staticmethod
    def _section(title, english):
        """A section opens with a heavy rule; the English subtitle is small and grey, on the same baseline."""
        frame = QFrame()
        frame.setObjectName("section")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 14, 0, 32)
        layout.setSpacing(14)
        heading = QLabel(f'{title}&nbsp;&nbsp;<span style="font-size:11px;font-weight:normal;color:{MUTE}">{english}</span>')
        heading.setObjectName("sectionTitle")
        heading.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(heading)
        return frame, layout

    def _connection_section(self):
        frame, layout = self._section("连接", "Connection")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        for column, stretch in enumerate((5, 2, 2)):
            grid.setColumnStretch(column, stretch)
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
        grid.addWidget(self._label("caption", "服务器 IP / 域名"), 0, 0)
        grid.addWidget(self.host, 1, 0)
        grid.addWidget(self._label("caption", "连接方式"), 0, 1)
        grid.addWidget(self.protocol, 1, 1)
        grid.addWidget(self._label("caption", "端口"), 0, 2)
        grid.addWidget(self.port, 1, 2)
        grid.addWidget(self._label("caption", "上传密钥", 12), 2, 0, 1, 3)
        grid.addWidget(self.key, 3, 0, 1, 3)
        grid.addWidget(self._label("caption", "设备名称", 12), 4, 0)
        grid.addWidget(self.device_name, 5, 0)
        grid.addWidget(self._label("caption", "所属账户", 12), 4, 1, 1, 2)
        grid.addWidget(self.account, 5, 1, 1, 2)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(lambda: self.connection_job(True))
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(lambda: self.connection_job(False))
        dashboard = QPushButton("打开服务端网页")
        dashboard.clicked.connect(self.open_dashboard)
        actions.addWidget(self.save_button)
        actions.addWidget(self.test_button)
        actions.addWidget(dashboard)
        actions.addStretch()
        layout.addSpacing(8)
        layout.addLayout(actions)
        self.connection_note = self._label("hint", "首次保存或更换连接时会验证密钥，避免将缓存上传到错误账户。")
        layout.addWidget(self.connection_note)
        return frame

    def _collection_section(self):
        frame, layout = self._section("采集", "Collection")
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
        numbers = QGridLayout()
        numbers.setHorizontalSpacing(16)
        numbers.setVerticalSpacing(4)
        for column, (caption, spin) in enumerate([("空闲暂停阈值", self.idle), ("上传间隔", self.interval),
                                                  ("电池状态间隔", self.battery_interval)]):
            numbers.setColumnStretch(column, 1)
            numbers.addWidget(self._label("caption", caption), 0, column)
            numbers.addWidget(spin, 1, column)
        layout.addLayout(numbers)
        layout.addSpacing(8)
        self.startup = QCheckBox("登录 Windows 后自动启动")
        self.silent = QCheckBox("静默启动（直接进入系统托盘）")
        self.silent.setToolTip("启动时不弹出主窗口，只显示托盘图标。再次运行程序或单击托盘图标可打开主窗口。")
        layout.addWidget(self.startup)
        self.startup_note = self._label("hint", "")
        self.startup_note.setContentsMargins(28, 0, 0, 4)
        self.startup_note.hide()
        layout.addWidget(self.startup_note)
        layout.addWidget(self.silent)
        self.battery = QCheckBox("采集并上传电池状态")
        self.battery.setToolTip("按间隔记录电量、充电和电源状态；插拔电源时会立即补充一条记录。")
        self.battery.toggled.connect(self.battery_interval.setEnabled)
        layout.addWidget(self.battery)
        self.shutdown_upload = QCheckBox("关机 / 注销前保存并尝试上传状态")
        self.suspend_upload = QCheckBox("睡眠 / 休眠前保存并尝试上传状态")
        self.shutdown_upload.setToolTip("先写入本地缓存，再在约3秒内尝试上传，不会阻止关机。")
        self.suspend_upload.setToolTip("Windows 只给约2秒处理时间；来不及上传的记录会在唤醒后补传。")
        layout.addWidget(self.shutdown_upload)
        layout.addWidget(self.suspend_upload)
        layout.addSpacing(6)
        layout.addWidget(self._label("hint", "每秒采样前台应用。锁屏、睡眠及空闲时暂停计时；电源事件会先保存本地状态，再限时尝试上传。关闭窗口后继续在托盘运行。"))
        return frame

    def _ledger_table(self, columns, headers):
        """Table in the ledger style: flush-left columns, a heavy header rule and hairlines between rows."""
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
        table.verticalHeader().setDefaultSectionSize(36)
        return table

    def _aliases_section(self):
        frame, layout = self._section("应用名翻译", "App names")
        layout.addWidget(self._label("hint", "按进程名匹配（不区分大小写，可省略 .exe），例如 chrome.exe → 浏览器；原始进程名仍会保留。"
                                     "双击下方最近记录可快速为该应用添加翻译，修改后保存设置生效。"))
        self.aliases = self._ledger_table(2, ["进程名", "自定义显示名"])
        self.aliases.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                     QAbstractItemView.EditTrigger.EditKeyPressed)
        self.aliases.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.fit_aliases()
        layout.addWidget(self.aliases)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        add_alias = QPushButton("添加翻译")
        add_alias.clicked.connect(lambda: self.add_alias())
        remove_alias = QPushButton("删除选中")
        remove_alias.clicked.connect(self.remove_alias)
        actions.addWidget(add_alias)
        actions.addWidget(remove_alias)
        actions.addStretch()
        layout.addSpacing(4)
        layout.addLayout(actions)
        return frame

    def _history_section(self):
        frame, layout = self._section("最近记录", "Recent records")
        layout.addWidget(self._label("hint", "本地记录：已上传保留7天，未上传最多保留30天 / 100,000条。"))
        self.history_empty = self._label("hint", "还没有记录。开始采集后，每一段前台应用使用都会出现在这里。", 6)
        layout.addWidget(self.history_empty)
        self.history = self._ledger_table(5, ["应用名称", "进程名", "结束时间（本地）", "时长", "上传状态"])
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.history.horizontalHeader()
        for column, mode in enumerate((QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.ResizeToContents)):
            header.setSectionResizeMode(column, mode)
        self.history.setMinimumHeight(300)
        self.history.cellDoubleClicked.connect(self.alias_from_history)
        layout.addWidget(self.history, 1)
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
        self.aliases.setFixedHeight(self.aliases.horizontalHeader().sizeHint().height() + rows * 36 + 2)

    def alias_row(self, process):
        for row in range(self.aliases.rowCount()):
            item = self.aliases.item(row, 0)
            if item is not None and item.text().strip().casefold() == process.casefold():
                return row
        return None

    def edit_alias(self, row, column):
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
        self.connection_note.setText("设置已保存。" + ("HTTP 连接适用于可信内网；公网请选择 HTTPS。" if candidate.protocol == "http" else "HTTPS 证书会进行验证。"))
        if was_running:
            self.start_collection()
        self.refresh_history()

    def start_collection(self):
        if not self.config.configured:
            QMessageBox.information(self, "先连接服务器", "请填写服务器与密钥并保存设置，再开始采集。")
            self.show_window()
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

    def set_state(self, state, text, detail=""):
        """The rail's colour and lamp follow the state: running, stopped or error."""
        self.status.setText(text)
        self.status_detail.setText(detail)
        self.status_detail.setVisible(bool(detail))
        self.lamp.state = state
        self.lamp.update()
        self.rail.setProperty("state", state)
        self.rail.style().unpolish(self.rail)
        self.rail.style().polish(self.rail)

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
        self.set_state("stopped", "采集已暂停")
        self.show_current(None, "—")
        self.toggle.setText("开始采集")
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
                self.store.add(self.config, self.tracker.observe(app, time.time(), now))
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
        except Exception:
            logging.exception("Sampling/storage failed")
            # A locked or full disk is often temporary: keep the agent alive and retry instead of stopping for good.
            self.tracker = SessionTracker()
            self.retry_sampling_at = now + 30
            self.set_state("error", "采集出错", "本地读取或存储失败，30 秒后自动重试")
            self.tray.setToolTip("专注记录 · 采集出错，稍后重试")

    def refresh_history(self):
        current, total = self.store.counts(self.config.destination)
        self.cache_status.setText(f"当前连接 {current} 条 · 总计 {total} 条" +
            ("（其他连接的缓存保持隔离，需切回原账户上传）" if total > current else ""))
        records = self.store.recent(self.config.destination)
        # Pending rows are set in bold ink, sent rows recede to grey, rejected rows turn red.
        states = {PENDING: ("待上传", INK, True), SENT: ("已上传", MUTE, False)}
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
                if column == 4:
                    item.setForeground(QColor(color))
                    if bold:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                self.history.setItem(row, column, item)
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
