import json
import pytest

from test_server import authorized, client, add_member, batch, board, last_day, send, switch_to, upload_key


def sync(client, key, device, aliases):
    return client.put("/api/v1/agent/app-aliases", headers={"Authorization": "Bearer " + key},
                      json={"device": device, "app_aliases": aliases})


def test_alias_updates_history_ranking_and_live_name_without_mutating_events(authorized):
    client, key = authorized
    body = batch()
    body["events"][0]["process_name"] = "Example.EXE"
    assert send(client, key, body).json()["inserted"] == 1
    other = batch()
    other["device"]["name"] = "Other PC"
    assert send(client, key, other).json()["inserted"] == 1
    result = sync(client, key, body["device"], {r"C:\Apps\EXAMPLE.exe": "历史应用新名称"})
    assert result.status_code == 200 and result.json()["app_aliases"] == {"example.exe": "历史应用新名称"}
    data = board(client)
    assert ["历史应用新名称", "Example.EXE"] in data["apps"]
    assert ["Example App", "example.exe"] in data["apps"]  # Other devices are independent.
    details = client.get("/api/web/people/admin", params=last_day()).json()
    assert ["历史应用新名称", "Example.EXE"] in details["apps"]
    assert len(details["ranking"]) == 2
    device = next(d for d in data["people"][0]["devices"] if d["id"] == body["device"]["id"])
    assert device["last"]["app"] == "历史应用新名称"
    assert send(client, key, body).json()["duplicates"] == 1
    assert sync(client, key, body["device"], {"example": "再次改名"}).status_code == 200
    assert ["再次改名", "Example.EXE"] in board(client)["apps"]
    assert sync(client, key, body["device"], {}).status_code == 200
    assert ["Example App", "Example.EXE"] in board(client)["apps"]
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert {row[0] for row in db.execute("SELECT app_name FROM events")} == {"Example App"}


def test_alias_authentication_ownership_and_restart_persistence(authorized):
    client, key = authorized
    body = batch()
    assert sync(client, key, body["device"], {"example": "自己的翻译"}).status_code == 200
    assert client.put("/api/v1/agent/app-aliases", json={"device": body["device"], "app_aliases": {}}).status_code == 401
    add_member(client, "alice")
    switch_to(client, "alice")
    alice_key = upload_key(client)
    assert sync(client, alice_key, body["device"], {"example": "越权覆盖"}).status_code == 409
    database = client.app.state.database
    database.initialize()
    with database.connect() as db:
        aliases = json.loads(db.execute("SELECT aliases FROM device_app_aliases WHERE device_id=?", (body["device"]["id"],)).fetchone()[0])
    assert aliases == {"example": "自己的翻译"}


@pytest.mark.parametrize("aliases", [{" ": "应用"}, {"app": " "}, {"x"*201: "应用"}, {"app": "x"*201},
                                    {str(i): "应用" for i in range(501)}, {"App.exe": "a", "app.exe": "b"}])
def test_invalid_aliases_are_rejected_without_changing_saved_mapping(authorized, aliases):
    client, key = authorized
    device = batch()["device"]
    assert sync(client, key, device, {"app": "有效翻译"}).status_code == 200
    assert sync(client, key, device, aliases).status_code == 422
    with client.app.state.database.connect() as db:
        assert json.loads(db.execute("SELECT aliases FROM device_app_aliases").fetchone()[0]) == {"app": "有效翻译"}


def test_existing_database_gets_alias_table(authorized):
    client, key = authorized
    database = client.app.state.database
    with database.connect() as db:
        db.execute("DROP TABLE device_app_aliases")
    database.initialize()
    assert sync(client, key, batch()["device"], {"app": "新功能"}).status_code == 200
