import json
from pathlib import Path
from uuid import uuid4

import pytest

from server.app.app_colors import PALETTE, default_color
from test_server import authorized, client, add_member, batch, board, last_day, send, switch_to, upload_key


def sync(client, key, device, colors):
    return client.put("/api/v1/agent/app-colors", headers={"Authorization": "Bearer " + key},
                      json={"device": device, "app_colors": colors})


def test_colors_update_history_live_ranking_and_reset_without_changing_events(authorized):
    client, key = authorized
    body = batch()
    body["events"][0]["process_name"] = "Example.EXE"
    assert send(client, key, body).json()["inserted"] == 1
    assert "app_colors" in client.get("/api/v1/agent/check", headers={"Authorization": "Bearer " + key}).json()["features"]
    automatic = default_color("example.exe")
    custom = next(color[0] for color in PALETTE if color[0] != automatic)
    assert board(client)["app_colors"] == [automatic]
    assert sync(client, key, body["device"], {r"C:\Apps\EXAMPLE.exe": custom}).json()["app_colors"] == {"example.exe": custom}
    data = board(client)
    assert data["app_colors"] == [custom]
    assert data["people"][0]["devices"][0]["last"]["color"] == custom
    details = client.get("/api/web/people/admin", params=last_day()).json()
    assert details["app_colors"][details["ranking"][0][0]] == custom
    assert details["app_colors"][details["records"][0][3]] == custom
    assert send(client, key, body).json()["duplicates"] == 1
    assert sync(client, key, body["device"], {}).status_code == 200
    assert board(client)["app_colors"] == [automatic]
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert db.execute("SELECT app_name FROM events").fetchone()[0] == "Example App"


def test_colors_are_device_scoped_and_survive_restart(authorized):
    client, key = authorized
    first, second = batch(), batch()
    second["device"]["name"] = "Other PC"
    for body, color in ((first, "teal"), (second, "rose")):
        assert send(client, key, body).status_code == 200
        assert sync(client, key, body["device"], {"example": color}).status_code == 200
    client.app.state.database.initialize()
    data = board(client)
    for device in data["people"][0]["devices"]:
        expected = "teal" if device["id"] == first["device"]["id"] else "rose"
        assert device["last"]["color"] == expected
        assert all(data["app_colors"][run[2]] == expected for run in device["runs"])
    details = client.get("/api/web/people/admin", params=last_day()).json()
    assert set(details["app_colors"]) == {"teal", "rose"}
    assert len(details["ranking"]) == 2  # Same program on devices with different overrides keeps both colours.


def test_color_sync_requires_ownership_and_authentication(authorized):
    client, key = authorized
    device = batch()["device"]
    assert sync(client, key, device, {"example": "teal"}).status_code == 200
    assert client.put("/api/v1/agent/app-colors", json={"device": device, "app_colors": {}}).status_code == 401
    add_member(client, "alice")
    switch_to(client, "alice")
    assert sync(client, upload_key(client), device, {"example": "rose"}).status_code == 409
    with client.app.state.database.connect() as db:
        assert json.loads(db.execute("SELECT colors FROM device_app_colors").fetchone()[0]) == {"example": "teal"}


@pytest.mark.parametrize("colors", [
    {" ": "teal"}, {"app": "#ff0000"}, {"app": "url(https://invalid.test/)"}, {"app": "neon"},
    {"x" * 201: "teal"}, {"APP.exe": "rose", "app.exe": "teal"},
    {str(i): "teal" for i in range(501)}, {"app": None},
])
def test_invalid_colors_leave_saved_mapping_intact(authorized, colors):
    client, key = authorized
    device = batch()["device"]
    assert sync(client, key, device, {"app": "teal"}).status_code == 200
    assert sync(client, key, device, colors).status_code == 422
    with client.app.state.database.connect() as db:
        assert json.loads(db.execute("SELECT colors FROM device_app_colors").fetchone()[0]) == {"app": "teal"}


def test_old_database_migration_and_device_merge_keep_colors(authorized):
    client, key = authorized
    database = client.app.state.database
    with database.connect() as db:
        db.execute("DROP TABLE device_app_colors")
    database.initialize()
    body = batch()
    assert sync(client, key, body["device"], {"example": "teal"}).status_code == 200
    source = str(uuid4())
    with database.connect() as db:
        db.execute("DROP INDEX devices_owner_name")
        original = db.execute("SELECT * FROM devices").fetchone()
        db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?)", (source, 1, original["name"], "windows", "old",
                   original["first_seen"] + 1, original["last_seen"] + 1))
        db.execute("INSERT INTO device_app_colors VALUES(?,?)", (source, json.dumps({"other": "rose"})))
    database.initialize()
    with database.connect() as db:
        assert json.loads(db.execute("SELECT colors FROM device_app_colors").fetchone()[0]) == {"example": "teal", "other": "rose"}
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_client_server_palette_and_css_match():
    from focus_agent.app_colors import PALETTE as client_palette, default_color as client_default
    assert PALETTE == client_palette
    css = (Path(__file__).parents[1] / "app" / "static" / "style.css").read_text(encoding="utf-8")
    for color_id, _, light, dark in PALETTE:
        assert f'[data-color="{color_id}"] {{ --app-light: {light}; --app-dark: {dark}; }}' in css
    for process in ("Chrome.EXE", "chrome", r"C:\应用\Chrome.exe", "程序.exe", "Weixin.exe"):
        assert default_color(process) == client_default(process)
    assert default_color("Chrome.EXE") == default_color("chrome") == default_color(r"C:\应用\Chrome.exe")
