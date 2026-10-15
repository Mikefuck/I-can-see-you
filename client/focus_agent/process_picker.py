"""Searchable running-process chooser using the main window's ledger styling."""
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QTableWidgetItem, QVBoxLayout,
)

from .aliases import alias_for, process_key
from .motion import CheckDelegate, MotionButton as QPushButton
from .winapi import ForegroundReader


class ProcessPicker(QDialog):
    loaded = Signal(object, str)

    def __init__(self, window, aliases, loader=None):
        super().__init__(window)
        self.theme_colors = window.theme_colors
        self.aliases = aliases
        self.loader = loader or (lambda: ForegroundReader().running_applications())
        self.apps, self.checked = [], set()
        self.loading = False
        self.setWindowTitle("选择系统进程 · 专注记录")
        self.setAttribute(Qt.WidgetAttribute.WA_WindowPropagation, True)
        self.setPalette(window.palette())
        self.resize(760, 560)
        self.setMinimumSize(620, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel("选择系统进程")
        heading.setObjectName("stateWord")
        layout.addWidget(heading)
        hint = QLabel("同名进程合并显示。勾选要翻译的应用，添加后编辑显示名并保存设置。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(window._rule("heavyRule", 3))
        search = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索应用名称、进程名或已有翻译")
        self.search.setAccessibleName("搜索系统进程")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_apps)
        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.clicked.connect(self.reload)
        search.addWidget(self.search, 1)
        search.addWidget(self.refresh_button)
        layout.addLayout(search)
        self.table = window._ledger_table(4, ["选择", "应用名称", "进程名", "已有翻译"])
        self.table.setItemDelegateForColumn(0, CheckDelegate(self.table))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 48)
        self.table.itemChanged.connect(self.check_changed)
        self.table.cellClicked.connect(self.toggle_row)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.select_button = QPushButton("全选当前结果")
        self.select_button.clicked.connect(self.select_visible)
        actions.addWidget(self.select_button)
        actions.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.confirm = QPushButton("添加所选")
        self.confirm.setProperty("primary", True)
        self.confirm.clicked.connect(self.accept)
        self.confirm.setDefault(True)
        actions.addWidget(self.confirm)
        layout.addLayout(actions)
        self.loaded.connect(self.show_apps)
        self.search.setFocus()
        self.reload()

    def reload(self):
        if self.loading:
            return
        self.loading = True
        self.refresh_button.setEnabled(False)
        self.confirm.setEnabled(False)
        self.select_button.setEnabled(False)
        self.table.setEnabled(False)
        self.status.setText("正在读取系统进程…")

        def read():
            try:
                apps, error = self.loader(), ""
            except Exception as exc:
                apps, error = [], str(exc)
            try:
                self.loaded.emit(apps, error)
            except RuntimeError:
                pass  # The window may have been closed while file metadata was being read.

        Thread(target=read, name="focus-process-picker", daemon=True).start()

    def show_apps(self, apps, error):
        self.loading = False
        self.refresh_button.setEnabled(True)
        self.table.setEnabled(True)
        self.apps = list({process_key(app.process_name): app for app in apps}.values())
        self.checked.intersection_update(process_key(app.process_name) for app in self.apps)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.apps))
        for row, app in enumerate(self.apps):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if process_key(app.process_name) in self.checked else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, process_key(app.process_name))
            self.table.setItem(row, 0, check)
            for column, value in enumerate((app.app_name, app.process_name, alias_for(self.aliases, app.process_name) or "—"), 1):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.filter_apps()
        if error:
            self.status.setText("读取失败，请刷新重试：" + error)

    def filter_apps(self):
        query = self.search.text().strip().casefold()
        for row, app in enumerate(self.apps):
            text = " ".join((app.app_name, app.process_name, alias_for(self.aliases, app.process_name) or ""))
            self.table.setRowHidden(row, query not in text.casefold())
        if not self.loading:
            self.update_count()

    def update_count(self):
        visible = sum(not self.table.isRowHidden(row) for row in range(len(self.apps)))
        text = f"已选 {len(self.checked)} 个 · 显示 {visible} / {len(self.apps)} 个进程"
        if not self.apps:
            text = "暂无可选进程，请刷新列表。"
        elif not visible:
            text += " · 没有匹配项，请更换关键词。"
        self.status.setText(text)
        self.confirm.setText(f"添加所选（{len(self.checked)}）" if self.checked else "添加所选")
        self.confirm.setEnabled(bool(self.checked))
        self.select_button.setEnabled(bool(visible))

    def check_changed(self, item):
        if item.column() != 0:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self.checked.add(key)
        else:
            self.checked.discard(key)
        self.update_count()

    def toggle_row(self, row, column):
        if column:
            item = self.table.item(row, 0)
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def select_visible(self):
        items = [self.table.item(row, 0) for row in range(len(self.apps)) if not self.table.isRowHidden(row)]
        state = Qt.CheckState.Unchecked if all(item.checkState() == Qt.CheckState.Checked for item in items) else Qt.CheckState.Checked
        for item in items:
            item.setCheckState(state)

    def selected_apps(self):
        return [app for app in self.apps if process_key(app.process_name) in self.checked]
