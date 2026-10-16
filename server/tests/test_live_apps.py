import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from server.app import board as board_model
from test_server import (add_member, authorized, batch, client, seed_device, send,
                         set_sharing)


def foreground(app="Editor", process="editor.exe", when=None):
    observed = time.time() if when is None else when
    stamp = datetime.fromtimestamp(observed, timezone.utc).isoformat()
    return {"observed_at": stamp, "since": stamp,
            "app": {"app_name": app, "process_name": process} if app else None}


def test_foreground_snapshot_updates_live_app_without_inventing_usage(authorized):
    client, key = authorized
    body = batch(end=time.time() - 10)
    assert send(client, key, body).status_code == 200
    headers = {"Authorization": "Bearer " + key}
    for path, field, value in [("app-aliases", "app_aliases", "编辑器"), ("app-colors", "app_colors", "teal")]:
        assert client.put("/api/v1/agent/" + path, headers=headers, json={
            "device": body["device"], field: {"editor.exe": value}}).status_code == 200
    body["events"] = []
    body["foreground"] = foreground(when=time.time() - 1)
    assert send(client, key, body).status_code == 200
    for path in ("/api/web/live", "/api/web/board"):
        device = client.get(path).json()["people"][0]["devices"][0]
        assert device["state"] == "active" and device["last"]["process"] == "editor.exe"
        assert device["last"]["app"] == "编辑器" and device["last"]["color"] == "teal"
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*),SUM(duration_seconds) FROM events").fetchone()[:] == (1, 30)

    body["foreground"] = foreground("Old App", "old.exe", time.time() - 5)
    assert send(client, key, body).status_code == 200
    assert client.get("/api/web/live").json()["people"][0]["devices"][0]["last"]["app"] == "编辑器"
    body["foreground"] = foreground(None)
    assert send(client, key, body).status_code == 200
    assert client.get("/api/web/live").json()["people"][0]["devices"][0]["state"] == "idle"
    # Disabling the option or using an older client restores the usage-record fallback.
    body.pop("foreground")
    assert send(client, key, body).status_code == 200
    device = client.get("/api/web/live").json()["people"][0]["devices"][0]
    assert device["state"] == "active" and device["last"]["process"] == "example.exe"


@pytest.mark.parametrize("invalid", [
    {"observed_at": "2026-10-16T12:00:00", "since": "2026-10-16T12:00:00", "app": None},
    {"observed_at": "2026-10-16T12:00:00+00:00", "since": "2026-10-16T12:00:01+00:00", "app": None},
    pytest.param(lambda: foreground(when=time.time() + 600), id="future-observation"),
    {**foreground(), "app": {"app_name": "Editor", "process_name": ""}},
])
def test_invalid_foreground_rolls_back_usage(authorized, invalid):
    client, key = authorized
    body = batch()
    body["foreground"] = invalid() if callable(invalid) else invalid
    assert send(client, key, body).status_code == 422
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM device_foreground").fetchone()[0] == 0


def test_stale_foreground_expires_and_lifecycle_status_takes_precedence(authorized):
    client, key = authorized
    body = batch(end=time.time() - 600)
    body["foreground"] = foreground(when=time.time() - 400)
    assert send(client, key, body).status_code == 200
    device = client.get("/api/web/live").json()["people"][0]["devices"][0]
    assert device["state"] == "idle" and device["last"]["process"] == "example.exe"
    body["foreground"] = foreground(when=time.time() - 2)
    body["events"] = [{"id": str(uuid4()), "kind": "device_status", "reason": "suspend",
                       "occurred_at": datetime.now(timezone.utc).isoformat()}]
    assert send(client, key, body).status_code == 200
    assert client.get("/api/web/live").json()["people"][0]["devices"][0]["state"] == "asleep"


def test_foreground_respects_retention_and_device_removal(authorized):
    client, key = authorized
    body = batch()
    body["foreground"] = foreground(when=time.time() - 2 * 86400)
    assert send(client, key, body).status_code == 200
    database = client.app.state.database
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM device_foreground").fetchone()[0] == 1
    database.set_retention_days(1)
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM device_foreground").fetchone()[0] == 0
    body["foreground"] = foreground()
    assert send(client, key, body).status_code == 200
    with database.connect() as db:
        db.execute("DELETE FROM devices")
        assert db.execute("SELECT COUNT(*) FROM device_foreground").fetchone()[0] == 0


def test_live_apps_follow_new_uploads_and_keep_aliases_and_colors(authorized, monkeypatch):
    client, key = authorized
    body = batch()
    assert send(client, key, body).status_code == 200
    headers = {"Authorization": "Bearer " + key}
    assert client.put("/api/v1/agent/app-aliases", headers=headers, json={
        "device": body["device"], "app_aliases": {"example.exe": "浏览器"}}).status_code == 200
    assert client.put("/api/v1/agent/app-colors", headers=headers, json={
        "device": body["device"], "app_colors": {"example.exe": "teal"}}).status_code == 200

    def no_history(*args, **kwargs):
        raise AssertionError("Live refresh must not scan the history window")

    monkeypatch.setattr(board_model, "load_runs", no_history)
    data = client.get("/api/web/live").json()
    device = data["people"][0]["devices"][0]
    assert device["state"] == "active"
    assert device["last"]["app"] == "浏览器" and device["last"]["color"] == "teal"
    assert "runs" not in device and "ranking" not in data and "base" not in data

    # A different app in the next upload replaces the displayed name immediately.
    event = batch(end=time.time())["events"][0]
    event.update(app_name="代码编辑器", process_name="editor.exe")
    body["events"] = [event]
    assert send(client, key, body).status_code == 200
    device = client.get("/api/web/live", params={"username": "admin"}).json()["people"][0]["devices"][0]
    assert device["last"]["app"] == "代码编辑器"


def test_live_apps_respect_visibility_session_expiry_and_disabled_accounts(authorized):
    client, _ = authorized
    add_member(client, "alice", shared=True)
    add_member(client, "bob")
    for user in ("admin", "alice", "bob"):
        seed_device(client, user, user + " PC", last_seen=1, usage=[(31, 1)])
    data = client.get("/api/web/live").json()
    assert data["authenticated"] is True
    assert {p["username"] for p in data["people"]} == {"admin", "alice", "bob"}
    assert [p["username"] for p in client.get("/api/web/live?username=bob").json()["people"]] == ["bob"]

    with client.app.state.database.connect() as db:
        db.execute("UPDATE users SET enabled=0 WHERE username='bob'")
    assert client.get("/api/web/live?username=bob").status_code == 404
    with client.app.state.database.connect() as db:
        db.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
    response = client.get("/api/web/live")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["authenticated"] is False
    assert [p["username"] for p in response.json()["people"]] == ["alice"]
    for username in ("admin", "bob", "missing"):
        assert client.get("/api/web/live", params={"username": username}).status_code == 401
    assert client.get("/api/web/live?username=alice").status_code == 200


def test_live_apps_preserve_empty_and_inactive_states(authorized):
    client, _ = authorized
    assert client.get("/api/web/live").json()["people"][0]["devices"] == []
    seed_device(client, "admin", "idle", last_seen=2, usage=[(900, 600)])
    seed_device(client, "admin", "offline", last_seen=3600, usage=[(3700, 3650)])
    seed_device(client, "admin", "asleep", last_seen=995, usage=[(1100, 1000)], power=[(990, "suspend")])
    seed_device(client, "admin", "off", last_seen=995, usage=[(1100, 1000)], power=[(990, "shutdown")])
    data = client.get("/api/web/live").json()
    assert {d["name"]: d["state"] for d in data["people"][0]["devices"]} == {
        "idle": "idle", "offline": "offline", "asleep": "asleep", "off": "off"}
    set_sharing(client, True)
    client.cookies.clear()
    assert client.get("/api/web/live").status_code == 200
