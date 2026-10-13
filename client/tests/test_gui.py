import ctypes
import os
import sys
import time
from ctypes import wintypes
from queue import Queue

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from focus_agent import gui
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
        config = Config(host="127.0.0.1", api_key="x"*43, account_id=1, username="alice", **options)
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
