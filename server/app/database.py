import logging
import sqlite3
import time
from contextlib import contextmanager

from .security import password_hash, valid_username, verify_password


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
    payload_hash TEXT,
    UNIQUE(user_id, device_id, event_id)
);
CREATE TABLE IF NOT EXISTS device_app_aliases (
    device_id TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    aliases TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS runtime_settings (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS admin_environment (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL
);
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
            if "payload_hash" not in {row["name"] for row in db.execute("PRAGMA table_info(events)")}:
                db.execute("ALTER TABLE events ADD COLUMN payload_hash TEXT")
            self._sync_admin(db)
        self.cleanup()

    def _sync_admin(self, db):
        username, password = self.settings.admin_username, self.settings.admin_password
        empty = not db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        # Existing databases may be operated without environment credentials.
        if not empty and not username and not password:
            return
        if not valid_username(username):
            raise ValueError("ADMIN_USERNAME is required (3–40 letters, digits, _ . -)")
        if not 12 <= len(password) <= 256:
            raise ValueError("ADMIN_PASSWORD must contain 12–256 characters (密码长度须为 12–256 个字符)")
        if empty:
            db.execute(
                "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,1,?)",
                (username, password_hash(password), time.time()),
            )
        admin = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not admin or not admin["is_admin"] or not admin["enabled"]:
            raise ValueError("ADMIN_USERNAME must identify an existing enabled administrator; "
                             "it cannot rename, promote or re-enable an account")
        previous = db.execute("SELECT password_hash FROM admin_environment WHERE user_id=?",
                              (admin["id"],)).fetchone()
        # Keep a website password change across restarts when Compose is unchanged.
        if previous and verify_password(password, previous["password_hash"]):
            return
        encoded = admin["password_hash"]
        if not verify_password(password, encoded):
            encoded = password_hash(password)
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, admin["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (admin["id"],))
            logging.warning("ADMIN_PASSWORD changed: administrator password synchronized; old sessions revoked")
        # The last environment value is stored only as a salted password hash.
        db.execute("INSERT INTO admin_environment VALUES(?,?) ON CONFLICT(user_id) DO UPDATE "
                   "SET password_hash=excluded.password_hash", (admin["id"], encoded))

    @property
    def retention_days(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM runtime_settings WHERE key='retention_days'").fetchone()
        return row[0] if row else self.settings.retention_days

    def set_retention_days(self, days):
        if type(days) is not int or not 1 <= days <= 365:
            raise ValueError("数据保留天数须为 1–365")
        with self.connect() as db:
            db.execute("INSERT INTO runtime_settings VALUES('retention_days',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (days,))
        self.cleanup()

    def cutoff(self):
        return time.time() - self.retention_days * 86400

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
