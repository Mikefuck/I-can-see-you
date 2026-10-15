"""Render our own GUI with synthetic records, without desktop sampling or network requests.

Set QT_QPA_PLATFORM=windows to render through the real Windows platform instead of the offscreen one, and pass
a directory to write the images there instead of client/docs."""
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
CLIENT = Path(__file__).resolve().parents[1]
ROOT = CLIENT.parent
sys.path.insert(0, str(CLIENT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from focus_agent import gui
from focus_agent import motion
from focus_agent.config import Config
from focus_agent.store import EventStore
from focus_agent.tracker import Application
from focus_agent.process_picker import ProcessPicker

APPS = [("Microsoft Edge", "msedge.exe"), ("Visual Studio Code", "Code.exe"), ("微信", "Weixin.exe"),
        ("Windows 文件资源管理器", "explorer.exe"), ("Microsoft Word", "WINWORD.EXE")]
# A working day in local clock hours; the spans that have not happened yet are left out.
DAY = [(8.7, 10.1), (10.35, 11.9), (13.5, 15.2), (15.45, 17.8), (19.2, 21.0)]


class FakeReader:
    def sample(self, idle):
        return Application("Microsoft Edge", "msedge.exe"), "正在记录前台应用"


class FakeUploader:
    def __init__(self, store, config):
        self.messages = Queue()

    def start(self):
        pass

    def stop(self):
        pass

    def trigger(self):
        pass

    def flush(self, timeout=3.0):
        return True

    def configure(self, config):
        pass


class FakeBattery:
    def status(self):
        return {"battery_percent": 82, "charging": True, "ac_online": True, "battery_life_seconds": None}


class NoSystemEvents:
    def __init__(self, callback):
        pass

    def close(self):
        pass


def iso(moment):
    return datetime.fromtimestamp(moment, timezone.utc).isoformat()


def synthetic_day(now):
    """Usage in five-minute segments plus the startup / sleep / wake nodes around it, all before now."""
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    spans = [(midnight + a * 3600, min(midnight + b * 3600, now - 60)) for a, b in DAY if midnight + a * 3600 < now - 600]
    if len(spans) < 2:  # early in the day: show the last few hours instead
        spans = [(now - a * 3600, now - b * 3600) for a, b in [(5.2, 3.9), (3.6, 2.1), (1.8, 0.02)]]
    usage, status = [], []
    for index, (start, end) in enumerate(spans):
        moment, turn = start, index
        while moment < end:
            stop = min(moment + 300, end)
            name, process = APPS[turn % len(APPS)]
            usage.append({"id": str(uuid4()), "kind": "app_usage", "app_name": name, "process_name": process,
                          "started_at": iso(moment), "ended_at": iso(stop), "duration_seconds": stop - moment})
            moment, turn = stop, turn + (1 if (turn * 7 + index) % 3 else 2)
    nodes = [(spans[0][0] - 120, "startup")]
    for (_, end), (start, _) in zip(spans, spans[1:]):
        if start - end > 1800:
            nodes += [(end + 60, "suspend"), (start - 60, "resume")]
    for moment, reason in nodes:
        status.append({"id": str(uuid4()), "kind": "device_status", "occurred_at": iso(moment), "reason": reason,
                       "battery_percent": 82, "charging": True, "ac_online": True, "battery_life_seconds": None})
    return usage, status


def main():
    # Static documentation images should capture the destination, never a half-finished transition.
    motion.animations_enabled = lambda: False
    gui.ForegroundReader, gui.Uploader, gui.BatteryReader = FakeReader, FakeUploader, FakeBattery
    gui.SystemEventWindow, gui.startup_enabled = NoSystemEvents, lambda: True
    app = QApplication([])
    # The offscreen Qt backend does not enumerate Windows fonts automatically.
    for font_file in ("msyh.ttc", "msyhbd.ttc", "arial.ttf", "arialbd.ttf", "bahnschrift.ttf"):
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font_file)
    gui.apply_typography(app)
    data = ROOT / ".runtime" / "gui-preview"
    for name in ("cache.sqlite3", "cache.sqlite3-wal", "cache.sqlite3-shm"):
        (data / name).unlink(missing_ok=True)
    store = EventStore(data / "cache.sqlite3")
    config = Config(host="192.168.1.10", api_key="demo-key-" + "x"*35, account_id=1,
                    username="alice", device_name="我的工作电脑", silent_start=True, startup=True,
                    app_aliases={"weixin.exe": "微信"})
    usage, status = synthetic_day(time.time())
    store.add(config, usage + status)
    store.acknowledge(config.destination, [event["id"] for event in (usage + status)[:-4]])
    window = gui.MainWindow(config, data / "config.json", store)
    window.upload_status.setText("上传成功 · 14:32:08")
    window.resize(1080, 820)
    window.show()
    window.tracker.start = time.time() - 95  # the current app has been in front for a while
    window.tick()
    app.processEvents()
    docs = Path(sys.argv[1]) if len(sys.argv) > 1 else CLIENT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for theme in ("light", "dark"):
        window.config = replace(window.config, theme=theme)
        window.apply_theme()
        for page, name in ((window.LEDGER, "ledger"), (window.SETTINGS, "settings"), (window.MANAGEMENT, "management")):
            window.show_page(page)
            app.processEvents()
            assert window.grab().save(str(docs / f"client-{name}-{theme}-preview.png"))
    window.config = replace(window.config, theme="light")
    window.apply_theme()
    window.show_page(window.LEDGER)
    app.processEvents()
    assert window.grab().save(str(docs / "client-preview.png"))
    window.show_page(window.SETTINGS)
    app.processEvents()
    assert window.grab().save(str(docs / "client-settings-preview.png"))
    window.show_page(window.LEDGER)
    window.resize(860, 600)
    app.processEvents()
    assert window.grab().save(str(docs / "client-small-preview.png"))
    window.resize(1080, 820)
    window.stop_collection()
    app.processEvents()
    assert window.grab().save(str(docs / "client-paused-preview.png"))
    picker = ProcessPicker(window, config.app_aliases,
                           loader=lambda: [Application(name, process) for name, process in APPS])
    deadline = time.monotonic() + 3
    while picker.loading and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not picker.loading
    picker.show()
    picker.toggle_row(0, 1)
    picker.toggle_row(1, 1)
    for theme in ("light", "dark"):
        window.config = replace(window.config, theme=theme)
        window.apply_theme()
        app.processEvents()
        assert picker.grab().save(str(docs / f"client-process-picker-{theme}-preview.png"))
    picker.close()
    window.quit_app()
    print("GUI preview rendered successfully")


if __name__ == "__main__":
    main()
