"""Local preview with synthetic usage only. The credentials are for this demo, not deployment.

Every start rebuilds the demo database so the board is anchored to the current time: several
members, some sharing their records, desktops and laptops in every state the board can show.
"""
import random
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import uvicorn
from server.app.config import Settings
from server.app.main import create_app
from server.app.security import password_hash

PASSWORD = "preview-only-123456"
PROFILES = {
    "dev": [("Visual Studio Code", "Code.exe", 6), ("Microsoft Edge", "msedge.exe", 3),
            ("Windows Terminal", "WindowsTerminal.exe", 2), ("微信", "Weixin.exe", 1)],
    "design": [("Figma", "Figma.exe", 6), ("Adobe Photoshop", "Photoshop.exe", 3),
               ("Microsoft Edge", "msedge.exe", 2), ("企业微信", "WXWork.exe", 1)],
    "office": [("Microsoft Excel", "EXCEL.EXE", 4), ("Microsoft Outlook", "OUTLOOK.EXE", 3),
               ("Microsoft Teams", "ms-teams.exe", 2), ("Microsoft Edge", "msedge.exe", 2)],
    "home": [("哔哩哔哩", "bilibili.exe", 3), ("Microsoft Edge", "msedge.exe", 3),
             ("Steam", "steam.exe", 2), ("网易云音乐", "cloudmusic.exe", 1)],
}
# owner, device, profile, has battery, today's blocks as (minutes ago start, minutes ago end), final state
DEVICES = [
    ("demo", "工作电脑", "dev", False, [(470, 300), (230, 0)], "active"),
    ("demo", "家里的笔记本", "home", True, [(760, 690)], "asleep"),
    ("alice", "ThinkPad X1", "design", True, [(520, 330), (260, 0)], "active"),
    ("bob", "财务部台式机", "office", False, [(600, 420), (330, 26)], "idle"),
    ("bob", "Surface Go", "home", True, [(900, 850)], "off"),
    ("carol", "前台电脑", "office", False, [(300, 0)], "active"),
]
# Usual working hours on earlier days, per profile. One member's devices never overlap: nobody uses two at once.
HISTORY = {"dev": [(9.1, 12.2), (13.4, 18.6)], "design": [(8.8, 12.0), (13.1, 17.9)],
           "office": [(9.0, 11.9), (13.0, 17.5)], "home": [(19.4, 23.2)]}


def segments(rng, apps, start, end, length):
    """Contiguous tracker-style segments, switching apps every few minutes with short idle gaps."""
    names = [(name, process) for name, process, _ in apps]
    weights = [weight for *_, weight in apps]
    t = start
    while t < end - 5:
        app = rng.choices(names, weights)[0]
        stay = min(end, t + rng.uniform(3, 28) * 60)
        while t < stay - 1:
            step = min(length, stay - t)
            yield app, t, t + step
            t += step
        if rng.random() < 0.18:
            t += rng.uniform(60, 240)


def add_event(db, user, device, app, process, start, end):
    db.execute("INSERT INTO events(event_id,user_id,device_id,kind,app_name,process_name,started_at,ended_at,"
               "duration_seconds) VALUES(?,?,?,?,?,?,?,?,?)",
               (str(uuid4()), user, device, "app_usage", app, process, start, end, end - start))


def keep_alive(database, live):
    """Devices that end the demo awake keep reporting, so the board stays live while you look at it."""
    rng = random.Random(11)
    while True:
        time.sleep(10)
        now = time.time()
        with database.connect() as db:
            for item in live:
                if item["state"] == "active":
                    if now >= item["switch"]:
                        apps = PROFILES[item["profile"]]
                        item["app"] = rng.choices([(name, process) for name, process, _ in apps], [weight for *_, weight in apps])[0]
                        item["switch"] = now + rng.uniform(3, 28) * 60
                    if now - 1 - item["end"] > .5:
                        add_event(db, item["user"], item["device"], *item["app"], item["end"], now - 1)
                        item["end"] = now - 1
                db.execute("UPDATE devices SET last_seen=? WHERE id=?", (now, item["device"]))


def seed(database):
    rng = random.Random(7)
    now = time.time()
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    live = []
    with database.connect() as db:
        users = {}
        for username, admin, shared in [("demo", 1, 1), ("alice", 0, 1), ("bob", 0, 1), ("carol", 0, 0)]:
            if username != "demo":
                db.execute("INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,?,?)",
                           (username, password_hash(PASSWORD), admin, now - 90 * 86400))
            db.execute("UPDATE users SET shared=? WHERE username=?", (shared, username))
            users[username] = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
        for owner, name, profile, battery, blocks, state in DEVICES:
            device, user = str(uuid4()), users[owner]
            events, status = [], []
            for days_ago in range(120, 0, -1):
                day = midnight - timedelta(days=days_ago)
                if rng.random() < (0.45 if day.weekday() >= 5 else 0.08):
                    continue
                spans = [(day + timedelta(hours=a + rng.uniform(-.4, .4)), day + timedelta(hours=b + rng.uniform(-.5, .5)))
                         for a, b in HISTORY[profile] if rng.random() < .9]
                for a, b in spans:
                    events += segments(rng, PROFILES[profile], a.timestamp(), b.timestamp(), 300)
                if spans:
                    status.append((spans[0][0].timestamp() - 40, "startup"))
                    status.append((spans[-1][1].timestamp() + 20, "shutdown" if not battery else "suspend"))
            today = [(max(now - a * 60, midnight.timestamp()), now - b * 60 - (8 if b == 0 else 0))
                     for a, b in blocks if now - b * 60 > midnight.timestamp()]
            for index, (a, b) in enumerate(today):
                events += segments(rng, PROFILES[profile], a, b, 30)
                status.append((a - 30, "startup" if index == 0 else "resume"))
                if index < len(today) - 1:
                    status.append((b + 15, "suspend"))
            last_end = max((end for _, _, end in events), default=now - 3 * 86400)
            if state in ("active", "idle"):
                last_seen = now - rng.uniform(4, 20)
            else:
                status.append((last_end + 25, "shutdown" if state == "off" else "suspend"))
                last_seen = last_end + 27
            db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?)",
                       (device, user, name, "windows", "0.1.0", now - 120 * 86400, last_seen))
            for (app, process), start, end in events:
                add_event(db, user, device, app, process, start, end)
            if state in ("active", "idle"):
                live.append({"device": device, "user": user, "profile": profile, "state": state,
                             "end": last_end, "app": None, "switch": 0})
            if battery:
                # Readings every five minutes while awake; drains on battery, recharges on the charger.
                level, charging = 96.0, False
                for start, end in today:
                    t = start
                    while t < end:
                        charging = level < 35 or (charging and level < 95)
                        level = min(100.0, level + 2.6) if charging else max(5.0, level - rng.uniform(.6, 1.1))
                        db.execute("INSERT INTO status_events(event_id,user_id,device_id,occurred_at,reason,battery_percent,"
                                   "charging,ac_online,battery_life_seconds) VALUES(?,?,?,?,?,?,?,?,?)",
                                   (str(uuid4()), user, device, t, "periodic", round(level), charging, charging,
                                    None if charging else int(level * 260)))
                        t += 300
            for at, reason in status:
                db.execute("INSERT INTO status_events(event_id,user_id,device_id,occurred_at,reason,battery_percent,"
                           "charging,ac_online,battery_life_seconds) VALUES(?,?,?,?,?,?,?,?,?)",
                           (str(uuid4()), user, device, at, reason, None, None, None, None))
    return live


def main():
    path = ROOT / ".runtime" / "demo" / "demo.sqlite3"
    for stale in path.parent.glob(path.name + "*"):
        stale.unlink()
    app = create_app(Settings(path, admin_username="demo", admin_password=PASSWORD))
    database = app.state.database
    database.initialize()
    live = seed(database)
    threading.Thread(target=keep_alive, args=(database, live), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
