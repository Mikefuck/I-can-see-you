import json
from copy import deepcopy
from uuid import uuid4

import pytest

from server.app.devices import MACHINE_HEADER
from test_server import authorized, client, add_member, batch, board, seed_device, switch_to, upload_key


def upload(client, key, body, machine="a" * 64):
    headers = {"Authorization": "Bearer " + key}
    if machine:
        headers[MACHINE_HEADER] = machine
    return client.post("/api/v1/usage/batches", headers=headers, json=body)


def aliases(client, key, body, machine="a" * 64):
    return client.put("/api/v1/agent/app-aliases",
                      headers={"Authorization": "Bearer " + key, MACHINE_HEADER: machine},
                      json={"device": body["device"], "app_aliases": {"example.exe": "编辑器"}})


def test_upgrade_and_reinstall_reuse_name_history_and_deduplication(authorized):
    client, key = authorized
    original = batch()
    assert upload(client, key, original).json()["inserted"] == 1
    upgraded = deepcopy(original)
    upgraded["device"].update(id=str(uuid4()), agent_version="0.3.0")
    assert upload(client, key, upgraded).json()["duplicates"] == 1
    assert aliases(client, key, upgraded).json()["device_id"] == upgraded["device"]["id"]
    upgraded["events"] = batch()["events"]
    assert upload(client, key, upgraded).json()["inserted"] == 1
    assert len(board(client)["people"][0]["devices"]) == 1
    with client.app.state.database.connect() as db:
        device = db.execute("SELECT * FROM devices").fetchone()
        assert device["id"] == original["device"]["id"] and device["agent_version"] == "0.3.0"
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM device_clients").fetchone()[0] == 2


@pytest.mark.parametrize("path", ["usage", "aliases"])
def test_other_computer_same_name_rejected_atomically_and_can_rename(authorized, path):
    client, key = authorized
    original, other = batch(), batch()
    assert upload(client, key, original).status_code == 200
    result = (upload if path == "usage" else aliases)(client, key, other, "b" * 64)
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "device_name_conflict"
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM device_clients").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM device_app_aliases").fetchone()[0] == 0
    other["device"]["name"] = "另一台电脑"
    assert upload(client, key, other, "b" * 64).status_code == 200
    # Renaming an already registered device to an occupied name also fails.
    other["device"]["name"] = original["device"]["name"]
    assert upload(client, key, other, "b" * 64).status_code == 409


def test_copied_client_id_does_not_bypass_computer_check(authorized):
    client, key = authorized
    body = batch()
    assert upload(client, key, body).status_code == 200
    assert upload(client, key, body, "b" * 64).status_code == 409
    other = deepcopy(body)
    other["device"]["name"] = "复制配置后的新名称"
    other["events"] = batch()["events"]
    assert upload(client, key, other, "b" * 64).status_code == 200
    assert upload(client, key, body, "b" * 64).status_code == 409
    assert upload(client, key, body).json()["duplicates"] == 1


def test_names_are_account_scoped_and_original_ids_stay_owned(authorized):
    client, key = authorized
    original = batch()
    assert upload(client, key, original).status_code == 200
    upgraded = batch()
    assert upload(client, key, upgraded).status_code == 200
    add_member(client, "alice")
    switch_to(client, "alice")
    other_key = upload_key(client)
    assert upload(client, other_key, batch(), "b" * 64).status_code == 200
    assert upload(client, other_key, upgraded).status_code == 409


def test_legacy_id_can_upgrade_but_unidentified_new_id_cannot_claim_name(authorized):
    client, key = authorized
    original = batch()
    assert upload(client, key, original, "").status_code == 200
    assert upload(client, key, original, "").json()["duplicates"] == 1
    assert upload(client, key, batch(), "").status_code == 409
    assert upload(client, key, batch()).status_code == 200
    assert upload(client, key, batch(), "b" * 64).status_code == 409


def test_renaming_same_computer_to_existing_name_merges_history(authorized):
    client, key = authorized
    first, second = batch(), batch()
    second["device"]["name"] = "临时名称"
    assert upload(client, key, first).status_code == 200
    assert upload(client, key, second).status_code == 200
    second["device"]["name"] = first["device"]["name"]
    assert upload(client, key, second).json()["duplicates"] == 1
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_legacy_duplicate_migration_preserves_records_aliases_and_old_queue_ids(authorized):
    client, key = authorized
    first = batch()
    assert upload(client, key, first, "").status_code == 200
    database = client.app.state.database
    with database.connect() as db:
        db.execute("DROP INDEX devices_owner_name")
    second_id = seed_device(client, "admin", "  Test PC  ", 5, usage=((60, 30),), power=((15, "suspend"),))
    with database.connect() as db:
        db.execute("INSERT INTO device_app_aliases VALUES(?,?)", (second_id, '{"editor.exe":"旧翻译"}'))
        # Preserve a rare UUID collision with a different payload as well as normal records.
        row = db.execute("SELECT * FROM events WHERE device_id=?", (first["device"]["id"],)).fetchone()
        db.execute("INSERT INTO events(event_id,user_id,device_id,kind,app_name,process_name,started_at,ended_at,duration_seconds) "
                   "VALUES(?,?,?,?,?,?,?,?,?)", (row["event_id"], 1, second_id, row["kind"], "旧版本应用",
                   row["process_name"], row["started_at"], row["ended_at"], row["duration_seconds"]))
    database.initialize()
    database.initialize()
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
        assert db.execute("SELECT name FROM devices").fetchone()[0] == "Test PC"
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM status_events").fetchone()[0] == 1
        assert json.loads(db.execute("SELECT aliases FROM device_app_aliases").fetchone()[0]) == {"editor.exe": "旧翻译"}
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    queued = deepcopy(first)
    queued["device"]["id"] = second_id
    queued["events"][0]["app_name"] = "旧版本应用"
    assert upload(client, key, queued, "").json()["duplicates"] == 1
    assert upload(client, key, first, "").json()["duplicates"] == 1
    assert upload(client, key, first).json()["duplicates"] == 1
    assert upload(client, key, queued, "b" * 64).status_code == 409
    queued["device"]["name"] = "另一台旧电脑"
    queued["events"] = batch()["events"]
    assert upload(client, key, queued, "b" * 64).status_code == 200
    assert upload(client, key, first).json()["duplicates"] == 1
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_device_names_rejected(authorized, name):
    client, key = authorized
    body = batch()
    body["device"]["name"] = name
    assert upload(client, key, body).status_code == 422


def test_whitespace_normalization_and_invalid_machine_header(authorized):
    client, key = authorized
    body = batch()
    body["device"]["name"] = "  Test PC  "
    assert upload(client, key, body).status_code == 200
    assert upload(client, key, batch(), "b" * 64).status_code == 409
    assert upload(client, key, batch(), "not-a-hash").status_code == 422


def test_migration_deduplicates_identical_events_and_preserves_cross_kind_collisions(authorized):
    client, key = authorized
    original = batch()
    assert upload(client, key, original, "").status_code == 200
    database = client.app.state.database
    with database.connect() as db:
        db.execute("DROP INDEX devices_owner_name")
    old_id = seed_device(client, "admin", "Test PC", 5, usage=((120, 90),))
    with database.connect() as db:
        old_event = db.execute("SELECT * FROM events WHERE device_id=?", (old_id,)).fetchone()
        first_event = db.execute("SELECT * FROM events WHERE device_id=?", (original["device"]["id"],)).fetchone()
        db.execute("INSERT INTO events(event_id,user_id,device_id,kind,app_name,process_name,started_at,ended_at,duration_seconds) "
                   "VALUES(?,?,?,?,?,?,?,?,?)", (first_event["event_id"], 1, old_id, first_event["kind"], first_event["app_name"],
                   first_event["process_name"], first_event["started_at"], first_event["ended_at"], first_event["duration_seconds"]))
        db.execute("INSERT INTO status_events(event_id,user_id,device_id,occurred_at,reason) VALUES(?,?,?,?,?)",
                   (old_event["event_id"], 1, original["device"]["id"], first_event["ended_at"], "startup"))
    database.initialize()
    database.initialize()
    assert upload(client, key, original, "").json()["duplicates"] == 1
    status = deepcopy(original)
    status["events"] = [{"id": old_event["event_id"], "kind": "device_status", "reason": "startup",
                         "occurred_at": original["events"][0]["ended_at"]}]
    assert upload(client, key, status, "").json()["duplicates"] == 1
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM status_events").fetchone()[0] == 1
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
