import copy
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from server.app.database import Database
from test_server import client, authorized, PASSWORD, batch, send


PREFIX = "/api/v1/management"


def desktop_login(client, username="admin"):
    response = client.post(PREFIX + "/login", json={"username": username, "password": PASSWORD},
                           headers={"X-FocusLedger-Client": "desktop"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_management_login_csrf_and_upload_token_separation(client):
    assert client.post(PREFIX + "/login", json={"username": "admin", "password": PASSWORD}).status_code == 403
    headers = desktop_login(client)
    assert client.get(PREFIX + "/users").json()["users"][0]["username"] == "admin"
    assert client.put(PREFIX + "/settings", json={"retention_days": 20}).status_code == 403
    assert client.put(PREFIX + "/settings", json={"retention_days": 20}, headers=headers).status_code == 200
    key = client.post(PREFIX + "/token", json={}, headers=headers).json()["api_key"]
    client.cookies.clear()
    assert client.get(PREFIX + "/users", headers={"Authorization": "Bearer " + key}).status_code == 401
    assert send(client, key, batch()).status_code == 200


def test_management_user_lifecycle_and_revocation(client):
    headers = desktop_login(client)
    body = {"username": "alice", "password": PASSWORD, "is_admin": False}
    response = client.post(PREFIX + "/users", json=body, headers=headers)
    assert response.status_code == 200
    identity = response.json()["id"]
    assert client.post(PREFIX + "/users", json=body, headers=headers).status_code == 409
    assert client.post(PREFIX + "/users", json={**body, "username": "bob", "password": "short"}, headers=headers).status_code == 422
    member = TestClient(client.app)
    member_headers = desktop_login(member, "alice")
    for path in ("/users", "/settings"):
        assert member.get(PREFIX + path).status_code == 403
    assert member.post(PREFIX + "/users", json=body, headers=member_headers).status_code == 403
    assert member.put(PREFIX + "/settings", json={"retention_days": 1}, headers=member_headers).status_code == 403
    key = member.post(PREFIX + "/token", json={}, headers=member_headers).json()["api_key"]
    assert send(member, key, batch()).status_code == 200
    assert client.patch(PREFIX + f"/users/{identity}", json={"enabled": False}, headers=headers).status_code == 200
    assert send(member, key, batch()).status_code == 401
    assert member.post(PREFIX + "/token", json={}, headers=member_headers).status_code == 401
    assert client.patch(PREFIX + f"/users/{identity}", json={"enabled": True}, headers=headers).status_code == 200
    assert send(member, key, batch()).status_code == 401
    desktop_login(member, "alice")
    assert client.patch(PREFIX + "/users/1", json={"enabled": False}, headers=headers).status_code == 400
    assert "password_hash" not in client.get(PREFIX + "/users").text


def test_retention_update_is_validated_persisted_and_applied(client):
    headers = desktop_login(client)
    key = client.post(PREFIX + "/token", json={}, headers=headers).json()["api_key"]
    assert send(client, key, batch(end=time.time() - 10 * 86400)).status_code == 200
    for days in (0, 366, 1.5, "2"):
        assert client.put(PREFIX + "/settings", json={"retention_days": days}, headers=headers).status_code == 422
    assert client.put(PREFIX + "/settings", json={"retention_days": 2}, headers=headers).json()["retention_days"] == 2
    db = client.app.state.database
    assert db.retention_days == 2
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    reopened = Database(db.settings)
    reopened.initialize()
    assert reopened.retention_days == 2
    assert client.get("/api/v1/agent/check", headers={"Authorization": "Bearer " + key}).json()["retention_days"] == 2
    assert client.post(PREFIX + "/logout", json={}, headers=headers).status_code == 200
    assert client.get(PREFIX + "/settings").status_code == 401


@pytest.mark.parametrize("at_boundary", [False, True])
def test_event_span_conflict_and_retry_after_retention_trim(authorized, at_boundary):
    client, key = authorized
    cutoff = client.app.state.database.cutoff()
    original = batch(end=cutoff + 15 if at_boundary else None)
    assert send(client, key, original).status_code == 200
    client.app.state.database.cleanup()
    assert send(client, key, original).json()["duplicates"] == 1
    changed = copy.deepcopy(original)
    event = changed["events"][0]
    end = datetime.fromisoformat(event["ended_at"]).timestamp()
    event["started_at"] = datetime.fromtimestamp(end - 60, timezone.utc).isoformat()
    event["duration_seconds"] = 60
    assert send(client, key, changed).status_code == 409


def test_legacy_database_migration_preserves_records_and_deduplication(authorized):
    client, key = authorized
    original = batch()
    assert send(client, key, original).status_code == 200
    database = client.app.state.database
    with database.connect() as db:
        db.execute("ALTER TABLE events DROP COLUMN payload_hash")
        db.execute("DROP TABLE runtime_settings")
    database.initialize()
    with database.connect() as db:
        assert "payload_hash" in {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert database.retention_days == 365
    assert send(client, key, original).json()["duplicates"] == 1
