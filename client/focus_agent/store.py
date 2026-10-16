import json
import sqlite3
import time
from contextlib import contextmanager


PENDING, SENT, REJECTED = 0, 1, 2


class EventStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY,destination TEXT NOT NULL,"
                       "device TEXT NOT NULL,payload TEXT NOT NULL,ended_at REAL NOT NULL,sent INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE INDEX IF NOT EXISTS queue ON events(destination,sent,ended_at)")
        self.cleanup()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, config, events):
        from datetime import datetime
        from . import __version__
        if not events:
            return
        device = json.dumps({"id": config.device_id, "name": config.device_name,
                             "platform": "windows", "agent_version": __version__}, ensure_ascii=False)
        with self.connect() as db:
            db.executemany("INSERT INTO events(id,destination,device,payload,ended_at) VALUES(?,?,?,?,?)",
                [(event["id"], config.destination, device, json.dumps(event, ensure_ascii=False),
                  datetime.fromisoformat(event.get("ended_at") or event["occurred_at"]).timestamp()) for event in events])

    def batch(self, destination, limit=500):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE destination=? AND sent=0 ORDER BY ended_at LIMIT ?",
                              (destination, limit)).fetchall()
        if not rows:
            return None
        device = json.loads(rows[0]["device"])
        # A batch belongs to exactly one device, including queues left by older configurations.
        selected = [row for row in rows if json.loads(row["device"])["id"] == device["id"]]
        return {"schema_version": 1, "device": device, "events": [json.loads(row["payload"]) for row in selected]}

    def acknowledge(self, destination, ids):
        with self.connect() as db:
            db.executemany("UPDATE events SET sent=1 WHERE destination=? AND id=?", [(destination, x) for x in ids])

    def reject(self, destination, ids):
        """Set aside records the server declared invalid so they cannot block the rest of the queue."""
        with self.connect() as db:
            db.executemany("UPDATE events SET sent=2 WHERE destination=? AND id=? AND sent=0",
                           [(destination, x) for x in ids])

    def counts(self, destination):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM events WHERE sent=0").fetchone()[0]
            current = db.execute("SELECT COUNT(*) FROM events WHERE sent=0 AND destination=?", (destination,)).fetchone()[0]
        return current, total

    def recent(self, destination):
        with self.connect() as db:
            rows = db.execute("SELECT payload,sent FROM events WHERE destination=? ORDER BY ended_at DESC LIMIT 50",
                              (destination,)).fetchall()
        return [(json.loads(row["payload"]), row["sent"]) for row in rows]

    def between(self, destination, start, end):
        """Records that ended in [start, end), oldest first; the day strip reads today's records with it."""
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM events WHERE destination=? AND ended_at>=? AND ended_at<? "
                              "ORDER BY ended_at", (destination, start, end)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def clear_pending(self):
        with self.connect() as db:
            db.execute("DELETE FROM events WHERE sent=0")

    def cleanup(self):
        now = time.time()
        with self.connect() as db:
            db.execute("DELETE FROM events WHERE ended_at<? OR (sent!=0 AND ended_at<?)",
                       (now - 30 * 86400, now - 7 * 86400))
            db.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY ended_at DESC LIMIT -1 OFFSET 100000)")
        with self.connect() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
