import re
import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from server.app.config import Settings
from server.app.main import create_app
from server.app.security import password_hash, token_hash, verify_password


PASSWORD = "correct-password-12345"


def hidden(html):
    return re.search(r'name="csrf" value="([^"]+)"', html)[1]


def login(client, username="admin", password=PASSWORD):
    nonce = hidden(client.get("/login").text)
    return client.post("/login", data={"csrf": nonce, "username": username, "password": password})


def upload_key(client):
    page = client.get("/settings")
    result = client.post("/settings/token", data={"csrf": hidden(page.text)})
    return re.search(r'rows="3">([^<]+)</textarea>', result.text)[1]


def batch(device=None, end=None, duration=30):
    end = end or time.time() - 1
    stamp = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat()
    return {"schema_version": 1, "device": {"id": device or str(uuid4()), "name": "Test PC",
        "platform": "windows", "agent_version": "0.1.0"}, "events": [
        {"id": str(uuid4()), "kind": "app_usage", "app_name": "Example App", "process_name": "example.exe",
         "started_at": stamp(end-duration), "ended_at": stamp(end), "duration_seconds": duration}]}


def send(client, key, body):
    return client.post("/api/v1/usage/batches", headers={"Authorization": "Bearer " + key}, json=body)


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(tmp_path / "db.sqlite3", admin_username="admin", admin_password=PASSWORD))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def authorized(client):
    assert login(client).status_code == 200
    return client, upload_key(client)


def test_login_and_password_hash(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert "用户名或密码错误" in login(client, password="wrong").text
    assert "设备概览" in login(client).text
    encoded = password_hash(PASSWORD)
    assert PASSWORD not in encoded
    assert verify_password(PASSWORD, encoded)
    assert not verify_password("bad", encoded)


def test_ingestion_idempotency(authorized):
    client, key = authorized
    body = batch()
    first = send(client, key, body)
    assert first.status_code == 200
    assert first.json()["inserted"] == 1
    assert send(client, key, body).json()["duplicates"] == 1
    assert "Example App" in client.get("/").text
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_device_status_ingestion_and_deduplication(authorized):
    client, key = authorized
    body = batch()
    body["events"] = [{"id": str(uuid4()), "kind": "device_status",
                       "occurred_at": datetime.now(timezone.utc).isoformat(),
                       "reason": "suspend", "battery_percent": 82,
                       "charging": False, "ac_online": False,
                       "battery_life_seconds": 3600}]
    first = send(client, key, body)
    assert first.status_code == 200
    assert first.json()["inserted"] == 1
    assert send(client, key, body).json()["duplicates"] == 1
    with client.app.state.database.connect() as db:
        row = db.execute("SELECT reason,battery_percent FROM status_events").fetchone()
        assert tuple(row) == ("suspend", 82)


def test_tenant_isolation_and_device_ownership(authorized):
    client, admin_key = authorized
    body = batch()
    assert send(client, admin_key, body).status_code == 200
    csrf = hidden(client.get("/admin/users").text)
    client.post("/admin/users", data={"csrf": csrf, "username": "alice", "password": PASSWORD})
    client.cookies.clear()
    login(client, "alice")
    alice_key = upload_key(client)
    assert "Test PC" not in client.get("/").text
    assert client.get("/?device=" + body["device"]["id"]).status_code == 404
    assert client.get("/admin/users").status_code == 403
    assert send(client, alice_key, body).status_code == 409
    assert send(client, alice_key, batch()).status_code == 200


def test_token_rotation_and_disable_account(authorized):
    client, old = authorized
    new = upload_key(client)
    assert send(client, old, batch()).status_code == 401
    assert send(client, new, batch()).status_code == 200
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT upload_hash FROM users").fetchone()[0] == token_hash(new)
        db.execute("UPDATE users SET enabled=0")
    assert send(client, new, batch()).status_code == 401
    assert client.get("/settings").status_code == 401


def test_csrf_protection(authorized):
    client, key = authorized
    assert client.post("/settings/token").status_code == 403
    assert client.post("/admin/users", data={"username": "mallory", "password": PASSWORD}).status_code == 403
    assert client.post("/logout").status_code == 403


def test_login_csrf_and_rate_limit(client):
    assert client.post("/login", data={"username": "admin", "password": PASSWORD}).status_code == 403
    for _ in range(10):
        assert login(client, password="wrong").status_code == 200
    assert login(client).status_code == 429


@pytest.mark.parametrize("mutate", [
    lambda x: x["events"][0].update(duration_seconds=6000),
    lambda x: x["events"][0].update(duration_seconds=12),
    lambda x: x["events"][0].update(started_at="2026-01-01T10:00:00"),
    lambda x: x["events"][0].update(window_title="private document"),
    lambda x: x.update(schema_version=2),
])
def test_invalid_payloads_rejected(authorized, mutate):
    client, key = authorized
    body = batch()
    mutate(body)
    assert send(client, key, body).status_code == 422


def test_future_clock_rejected(authorized):
    client, key = authorized
    assert send(client, key, batch(end=time.time()+600)).status_code == 422


def test_old_records_acknowledged_and_trimmed(authorized):
    client, key = authorized
    database = client.app.state.database
    old = batch(end=time.time()-366*86400)
    result = send(client, key, old).json()
    assert result["expired"] == 1
    assert result["acknowledged_ids"] == [old["events"][0]["id"]]
    boundary = batch(end=database.cutoff()+15, duration=30)
    assert send(client, key, boundary).status_code == 200
    with database.connect() as db:
        row = db.execute("SELECT * FROM events").fetchone()
        assert row["duration_seconds"] <= 15
        db.execute("UPDATE events SET started_at=?,ended_at=?", (database.cutoff()-60, database.cutoff()-30))
    database.cleanup()
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_batch_rollback_on_conflicting_id(authorized):
    client, key = authorized
    original = batch()
    send(client, key, original)
    changed = batch(device=original["device"]["id"])
    conflicting = dict(original["events"][0], app_name="Different App")
    changed["events"].append(conflicting)
    assert send(client, key, changed).status_code == 409
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_request_size_and_security_headers(client):
    response = client.post("/api/v1/usage/batches", content=b"x" * (2*1024*1024+1))
    assert response.status_code == 413
    assert client.get("/healthz").headers["X-Frame-Options"] == "DENY"


def test_password_change_invalidates_sessions(authorized):
    client, key = authorized
    csrf = hidden(client.get("/settings").text)
    result = client.post("/settings/password", data={"csrf": csrf, "old_password": PASSWORD,
                        "new_password": "brand-new-password-6789"}, follow_redirects=False)
    assert result.status_code == 303
    assert client.get("/settings").status_code == 401
    assert "设备概览" in login(client, password="brand-new-password-6789").text
    assert send(client, key, batch()).status_code == 200


def test_retention_never_exceeds_one_year(tmp_path):
    with pytest.raises(ValueError):
        Settings(tmp_path / "db", retention_days=366)
    with pytest.raises(ValueError):
        Settings(tmp_path / "db", retention_days=0)


def test_xss_is_escaped(authorized):
    client, key = authorized
    body = batch()
    body["events"][0]["app_name"] = "<script>alert(1)</script>"
    send(client, key, body)
    assert "<script>alert(1)</script>" not in client.get("/").text
    assert "&lt;script&gt;" in client.get("/").text
