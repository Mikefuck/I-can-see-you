import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
import pytest

from server.app import main
from server.app.config import Settings
from server.app.main import create_app
from server.app.realtime import ChangeBroker
from server.app.security import token_hash
from test_server import PASSWORD, batch, hidden, login, set_sharing
from test_upload_integration import real_server


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "HEARTBEAT_SECONDS", .15)
    app = create_app(Settings(tmp_path / "realtime.db", admin_username="admin", admin_password=PASSWORD))
    app.state.database.initialize()
    key = "realtime-test-token-" + "x" * 32
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET upload_hash=?,shared=1", (token_hash(key),))
    with real_server(app) as port:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", follow_redirects=True, timeout=3) as client:
            yield app, client, key


def frames(response):
    event, data = "message", ""
    for line in response.iter_lines():
        if not line:
            if data:
                yield event, json.loads(data)
            event, data = "message", ""
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data += line[5:].strip()


def receive(stream, expected, *, area=None):
    for event, data in stream:
        if event == expected:
            if area is not None and area not in data.get("areas", []):
                continue
            return data
        assert event == "ping", f"Unexpected event {event}: {data}"
    raise AssertionError("Event stream closed before " + expected)


def upload(client, key, body):
    return client.post("/api/v1/usage/batches", json=body, headers={"Authorization": "Bearer " + key})


def foreground(body, name):
    stamp = datetime.now(timezone.utc).isoformat()
    body["foreground"] = {"observed_at": stamp, "since": stamp,
                          "app": {"app_name": name, "process_name": name.lower() + ".exe"}}


def test_live_notifications_follow_commits_and_reconnect_to_latest_snapshot(live_server):
    app, client, key = live_server
    body = batch()
    body["events"] = []
    foreground(body, "Browser")
    assert upload(client, key, body).status_code == 200
    with client.stream("GET", "/api/web/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-accel-buffering"] == "no"
        stream = frames(response)
        assert receive(stream, "ready")["now"] > 0
        foreground(body, "Editor")
        assert upload(client, key, body).status_code == 200
        assert receive(stream, "changed")["areas"] == ["live"]
        device = client.get("/api/web/live").json()["people"][0]["devices"][0]
        assert device["last"]["app"] == "Editor"
        body["events"] = batch(device=body["device"]["id"])["events"]
        assert upload(client, key, body).status_code == 200
        assert receive(stream, "changed")["areas"] == ["history", "live"]
    body["events"] = []
    foreground(body, "Terminal")
    assert upload(client, key, body).status_code == 200
    with client.stream("GET", "/api/web/events") as response:
        receive(frames(response), "ready")
        device = client.get("/api/web/live").json()["people"][0]["devices"][0]
        assert device["last"]["app"] == "Terminal"
    deadline = time.monotonic() + 2
    while app.state.changes.listeners and time.monotonic() < deadline:
        time.sleep(.01)
    assert not app.state.changes.listeners


def test_private_activity_is_not_broadcast_and_sharing_refreshes_visibility(live_server):
    app, client, key = live_server
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET shared=0")
    assert client.get("/api/web/events?username=admin").status_code == 401
    with client.stream("GET", "/api/web/events") as response:
        stream = frames(response)
        receive(stream, "ready")
        assert upload(client, key, batch()).status_code == 200
        assert next(stream)[0] == "ping"
        assert client.get("/api/web/live").json()["people"] == []
        with httpx.Client(base_url=str(client.base_url), follow_redirects=True, timeout=3) as actor:
            assert login(actor).status_code == 200
            set_sharing(actor, True)
            assert "access" in receive(stream, "changed", area="access")["areas"]
            set_sharing(actor, False)
            assert "access" in receive(stream, "changed", area="access")["areas"]
        assert client.get("/api/web/live").json()["people"] == []


def test_member_stream_resets_after_logout(live_server):
    _, client, _ = live_server
    assert login(client).status_code == 200
    with client.stream("GET", "/api/web/events?username=admin") as response:
        stream = frames(response)
        receive(stream, "ready")
        csrf = hidden(client.get("/settings").text)
        assert client.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
        assert receive(stream, "reset") == {}
        assert list(stream) == []


def test_rejected_transaction_emits_no_change_and_preserves_foreground(live_server):
    _, client, key = live_server
    body = batch()
    foreground(body, "Browser")
    assert upload(client, key, body).status_code == 200
    with client.stream("GET", "/api/web/events") as response:
        stream = frames(response)
        receive(stream, "ready")
        foreground(body, "Rejected")
        body["events"][0]["app_name"] = "Conflicting event ID"
        assert upload(client, key, body).status_code == 409
        assert next(stream)[0] == "ping"
        device = client.get("/api/web/live").json()["people"][0]["devices"][0]
        assert device["last"]["app"] == "Browser"


def test_program_metadata_notifies_open_person_page(live_server):
    _, client, key = live_server
    body = batch()
    assert upload(client, key, body).status_code == 200
    with client.stream("GET", "/api/web/events?username=admin") as response:
        stream = frames(response)
        receive(stream, "ready")
        for endpoint, field, mapping in [("app-aliases", "app_aliases", {"example.exe": "浏览器"}),
                                         ("app-colors", "app_colors", {"example.exe": "teal"})]:
            result = client.put("/api/v1/agent/" + endpoint, json={"device": body["device"], field: mapping},
                                headers={"Authorization": "Bearer " + key})
            assert result.status_code == 200
            assert receive(stream, "changed")["areas"] == ["history", "live", "metadata"]


def test_broker_bounds_pending_work_and_keeps_history_during_live_bursts():
    async def exercise():
        broker = ChangeBroker()
        broker.start()
        with broker.subscribe() as listener:
            await asyncio.to_thread(broker.publish, 1, history=True)
            await asyncio.wait_for(listener.wait(), 1)
            for _ in range(100):
                broker.publish(1)
                broker.publish(2)
            await asyncio.sleep(0)
            assert broker.areas_since(0, {1}) == ["history", "live"]
            assert broker.areas_since(0, {3}) == []
            assert len(broker.versions) == 3  # Per-owner revisions, not an unbounded event queue.
        assert not broker.listeners
        broker.close()
    asyncio.run(exercise())
