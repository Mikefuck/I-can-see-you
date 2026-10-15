import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from server.app import board as board_model
from server.app.config import Settings
from server.app.database import Database
from server.app.main import create_app
from server.app.security import password_hash, token_hash, verify_password


PASSWORD = "correct-password-12345"
APP = Path(__file__).parents[1] / "app"


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


def add_member(client, username, shared=False):
    """Create an account as the signed-in admin."""
    data = {"csrf": hidden(client.get("/admin/users").text), "username": username, "password": PASSWORD}
    if shared:
        data["shared"] = "on"
    assert client.post("/admin/users", data=data, follow_redirects=False).status_code == 303


def switch_to(client, username):
    client.cookies.clear()
    assert login(client, username).status_code == 200


def set_sharing(client, on):
    data = {"csrf": hidden(client.get("/settings").text), "shared": "on" if on else "off"}
    assert client.post("/settings/sharing", data=data, follow_redirects=False).status_code == 303


def board(client, **query):
    result = client.get("/api/web/board", params=query)
    assert result.status_code == 200
    return result.json()


def names(data):
    return [person["username"] for person in data["people"]]


def last_day():
    now = time.time()
    return {"start": now - 86400, "end": now}


def seed_device(client, owner, name, last_seen, usage=(), power=()):
    """Write a device straight into the database. Every time is a number of seconds before now:
    usage is (start, end) pairs of one app, power is (when, reason) pairs, last_seen the last contact."""
    now, device = time.time(), str(uuid4())
    with client.app.state.database.connect() as db:
        user = db.execute("SELECT id FROM users WHERE username=?", (owner,)).fetchone()[0]
        db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?)",
                   (device, user, name, "windows", "0.1.0", now - 86400, now - last_seen))
        for start, end in usage:
            db.execute("INSERT INTO events(event_id,user_id,device_id,kind,app_name,process_name,started_at,ended_at,"
                       "duration_seconds) VALUES(?,?,?,?,?,?,?,?,?)",
                       (str(uuid4()), user, device, "app_usage", "Editor", "editor.exe", now - start, now - end, start - end))
        for when, reason in power:
            db.execute("INSERT INTO status_events(event_id,user_id,device_id,occurred_at,reason) VALUES(?,?,?,?,?)",
                       (str(uuid4()), user, device, now - when, reason))
    return device


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
    assert "data-board" in login(client).text
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
    data = board(client)
    assert data["apps"] == [["Example App", "example.exe"]]
    device = data["people"][0]["devices"][0]
    assert device["name"] == "Test PC" and len(device["runs"]) == 1
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
    add_member(client, "alice")
    switch_to(client, "alice")
    alice_key = upload_key(client)
    # Records stay private until their owner shares them, the admin's included.
    assert names(board(client)) == ["alice"]
    assert "Test PC" not in client.get("/api/web/board").text
    assert client.get("/api/web/people/admin", params=last_day()).status_code == 404
    assert client.get("/people/admin").status_code == 404
    assert client.get("/admin/users").status_code == 403
    assert send(client, alice_key, body).status_code == 409
    assert send(client, alice_key, batch()).status_code == 200


def test_sharing_is_opt_in_and_can_be_withdrawn(authorized):
    client, admin_key = authorized
    assert send(client, admin_key, batch()).status_code == 200
    add_member(client, "alice")
    add_member(client, "bob", shared=True)
    # The admin sees every account on the members page, but only shared records anywhere else.
    assert names(board(client)) == ["admin", "bob"]
    assert client.get("/api/web/people/alice", params=last_day()).status_code == 404
    assert client.get("/people/alice").status_code == 404
    assert client.get("/people/admin").status_code == 200
    members = client.get("/admin/users").text
    assert "alice" in members and "未公开" in members

    switch_to(client, "alice")
    assert send(client, upload_key(client), batch()).status_code == 200
    assert names(board(client)) == ["alice", "bob"]
    set_sharing(client, True)

    switch_to(client, "bob")
    data = board(client)
    assert names(data) == ["bob", "alice"]
    assert [person["self"] for person in data["people"]] == [True, False]
    other = client.get("/api/web/people/alice", params=last_day())
    assert other.status_code == 200
    assert other.json()["person"] == {"username": "alice", "self": False, "shared": True}
    assert client.get("/people/alice").status_code == 200

    switch_to(client, "alice")
    set_sharing(client, False)
    switch_to(client, "bob")
    assert names(board(client)) == ["bob"]
    assert client.get("/api/web/people/alice", params=last_day()).status_code == 404


def test_disabled_account_leaves_the_board(authorized):
    client, _ = authorized
    add_member(client, "bob", shared=True)
    assert names(board(client)) == ["admin", "bob"]
    with client.app.state.database.connect() as db:
        bob = db.execute("SELECT id FROM users WHERE username='bob'").fetchone()[0]
    toggled = client.post(f"/admin/users/{bob}/toggle", data={"csrf": hidden(client.get("/admin/users").text)},
                          follow_redirects=False)
    assert toggled.status_code == 303
    assert names(board(client)) == ["admin"]
    assert client.get("/api/web/people/bob", params=last_day()).status_code == 404


def test_board_reports_each_device_state(authorized):
    client, _ = authorized
    seed_device(client, "admin", "active", last_seen=5, usage=[(65, 5)])
    seed_device(client, "admin", "idle", last_seen=5, usage=[(900, 600)])
    seed_device(client, "admin", "offline", last_seen=3600, usage=[(3700, 3650)])
    seed_device(client, "admin", "asleep", last_seen=995, usage=[(1100, 1000)], power=[(990, "suspend")])
    seed_device(client, "admin", "off", last_seen=995, usage=[(1100, 1000)], power=[(990, "shutdown")])
    # Sleeping earlier but used again afterwards: the old suspend no longer counts.
    seed_device(client, "admin", "woke", last_seen=5, usage=[(300, 100)], power=[(2000, "suspend"), (1500, "resume")])
    seed_device(client, "admin", "unused", last_seen=5)
    states = {device["name"]: device["state"] for device in board(client)["people"][0]["devices"]}
    assert states == {"active": "active", "idle": "idle", "offline": "offline", "asleep": "asleep", "off": "off",
                      "woke": "idle", "unused": "idle"}
    active = next(device for device in board(client)["people"][0]["devices"] if device["name"] == "active")
    assert active["last"]["app"] == "Editor" and active["since"] == pytest.approx(time.time() - 65, abs=5)


def test_board_window_and_since(authorized):
    client, _ = authorized
    seed_device(client, "admin", "Desk", last_seen=5, usage=[(20 * 3600, 19 * 3600), (600, 300)])
    runs = board(client)["people"][0]["devices"][0]["runs"]
    assert len(runs) == 2
    recent = board(client, since=time.time() - 3600)
    assert recent["base"] == pytest.approx(time.time() - 3600, abs=5)
    runs = recent["people"][0]["devices"][0]["runs"]
    # Run times are whole seconds counted from the stated base.
    assert len(runs) == 1 and abs(runs[0][0] - 3000) <= 5 and abs(runs[0][1] - 3300) <= 5
    for bad in ("nan", "inf"):
        assert client.get("/api/web/board", params={"since": bad}).status_code == 422


def test_person_view_day_runs_and_longer_bins(authorized):
    client, _ = authorized
    device = seed_device(client, "admin", "Desk", last_seen=5, usage=[(3600, 3000), (2999.5, 2000)])
    other = seed_device(client, "admin", "Laptop", last_seen=5)
    day = client.get("/api/web/people/admin", params=last_day()).json()
    assert day["bin"] == 0 and "bins" not in day
    # Back-to-back segments of one app join into a single run.
    assert len(day["runs"][device]) == 1
    assert day["totals"][device] == pytest.approx(1600, abs=2)
    assert day["apps"] == [["Editor", "editor.exe"]]
    assert day["ranking"][0][0] == 0 and day["ranking"][0][1] == pytest.approx(1600, abs=2)
    assert day["streak"][1] - day["streak"][0] == pytest.approx(1600, abs=2)
    assert {item["name"] for item in day["devices"]} == {"Desk", "Laptop"}
    only = client.get("/api/web/people/admin", params={**last_day(), "device": other}).json()
    assert only["totals"] == {} and only["records"] == []

    now = time.time()
    week = client.get("/api/web/people/admin", params={"start": now - 7 * 86400, "end": now}).json()
    assert week["bin"] == 900 and "runs" not in week and sum(item[1] for item in week["bins"]) == pytest.approx(1600, abs=2)
    year = client.get("/api/web/people/admin", params={"start": now - 365 * 86400, "end": now}).json()
    assert year["bin"] == 1800


def test_person_view_rejects_bad_ranges_and_foreign_devices(authorized):
    client, _ = authorized
    now = time.time()
    assert client.get("/api/web/people/admin", params={"start": now, "end": now - 10}).status_code == 422
    assert client.get("/api/web/people/admin", params={"start": now - 400 * 86400, "end": now}).status_code == 422
    assert client.get("/api/web/people/admin", params={"start": "nan", "end": now}).status_code == 422
    assert client.get("/api/web/people/admin", params={"start": now - 60}).status_code == 422
    assert client.get("/api/web/people/admin", params={**last_day(), "device": str(uuid4())}).status_code == 404
    add_member(client, "bob", shared=True)
    foreign = seed_device(client, "bob", "Bob PC", last_seen=5)
    assert client.get("/api/web/people/admin", params={**last_day(), "device": foreign}).status_code == 404
    assert client.get("/api/web/people/bob", params={**last_day(), "device": foreign}).status_code == 200


def test_web_api_requires_a_session(client):
    assert client.get("/api/web/board").status_code == 401
    assert client.get("/api/web/people/admin", params=last_day()).status_code == 401
    assert client.get("/people/admin", follow_redirects=False).headers["location"] == "/login"


def test_longest_streak_bridges_short_pauses():
    runs = [["d", "a", "p", 0, 600], ["d", "b", "p", 630, 900], ["d", "a", "p", 2000, 2100]]
    assert board_model.longest_streak(runs) == [0, 900]
    assert board_model.longest_streak([["d", "a", "p", 5, 9]]) == [5, 9]
    assert board_model.longest_streak([]) is None


def test_app_names_are_interned_once():
    apps = board_model.Apps()
    assert [apps("A", "a.exe"), apps("B", "b.exe"), apps("A", "a.exe"), apps("A", "other.exe")] == [0, 1, 0, 2]
    assert apps.items == [["A", "a.exe"], ["B", "b.exe"], ["A", "other.exe"]]


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
    assert client.post("/settings/sharing", data={"shared": "on"}).status_code == 403
    assert client.post("/admin/users", data={"username": "mallory", "password": PASSWORD}).status_code == 403
    assert client.post("/logout").status_code == 403
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT shared FROM users").fetchone()[0] == 0


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
    assert "data-board" in login(client, password="brand-new-password-6789").text
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
    body["device"]["name"] = "<img src=x onerror=alert(1)>"
    send(client, key, body)
    for url in ("/", "/people/admin", "/settings"):
        html = client.get(url).text
        assert "<script>alert(1)</script>" not in html and "<img src=x" not in html, url
    # The board's seed data sits in the page as escaped JSON; the script inserts every name as text.
    assert "\\u003cscript\\u003e" in client.get("/").text
    assert board(client)["apps"][0][0] == "<script>alert(1)</script>"


def test_pages_obey_the_content_security_policy(authorized):
    client, _ = authorized
    # style-src and script-src are 'self': an inline style, handler or script would be dropped silently.
    for path in (APP / "templates").glob("*.html"):
        source = path.read_text(encoding="utf-8")
        assert " style=" not in source and "<style" not in source, path.name
        assert not re.search(r"\son[a-z]+=", source), path.name
    for url in ("/", "/settings", "/admin/users", "/people/admin"):
        for tag in re.findall(r"<script[^>]*>", client.get(url).text):
            assert "src=" in tag or 'type="application/json"' in tag, (url, tag)
    policy = client.get("/healthz").headers["Content-Security-Policy"]
    assert "script-src 'self'" in policy and "style-src 'self'" in policy
    script = "\n".join((APP / "static" / name).read_text(encoding="utf-8") for name in ("app.js", "theme.js"))
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe not in script, unsafe
    assert 'setAttribute("style"' not in script


def test_static_assets_are_served_and_revalidated(client):
    for name, marker in (("style.css", "--paper"), ("app.js", "use strict"), ("theme.js", "use strict"), ("mark.svg", "<svg")):
        response = client.get("/static/" + name)
        assert response.status_code == 200 and marker in response.text, name
        assert response.headers["Cache-Control"] == "no-cache", name
        # Unchanged files are answered with 304 instead of being sent again.
        again = client.get("/static/" + name, headers={"If-None-Match": response.headers["ETag"]})
        assert again.status_code == 304, name
    # Anything behind a login, and the login page itself, is never stored.
    assert client.get("/login").headers["Cache-Control"] == "no-store"
    assert client.get("/api/web/board").headers["Cache-Control"] == "no-store"


def test_theme_switch_is_available_on_login_records_and_error_pages(authorized):
    client, _ = authorized
    for url in ("/", "/settings", "/admin/users", "/people/admin", "/nowhere"):
        page = client.get(url, headers={"accept": "text/html"}).text
        assert page.count('data-theme-picker') == 1, url
        for mode in ("system", "light", "dark"):
            assert f'data-theme-option="{mode}"' in page, url
        # A blocking external script restores the theme before the first stylesheet can paint.
        assert page.index('/static/theme.js') < page.index('/static/style.css')
    client.cookies.clear()
    assert 'data-theme-picker' in client.get("/login").text


def test_browsers_get_error_pages_and_devices_keep_json(authorized):
    client, _ = authorized
    page = client.get("/nowhere", headers={"accept": "text/html"})
    assert page.status_code == 404 and "没有这个页面" in page.text and "text/html" in page.headers["content-type"]
    # API paths and non-browser clients keep the JSON body.
    api = client.get("/api/web/people/ghost", params=last_day(), headers={"accept": "text/html"})
    assert api.status_code == 404 and api.json()["detail"]
    assert client.get("/nowhere").json() == {"detail": "Not Found"}
    client.cookies.clear()
    gate = client.get("/settings", headers={"accept": "text/html"})
    assert gate.status_code == 401 and "去登录" in gate.text


def test_database_without_the_sharing_column_is_upgraded_privately(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                         "password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, "
                         "enabled INTEGER NOT NULL DEFAULT 1, upload_hash TEXT UNIQUE, created_at REAL NOT NULL);")
        db.execute("INSERT INTO users(username,password_hash,is_admin,created_at) VALUES('veteran','x',1,0)")
    database = Database(Settings(path, admin_username="admin", admin_password=PASSWORD))
    database.initialize()
    database.initialize()
    with database.connect() as db:
        assert db.execute("SELECT shared FROM users WHERE username='veteran'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
