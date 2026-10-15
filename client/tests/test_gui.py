import ctypes
import os
import sys
import time
import threading
from ctypes import wintypes
from queue import Queue

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette
from focus_agent import gui
from focus_agent import management_ui
from focus_agent.config import Config, load_config
from focus_agent.store import EventStore
from focus_agent.tracker import Application, SessionTracker
from focus_agent.winapi import SystemEventWindow, decrypt


APP = Application("Synthetic App", "synthetic.exe")


class Reader:
    def set_aliases(self, aliases):
        self.aliases = aliases

    def sample(self, idle):
        return Application("Synthetic App", "synthetic.exe"), "sample"


class Upload:
    def __init__(self, store, config):
        self.messages = Queue()
        self.calls = []

    def start(self):
        pass

    def configure(self, config):
        pass

    def stop(self):
        pass

    def trigger(self):
        self.calls.append("trigger")

    def flush(self, timeout=3.0):
        self.calls.append(("flush", timeout))
        return True


class Battery:
    def __init__(self):
        self.value = {"battery_percent": 64, "charging": False, "ac_online": False, "battery_life_seconds": 5400}

    def status(self):
        return dict(self.value)


class NoSystemEvents:
    def __init__(self, callback):
        pass

    def close(self):
        pass


@pytest.fixture
def make_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, "ForegroundReader", Reader)
    monkeypatch.setattr(gui, "Uploader", Upload)
    monkeypatch.setattr(gui, "BatteryReader", Battery)
    monkeypatch.setattr(gui, "SystemEventWindow", NoSystemEvents)
    monkeypatch.setattr(gui, "startup_enabled", lambda: False)
    startup_calls = []
    monkeypatch.setattr(gui, "set_startup", startup_calls.append)
    windows = []

    def build(**options):
        config = Config(**{"host": "127.0.0.1", "api_key": "x"*43, "account_id": 1, "username": "alice", **options})
        window = gui.MainWindow(config, tmp_path / "config.json", EventStore(tmp_path / "events.db"))
        window.startup_calls = startup_calls
        windows.append(window)
        return window

    yield app, build
    for window in windows:
        window.quit_app()


def statuses(window):
    return [event for event, _ in reversed(window.store.recent(window.config.destination))
            if event["kind"] == "device_status"]


def test_gui_controls_and_verified_account_switch(make_window, monkeypatch, tmp_path):
    app, build = make_window
    window = build()
    first = window.config
    assert window.running
    window.toggle_collection()
    assert not window.running
    window.interval.setValue(45)
    window.battery_interval.setValue(60)
    window.aliases.setRowCount(1)
    window.aliases.setItem(0, 0, gui.QTableWidgetItem("synthetic.exe"))
    window.aliases.setItem(0, 1, gui.QTableWidgetItem("合成应用"))
    window.connection_job(True)  # Same endpoint and key can be saved offline.
    assert window.config.upload_seconds == 45
    assert window.config.battery_seconds == 60
    assert window.config.app_aliases == {"synthetic.exe": "合成应用"}
    assert load_config(tmp_path / "config.json", decrypt).account_id == 1
    window.key.setText("y"*43)
    monkeypatch.setattr(gui, "check_connection", lambda config: {
        "account_id": 2, "username": "bob", "features": ["app_usage", "device_status"],
        "retention_days": 365})
    window.connection_job(True)
    deadline = time.monotonic()+3
    while window.job_thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.job_thread is None
    assert window.config.username == "bob"
    assert window.config.device_id != first.device_id
    assert window.config.destination != first.destination
    assert window.startup_calls == [False, False]
    window.toggle_collection()
    assert window.running
    window.upload_now()


def wait_job(app, window):
    deadline = time.monotonic() + 4
    while window.job_thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.job_thread is None


@pytest.mark.parametrize("fail", [False, True])
def test_verification_locks_settings_and_restores_controls(make_window, monkeypatch, fail):
    app, build = make_window
    window = build()
    entered, release = threading.Event(), threading.Event()

    def verify(config):
        entered.set()
        assert release.wait(3)
        if fail:
            raise RuntimeError("synthetic offline")
        return {"account_id": 1, "username": "alice", "retention_days": 365}

    monkeypatch.setattr(gui, "check_connection", verify)
    window.host.setText("server-a.example.com")
    window.mark_dirty()
    window.connection_job(True)
    try:
        assert entered.wait(2)
        assert not window.host.isEnabled()
        assert not window.key.isEnabled()
        assert not window.port.isEnabled()
        # The history page remains accessible, but its alias shortcut must not alter the locked form.
        name = gui.QTableWidgetItem("Synthetic App")
        name.setData(gui.Qt.ItemDataRole.UserRole, "app_usage")
        window.history.setRowCount(1)
        window.history.setItem(0, 0, name)
        window.history.setItem(0, 1, gui.QTableWidgetItem("synthetic.exe"))
        rows = window.aliases.rowCount()
        window.alias_from_history(0, 0)
        assert window.aliases.rowCount() == rows
    finally:
        release.set()
    wait_job(app, window)
    assert window.host.isEnabled() and window.key.isEnabled() and window.save_button.isEnabled()
    assert window.config.host == ("127.0.0.1" if fail else "server-a.example.com")
    assert window.dirty == fail


def test_returning_to_account_restores_original_device_after_test_and_save(make_window, monkeypatch):
    app, build = make_window
    window = build()
    original = window.config
    monkeypatch.setattr(gui, "check_connection", lambda config: {"account_id": 2 if config.api_key.startswith("y") else 1,
        "username": "bob" if config.api_key.startswith("y") else "alice", "retention_days": 365})
    window.key.setText("y" * 43)
    window.connection_job(False)
    wait_job(app, window)
    tested_id = window.config.device_ids[window.job_candidate.bind_account(2, "bob").destination]
    window.connection_job(True)
    wait_job(app, window)
    assert window.config.device_id == tested_id
    window.key.setText(original.api_key)
    window.connection_job(True)
    wait_job(app, window)
    assert window.config.device_id == original.device_id
    assert window.config.destination == original.destination


def test_management_page_login_create_and_save_runtime(make_window, monkeypatch):
    app, build = make_window
    window = build(account_id=0, api_key="", username="")
    panel = window.management_panel
    calls = []

    class Session:
        def __init__(self, config):
            self.base_url = config.base_url
            self.user = None
            self.days = 365
            self.users = [{"id": 1, "username": "admin", "is_admin": True, "enabled": True}]

        def login(self, username, password):
            calls.append(("login", username, password))
            self.user = {"account_id": 1, "username": username, "is_admin": True}
            return self.user

        def overview(self):
            return {"users": list(self.users), "settings": {"retention_days": self.days, "secure_cookies": False}}

        def request(self, path, body, method):
            calls.append((path, body, method))
            if path == "/users":
                self.users.append({"id": 2, "username": body["username"], "is_admin": False, "enabled": True})
            elif path == "/settings":
                self.days = body["retention_days"]
            return {}

    def wait():
        deadline = time.monotonic() + 3
        while panel.thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert panel.thread is None

    monkeypatch.setattr(management_ui, "ManagementSession", Session)
    window.show_page(window.MANAGEMENT)
    assert not panel.admin.isEnabled()
    panel.username.setText("admin")
    panel.password.setText("test-password-123")
    panel.login()
    wait()
    assert panel.admin.isEnabled()
    assert panel.password.text() == ""
    assert panel.users.rowCount() == 1
    panel.new_username.setText("alice")
    panel.new_password.setText("test-password-456")
    panel.create_user()
    wait()
    assert panel.users.rowCount() == 2
    assert panel.new_password.text() == ""
    monkeypatch.setattr(gui.QMessageBox, "question", lambda *args: gui.QMessageBox.StandardButton.Yes)
    panel.retention.setValue(30)
    panel.save_settings()
    wait()
    assert panel.retention_days == 30
    assert ("/settings", {"retention_days": 30}, "PUT") in calls


def test_startup_node_is_recorded_once_per_program_start(make_window):
    _, build = make_window
    window = build()
    window.toggle_collection()
    window.toggle_collection()
    window.connection_job(True)
    assert [event["reason"] for event in statuses(window)] == ["startup"]


def test_no_status_records_when_all_status_options_are_off(make_window):
    _, build = make_window
    window = build(battery_enabled=False, upload_on_shutdown=False, upload_on_suspend=False)
    for event in ["suspend", "resume", "query_end_session"]:
        window.handle_system_event(event)
    assert statuses(window) == []
    assert ("flush", 1.5) not in window.uploader.calls


def test_suspend_is_saved_once_and_fits_the_two_second_budget(make_window):
    _, build = make_window
    window = build()
    window.handle_system_event("suspend")
    window.handle_system_event("suspend")  # broadcast + explicit subscription
    assert [event["reason"] for event in statuses(window)] == ["startup", "suspend"]
    assert window.uploader.calls.count(("flush", 1.5)) == 1
    window.handle_system_event("resume")
    window.handle_system_event("resume")  # automatic + user-present resume
    assert [event["reason"] for event in statuses(window)] == ["startup", "suspend", "resume"]
    # Resume never blocks the GUI thread on a network that is still reconnecting.
    assert window.uploader.calls[-1] == "trigger"


def test_shutdown_answers_query_at_once_then_flushes_once(make_window):
    _, build = make_window
    window = build()
    # An open two-sample segment that must be persisted before Windows ends the process.
    wall, monotonic = time.time(), time.monotonic()
    window.tracker = SessionTracker()
    window.tracker.observe(APP, wall - 2, monotonic - 2)
    window.tracker.observe(APP, wall - 1, monotonic - 1)
    window.handle_system_event("query_end_session")
    assert window.uploader.calls == ["trigger"]  # no waiting inside WM_QUERYENDSESSION
    usage = [event for event, _ in window.store.recent(window.config.destination) if event["kind"] == "app_usage"]
    assert len(usage) == 1 and usage[0]["duration_seconds"] == pytest.approx(1)
    window.handle_system_event("query_end_session")  # every top-level window may be asked
    window.handle_system_event("end_session")
    assert [event["reason"] for event in statuses(window)] == ["startup", "shutdown"]
    assert window.uploader.calls == ["trigger", ("flush", 3.0)]
    assert not window.timer.isActive()


def test_session_end_finished_when_qt_quits_first(make_window):
    """With the main window open, Qt answers WM_ENDSESSION for it first and emits aboutToQuit."""
    _, build = make_window
    window = build()
    window.handle_system_event("query_end_session")
    window.about_to_quit()
    assert window.uploader.calls == ["trigger", ("flush", 3.0)]
    window.handle_system_event("end_session")  # our own window may still be asked afterwards
    assert window.uploader.calls == ["trigger", ("flush", 3.0)]
    assert [event["reason"] for event in statuses(window)] == ["startup", "shutdown"]


def test_own_quit_does_not_count_as_shutdown(make_window):
    _, build = make_window
    window = build()
    window.quit_app()
    window.about_to_quit()
    assert [event["reason"] for event in statuses(window)] == ["startup"]


def test_cancelled_shutdown_allows_a_later_one(make_window):
    _, build = make_window
    window = build()
    window.handle_system_event("query_end_session")
    window.handle_system_event("end_session_cancelled")
    window.handle_system_event("query_end_session")
    assert [event["reason"] for event in statuses(window)] == ["startup", "shutdown", "shutdown"]


def test_battery_opt_out_keeps_lifecycle_nodes_without_battery_details(make_window):
    _, build = make_window
    window = build(battery_enabled=False)
    window.handle_system_event("query_end_session")
    shutdown = statuses(window)[-1]
    assert shutdown["reason"] == "shutdown"
    assert [shutdown[key] for key in ("battery_percent", "charging", "ac_online", "battery_life_seconds")] == [None]*4


def test_power_source_change_is_recorded_immediately(make_window):
    _, build = make_window
    window = build(battery_seconds=3600)
    window.check_power()
    assert [event["reason"] for event in statuses(window)] == ["startup"]
    window.battery_reader.value.update(ac_online=True, charging=True)
    window.handle_system_event("power_status")
    assert [event["reason"] for event in statuses(window)] == ["startup", "periodic"]
    assert statuses(window)[-1]["charging"] is True
    assert "充电中" in window.battery_status.text()


def test_startup_checkbox_shows_real_windows_state(make_window, monkeypatch):
    _, build = make_window
    window = build(startup=True)  # saved preference, but disabled in Task Manager
    assert not window.startup.isChecked()
    assert not window.startup_note.isHidden()
    monkeypatch.setattr(gui, "startup_enabled", lambda: True)
    window.show_startup_state(True)
    assert window.startup.isChecked() and window.startup_note.isHidden()


def test_alias_suggestions_and_duplicates(make_window):
    _, build = make_window
    window = build()
    window.tick()
    window.add_alias()
    assert window.aliases.item(0, 0).text() == "synthetic.exe"
    assert window.aliases.item(0, 1).text() == "Synthetic App"
    window.add_alias("Synthetic.EXE", "重复")
    with pytest.raises(ValueError, match="重复"):
        window.collect_aliases()


def test_day_strip_shows_today_with_the_open_segment_live(make_window):
    _, build = make_window
    window = build()
    wall, monotonic = time.time(), time.monotonic()
    window.tracker = SessionTracker(segment_seconds=120)
    for offset in range(40, 0, -1):  # one app in the foreground for 40 s, not yet stored
        window.tracker.observe(APP, wall - offset, monotonic - offset)
    window.refresh_history()
    stored = window.day_recorded
    assert len(window.day.marks) == 1 and window.day.marks[0][1] is True  # the "startup" node, drawn as ▲
    hours, minutes, seconds = map(int, window.day_total.text().split(":"))
    assert hours * 3600 + minutes * 60 + seconds == pytest.approx(stored + 40, abs=2)
    live = [block for block in window.day.blocks() if block[2]]
    assert len(live) == 1 and live[0][1] == pytest.approx(time.time(), abs=2)
    window.toggle_collection()  # pausing stores the segment and nothing is live any more
    assert window.day_recorded == pytest.approx(stored + 40, abs=2)
    assert not any(live for *_, live in window.day.blocks())
    assert window.day.describe(window.day.x_at(wall - 20), window.day.SCALE + 5).startswith("Synthetic App")


def test_settings_edits_are_flagged_until_saved(make_window):
    _, build = make_window
    window = build()
    assert window.pages.currentIndex() == window.LEDGER and not window.dirty
    window.interval.setValue(45)
    assert window.dirty and window.settings_tab.flagged and not window.unsaved.isHidden()
    window.connection_job(True)
    assert not window.dirty and not window.settings_tab.flagged and window.unsaved.isHidden()


def test_system_theme_changes_live_and_manual_choice_takes_priority(make_window, tmp_path):
    app, build = make_window
    window = build()
    hints = app.styleHints()
    hints.colorSchemeChanged.emit(gui.Qt.ColorScheme.Dark)
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#161616"
    assert window.key.palette().color(QPalette.ColorRole.Text).name() == "#e8e8e5"
    assert window.management_panel.username.palette().color(QPalette.ColorRole.Text).name() == "#e8e8e5"
    window.theme_actions["light"].trigger()
    hints.colorSchemeChanged.emit(gui.Qt.ColorScheme.Dark)
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#ffffff"
    window.theme_actions["system"].trigger()
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#161616"
    hints.colorSchemeChanged.emit(gui.Qt.ColorScheme.Light)
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#ffffff"
    assert load_config(tmp_path / "config.json", decrypt).theme == "system"


def test_theme_saves_before_connection_setup_and_keeps_unfinished_edits(make_window, tmp_path):
    _, build = make_window
    window = build(account_id=0, username="", api_key="", theme="light")
    window.host.setText("unfinished.example.com")
    window.mark_dirty()
    window.theme_actions["dark"].trigger()
    saved = load_config(tmp_path / "config.json", decrypt)
    assert saved.theme == "dark" and saved.host == "127.0.0.1"
    assert window.host.text() == "unfinished.example.com" and window.dirty
    assert window.job_thread is None and not window.running and not window.startup_calls
    restored = build(**saved.__dict__)
    assert restored.palette().color(QPalette.ColorRole.Window).name() == "#161616"
    assert restored.theme_actions["dark"].isChecked()


def test_theme_is_preserved_when_pending_connection_check_finishes(make_window, monkeypatch, tmp_path):
    app, build = make_window
    window = build(theme="light")
    entered, release = threading.Event(), threading.Event()

    def verify(config):
        entered.set()
        assert release.wait(3)
        return {"account_id": 1, "username": "alice", "retention_days": 365}

    monkeypatch.setattr(gui, "check_connection", verify)
    window.host.setText("new.example.com")
    window.connection_job(True)
    try:
        assert entered.wait(2)
        window.theme_actions["dark"].trigger()
        assert window.theme_actions["dark"].isChecked()
    finally:
        release.set()
    wait_job(app, window)
    saved = load_config(tmp_path / "config.json", decrypt)
    assert saved.theme == window.config.theme == "dark"
    assert saved.host == "new.example.com"


def test_theme_save_failure_restores_the_current_choice(make_window, monkeypatch):
    _, build = make_window
    window = build(theme="light")
    messages = []

    def fail(*args):
        raise OSError("read-only configuration")

    monkeypatch.setattr(gui, "save_config", fail)
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: messages.append(args))
    window.theme_actions["dark"].trigger()
    assert window.config.theme == "light" and window.theme_actions["light"].isChecked()
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#ffffff"
    assert messages and "read-only configuration" in messages[0][2]


def test_theme_repaints_timeline_and_existing_history_without_interrupting_collection(make_window):
    app, build = make_window
    window = build(theme="light")
    window.show()
    app.processEvents()
    window.refresh_history()
    initial = window.history.item(0, 4).foreground().color().name()
    before = window.day.grab().toImage()
    node_count = len(statuses(window))
    tracker = window.tracker
    window.theme_actions["dark"].trigger()
    app.processEvents()
    assert window.running and window.tracker is tracker
    assert len(statuses(window)) == node_count and not window.startup_calls
    assert initial == "#101010"
    assert window.history.item(0, 4).foreground().color().name() == "#e8e8e5"
    # The solid baseline comes from a custom QPainter, outside the stylesheet.
    x = window.day.width() // 4 if window.day.x_at(window.day.now) > window.day.width() // 2 else window.day.width() * 3 // 4
    y = window.day.SCALE + window.day.BAR
    assert before.pixelColor(x, y).name() == "#101010"
    assert window.day.grab().toImage().pixelColor(x, y).name() == "#e8e8e5"


def test_unconfigured_window_opens_settings_and_history_aliases_switch_page(make_window):
    _, build = make_window
    window = build(account_id=0, username="")
    assert window.pages.currentIndex() == window.SETTINGS
    window.show_page(window.LEDGER)
    window.store.add(window.config, [{
        "id": "a", "kind": "app_usage", "app_name": "Synthetic App", "process_name": "synthetic.exe",
        "started_at": "2026-01-01T00:00:00+00:00", "ended_at": "2026-01-01T00:00:30+00:00", "duration_seconds": 30}])
    window.refresh_history()
    window.alias_from_history(0, 0)
    assert window.pages.currentIndex() == window.SETTINGS
    assert window.aliases.item(0, 0).text() == "synthetic.exe"


def test_system_event_messages_translate():
    translate = SystemEventWindow.translate
    assert translate(SystemEventWindow.WM_QUERYENDSESSION, 0) == "query_end_session"
    assert translate(SystemEventWindow.WM_ENDSESSION, 1) == "end_session"
    assert translate(SystemEventWindow.WM_ENDSESSION, 0) == "end_session_cancelled"
    assert translate(SystemEventWindow.WM_POWERBROADCAST, SystemEventWindow.PBT_APMSUSPEND) == "suspend"
    assert translate(SystemEventWindow.WM_POWERBROADCAST, SystemEventWindow.PBT_APMRESUMEAUTOMATIC) == "resume"
    assert translate(SystemEventWindow.WM_POWERBROADCAST, SystemEventWindow.PBT_APMRESUMESUSPEND) == "resume"
    assert translate(SystemEventWindow.WM_POWERBROADCAST, SystemEventWindow.PBT_APMPOWERSTATUSCHANGE) == "power_status"
    assert translate(0x000F, 0) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows window messages")
def test_hidden_event_window_receives_broadcast_style_messages():
    """Regression: with a silent start no Qt window exists, so nothing received shutdown/sleep broadcasts."""
    app = QApplication.instance() or QApplication([])
    events = []
    monitor = SystemEventWindow(events.append)
    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        top_level = []
        user.EnumWindows(enum_proc(lambda hwnd, _: top_level.append(hwnd) or True), 0)
        # EnumWindows lists exactly the windows that broadcasts reach (message-only windows are excluded).
        assert monitor.hwnd in top_level
        user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.SendMessageW.restype = ctypes.c_ssize_t
        assert user.SendMessageW(monitor.hwnd, SystemEventWindow.WM_QUERYENDSESSION, 0, 0) == 1  # never vetoes
        user.SendMessageW(monitor.hwnd, SystemEventWindow.WM_POWERBROADCAST, SystemEventWindow.PBT_APMSUSPEND, 0)
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.PostMessageW(monitor.hwnd, SystemEventWindow.WM_POWERBROADCAST,
                          SystemEventWindow.PBT_APMRESUMEAUTOMATIC, 0)
        deadline = time.monotonic() + 2
        while len(events) < 3 and time.monotonic() < deadline:
            app.processEvents()  # Qt's event loop dispatches messages for our native window
            time.sleep(0.01)
        assert events == ["query_end_session", "suspend", "resume"]
    finally:
        monitor.close()
    assert monitor.hwnd is None
