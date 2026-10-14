import sqlite3
import time
from contextlib import contextmanager

from .security import password_hash, valid_username


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    upload_hash TEXT UNIQUE,
    created_at REAL NOT NULL,
    shared INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    row_id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    app_name TEXT NOT NULL,
    process_name TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL NOT NULL,
    duration_seconds REAL NOT NULL,
    UNIQUE(user_id, device_id, event_id)
);
CREATE TABLE IF NOT EXISTS status_events (
    row_id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    occurred_at REAL NOT NULL,
    reason TEXT NOT NULL,
    battery_percent INTEGER,
    charging INTEGER,
    ac_online INTEGER,
    battery_life_seconds INTEGER,
    UNIQUE(user_id, device_id, event_id)
);
CREATE INDEX IF NOT EXISTS events_owner_time ON events(user_id, ended_at);
CREATE INDEX IF NOT EXISTS events_device_time ON events(device_id, ended_at);
CREATE INDEX IF NOT EXISTS status_owner_time ON status_events(user_id, occurred_at);
CREATE INDEX IF NOT EXISTS status_device_time ON status_events(device_id, occurred_at);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS events_expiry ON events(ended_at);
"""


class Database:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.database

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            # Databases created before opt-in sharing keep every account private.
            if "shared" not in {row["name"] for row in db.execute("PRAGMA table_info(users)")}:
                db.execute("ALTER TABLE users ADD COLUMN shared INTEGER NOT NULL DEFAULT 0")
            count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if not count:
                username = self.settings.admin_username
                if not valid_username(username):
                    raise ValueError("First start requires ADMIN_USERNAME (3–40 letters, digits, _ . -)")
                encoded = password_hash(self.settings.admin_password)
                db.execute(
                    "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,1,?)",
                    (username, encoded, time.time()),
                )
        self.cleanup()

    def cutoff(self):
        return time.time() - self.settings.retention_days * 86400

    def cleanup(self):
        cutoff = self.cutoff()
        with self.connect() as db:
            db.execute("DELETE FROM events WHERE ended_at <= ?", (cutoff,))
            db.execute("DELETE FROM status_events WHERE occurred_at <= ?", (cutoff,))
            # Trim a segment straddling the cutoff so no part older than the limit is retained.
            db.execute(
                "UPDATE events SET duration_seconds=ended_at-?, started_at=? WHERE started_at < ?",
                (cutoff, cutoff, cutoff),
            )
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
            db.execute("DELETE FROM devices WHERE last_seen <= ? AND NOT EXISTS "
                       "(SELECT 1 FROM events WHERE events.device_id=devices.id)", (cutoff,))
        with self.connect() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
