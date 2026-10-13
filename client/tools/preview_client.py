"""Render our own GUI with synthetic records, without desktop sampling or network requests."""
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from uuid import uuid4

os.environ["QT_QPA_PLATFORM"] = "offscreen"
CLIENT = Path(__file__).resolve().parents[1]
ROOT = CLIENT.parent
sys.path.insert(0, str(CLIENT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from focus_agent import gui
from focus_agent.config import Config
from focus_agent.store import EventStore
from focus_agent.tracker import Application


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


def main():
    gui.ForegroundReader, gui.Uploader, gui.BatteryReader = FakeReader, FakeUploader, FakeBattery
    gui.SystemEventWindow, gui.startup_enabled = NoSystemEvents, lambda: True
    app = QApplication([])
    # The offscreen Qt backend does not enumerate Windows fonts automatically.
    for font_file in ("msyh.ttc", "msyhbd.ttc", "arial.ttf", "arialbd.ttf"):
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font_file)
    gui.apply_typography(app)
    data = ROOT / ".runtime" / "gui-preview"
    store = EventStore(data / "cache.sqlite3")
    config = Config(host="192.168.1.10", api_key="demo-key-" + "x"*35, account_id=1,
                    username="alice", device_name="我的工作电脑", silent_start=True, startup=True)
    records = []
    for i, (name, process) in enumerate([("Microsoft Edge", "msedge.exe"), ("Visual Studio Code", "Code.exe"),
                                       ("Windows 文件资源管理器", "explorer.exe")]):
        end = time.time() - i*35
        records.append({"id": str(uuid4()), "kind": "app_usage", "app_name": name, "process_name": process,
                        "started_at": datetime.fromtimestamp(end-30, timezone.utc).isoformat(),
                        "ended_at": datetime.fromtimestamp(end, timezone.utc).isoformat(), "duration_seconds": 30})
    store.add(config, records)
    store.acknowledge(config.destination, [records[1]["id"], records[2]["id"]])
    window = gui.MainWindow(config, data / "config.json", store)
    window.upload_status.setText("上传成功 · 14:32:08")
    window.resize(1040, 880)
    window.show()
    app.processEvents()
    target = CLIENT / "docs" / "client-preview.png"
    assert window.grab().save(str(target))
    window.resize(860, 600)
    app.processEvents()
    assert window.grab().save(str(CLIENT / "docs" / "client-small-preview.png"))
    window.resize(1040, 880)
    window.stop_collection()
    app.processEvents()
    assert window.grab().save(str(CLIENT / "docs" / "client-paused-preview.png"))
    window.quit_app()
    print("GUI preview rendered successfully")


if __name__ == "__main__":
    main()
