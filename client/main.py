import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler


def main():
    parser = argparse.ArgumentParser(description="Focus Ledger Windows agent")
    parser.add_argument("--startup", action="store_true")
    parser.add_argument("--show", action="store_true", help="Ignore silent-start setting")
    parser.add_argument("--silent", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This client requires Windows 10/11.")
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
    from focus_agent.config import data_directory, load_config
    from focus_agent.gui import MainWindow, apply_typography
    from focus_agent.store import EventStore
    from focus_agent.winapi import SingleInstance, activate_running_instance, decrypt, refresh_startup_path

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Focus Ledger")
    apply_typography(app)
    app.setQuitOnLastWindowClosed(False)
    instance = SingleInstance()
    if instance.already_running:
        # Launching the program again opens the running copy, which may be sitting silently in the tray.
        if not args.startup and not activate_running_instance():
            QMessageBox.information(None, "专注记录已运行", "请点击系统托盘中的专注记录图标打开主窗口。")
        instance.close()
        return 0
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "agent.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(handlers=[handler], level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(directory / "config.json", decrypt)
        if config.startup:
            try:
                refresh_startup_path()
            except OSError:
                logging.exception("Unable to update the startup entry")
        store = EventStore(directory / "events.sqlite3")
        window = MainWindow(config, directory / "config.json", store)
        hide = config.configured and (args.silent or config.silent_start) and not args.show
        if not hide or not QSystemTrayIcon.isSystemTrayAvailable():
            window.show()
        return app.exec()
    except Exception as exc:
        logging.exception("Startup failed")
        QMessageBox.critical(None, "启动失败", f"程序无法启动：{exc}\n配置与缓存位置：{directory}")
        return 1
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
