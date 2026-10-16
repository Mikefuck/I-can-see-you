import time
from datetime import datetime, timezone

import pytest

from test_server import authorized, batch, client, send, set_sharing


def music(title="夜曲", state="playing", observed=None):
    return {"observed_at": datetime.fromtimestamp(observed or time.time(), timezone.utc).isoformat(),
            "track": {"title": title, "artist": "歌手", "album": "专辑", "app_name": "播放器",
                      "process_name": "music.exe", "state": state} if title is not None else None}


def device(client):
    return client.get("/api/web/live").json()["people"][0]["devices"][0]


def test_music_switch_pause_clear_and_background_playback_do_not_add_usage(authorized):
    client, key = authorized
    body = batch()
    body["events"] = []
    body["music"] = music()
    assert send(client, key, body).status_code == 200
    assert device(client)["state"] == "idle"
    assert device(client)["music"]["title"] == "夜曲"
    assert "music" in client.get("/api/v1/agent/check", headers={"Authorization": "Bearer " + key}).json()["features"]
    for snapshot in (music("晴天"), music("晴天", "paused"), music(None)):
        body["music"] = snapshot
        assert send(client, key, body).status_code == 200
        current = device(client)["music"]
        assert (current is None) if snapshot["track"] is None else all(current[k] == v for k, v in snapshot["track"].items())
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM device_music").fetchone()[0] == 1


def test_music_out_of_order_stale_clears_and_old_client_compatibility(authorized):
    client, key = authorized
    body = batch()
    body.update(events=[], music=music())
    assert send(client, key, body).status_code == 200
    body["music"] = music("旧歌曲", observed=time.time() - 20)
    assert send(client, key, body).status_code == 200
    assert device(client)["music"]["title"] == "夜曲"
    body["music"] = music(None)
    assert send(client, key, body).status_code == 200
    body["music"] = music("旧歌曲", observed=time.time() - 10)
    assert send(client, key, body).status_code == 200
    assert device(client)["music"] is None
    with client.app.state.database.connect() as db:
        db.execute("UPDATE device_music SET track=?,observed_at=?", ('{"title":"stale"}', time.time() - 400))
    assert device(client)["music"] is None
    body.pop("music")
    assert send(client, key, body).status_code == 200
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM device_music").fetchone()[0] == 0


@pytest.mark.parametrize("invalid", [
    {"observed_at": "2026-10-16T00:00:00", "track": None},
    lambda: music(observed=time.time() + 600),
    {**music(), "track": {**music()["track"], "title": "   "}},
    {**music(), "track": {**music()["track"], "title": "x" * 301}},
    {**music(), "track": {**music()["track"], "state": "stopped"}},
    {**music(), "recording": "forbidden"},
])
def test_invalid_music_rolls_back_entire_batch(authorized, invalid):
    client, key = authorized
    body = batch()
    body["music"] = invalid() if callable(invalid) else invalid
    assert send(client, key, body).status_code == 422
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM device_music").fetchone()[0] == 0


def test_music_visibility_aliases_retention_and_device_deletion(authorized):
    client, key = authorized
    body = batch()
    body.update(events=[], music=music())
    assert send(client, key, body).status_code == 200
    assert client.put("/api/v1/agent/app-aliases", headers={"Authorization": "Bearer " + key},
                      json={"device": body["device"], "app_aliases": {"music.exe": "音乐"}}).status_code == 200
    for path in ("/api/web/live", "/api/web/board", "/api/web/people/admin?start=" + str(time.time()-100) + "&end=" + str(time.time())):
        result = client.get(path).json()
        devices = result["devices"] if "devices" in result else result["people"][0]["devices"]
        assert devices[0]["music"]["app_name"] == "音乐"
    cookies = dict(client.cookies)
    client.cookies.clear()
    assert client.get("/api/web/live").json()["people"] == []
    assert "夜曲" not in client.get("/").text
    client.cookies.update(cookies)
    set_sharing(client, True)
    client.cookies.clear()
    assert device(client)["music"]["title"] == "夜曲"
    with client.app.state.database.connect() as db:
        db.execute("UPDATE devices SET last_seen=?", (time.time()-400,))
    assert device(client)["music"] is None
    body["music"] = music(observed=time.time() - 2 * 86400)
    # Clear the newer snapshot first to test retention of an older persisted observation.
    with client.app.state.database.connect() as db:
        db.execute("DELETE FROM device_music")
    assert send(client, key, body).status_code == 200
    client.app.state.database.set_retention_days(1)
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM device_music").fetchone()[0] == 0
    body["music"] = music()
    assert send(client, key, body).status_code == 200
    with client.app.state.database.connect() as db:
        db.execute("DELETE FROM devices")
        assert db.execute("SELECT COUNT(*) FROM device_music").fetchone()[0] == 0


def test_windows_uploader_music_round_trip_over_real_http(tmp_path):
    from focus_agent.config import Config
    from focus_agent.network import Uploader, request_json
    from focus_agent.store import EventStore
    from server.app.config import Settings
    from server.app.main import create_app
    from server.app.security import token_hash
    from test_upload_integration import real_server
    from test_server import PASSWORD
    app = create_app(Settings(tmp_path / "music-server.db", admin_username="admin", admin_password=PASSWORD))
    app.state.database.initialize()
    key = "music-test-token-" + "x" * 32
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET shared=1,upload_hash=?", (token_hash(key),))
    with real_server(app) as port:
        config = Config(host="127.0.0.1", port=port, api_key=key, account_id=1)
        uploader = Uploader(EventStore(tmp_path / "client.db"), config)
        uploader.observe_music(music()["track"], time.time())
        uploader.start()
        try:
            assert uploader.messages.get(timeout=5)[0]
            current = request_json(config, "/api/web/live")["people"][0]["devices"][0]
            assert current["state"] == "idle" and current["music"]["title"] == "夜曲"
            uploader.observe_music(music(state="paused")["track"], time.time())
            assert uploader.messages.get(timeout=5)[0]
            assert request_json(config, "/api/web/live")["people"][0]["devices"][0]["music"]["state"] == "paused"
            uploader.observe_music(None, time.time())
            assert uploader.messages.get(timeout=5)[0]
            assert request_json(config, "/api/web/live")["people"][0]["devices"][0]["music"] is None
        finally:
            uploader.stop()
            uploader.thread.join(3)
