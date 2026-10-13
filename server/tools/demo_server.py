"""Local preview with synthetic usage only. The credentials are for this demo, not deployment."""
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import uvicorn
from server.app.config import Settings
from server.app.main import create_app


def main():
    app = create_app(Settings(ROOT / ".runtime" / "demo" / "demo.sqlite3",
                             admin_username="demo", admin_password="preview-only-123456"))
    database = app.state.database
    database.initialize()
    with database.connect() as db:
        owner = db.execute("SELECT id FROM users WHERE username='demo'").fetchone()[0]
        if not db.execute("SELECT 1 FROM devices").fetchone():
            now = time.time()
            for name, platform in [("我的工作电脑", "windows"), ("家里的电脑", "windows")]:
                device_id = str(uuid4())
                db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?)",
                           (device_id, owner, name, platform, "0.1.0", now-5*86400, now))
                for i in range(60):
                    app_name, process = [("Microsoft Edge", "msedge.exe"), ("Visual Studio Code", "Code.exe"),
                                         ("Windows 文件资源管理器", "explorer.exe")][i % 3]
                    end = now - i*75
                    db.execute("INSERT INTO events(event_id,user_id,device_id,kind,app_name,process_name,started_at,ended_at,duration_seconds) "
                               "VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid4()), owner, device_id, "app_usage", app_name,
                               process, end-30, end, 30))
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
