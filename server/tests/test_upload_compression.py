import gzip
import json
from uuid import uuid4

import pytest

from test_server import authorized, batch, client, send


def compressed_post(client, key, body):
    return client.post("/api/v1/usage/batches", content=gzip.compress(json.dumps(body).encode()),
                       headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                "Content-Encoding": "gzip"})


def test_full_compressed_batch_keeps_usage_status_foreground_and_deduplication(authorized):
    client, key = authorized
    body = batch()
    prototype = body["events"][0]
    body["events"] = [{**prototype, "id": str(uuid4())} for _ in range(499)]
    body["events"].append({"id": str(uuid4()), "kind": "device_status", "reason": "periodic",
                           "occurred_at": prototype["ended_at"], "battery_percent": 73, "ac_online": False})
    body["foreground"] = {"observed_at": prototype["ended_at"], "since": prototype["started_at"],
                          "app": {"app_name": "编辑器", "process_name": "editor.exe"}}
    assert send(client, key, {**body, "events": []}).json()["upload_encodings"] == ["gzip"]
    result = compressed_post(client, key, body)
    assert result.status_code == 200, result.text
    assert result.json()["inserted"] == 500
    assert result.json()["acknowledged_ids"] == [item["id"] for item in body["events"]]
    assert compressed_post(client, key, body).json()["duplicates"] == 500
    assert send(client, key, body).json()["duplicates"] == 500
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*),SUM(duration_seconds) FROM events").fetchone()[:] == (499, 499 * 30)
        assert db.execute("SELECT battery_percent FROM status_events").fetchone()[0] == 73
        assert db.execute("SELECT app_name,process_name FROM device_foreground").fetchone()[:] == ("编辑器", "editor.exe")


@pytest.mark.parametrize("mapping,value", [("app-aliases", "编辑器"), ("app-colors", "teal")])
def test_compressed_settings_sync_and_empty_reset(authorized, mapping, value):
    client, key = authorized
    field = mapping.replace("-", "_")
    device = batch()["device"]
    for values in ({f"app{index}.exe": value for index in range(100)}, {}):
        body = {"device": device, field: values}
        result = client.put("/api/v1/agent/" + mapping,
                            content=gzip.compress(json.dumps(body, ensure_ascii=False).encode("utf-8")),
                            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                     "Content-Encoding": "gzip"})
        assert result.status_code == 200, result.text
        assert result.json()[field] == values


def test_validation_still_identifies_the_original_event_index(authorized):
    client, key = authorized
    body = batch()
    body["events"].append({**body["events"][0], "id": str(uuid4()), "duration_seconds": -1})
    result = compressed_post(client, key, body)
    assert result.status_code == 422
    assert any(error["loc"][:3] == ["body", "events", 1] for error in result.json()["detail"])
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


@pytest.mark.parametrize("content", [b"", b"not gzip", gzip.compress(b"{}")[:-1],
                                     gzip.compress(b"{}") + b"trailing",
                                     gzip.compress(b"{}") + gzip.compress(b"{}")])
def test_invalid_or_concatenated_gzip_is_rejected(client, content):
    result = client.post("/api/v1/usage/batches", content=content,
                        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
    assert result.status_code == 400


def test_corrupt_gzip_checksum_is_rejected(client):
    content = bytearray(gzip.compress(b"{}"))
    content[-8] ^= 1
    assert client.post("/api/v1/usage/batches", content=bytes(content),
                       headers={"Content-Encoding": "gzip"}).status_code == 400


@pytest.mark.parametrize("compressed", [True, False])
def test_request_limit_applies_to_decoded_and_wire_bytes(client, compressed):
    data = b"x" * (2 * 1024 * 1024 + 1)
    content = gzip.compress(data) if compressed else data
    assert client.post("/api/v1/usage/batches", content=content,
                       headers={"Content-Encoding": "gzip"}).status_code == 413


def test_chunked_gzip_and_authentication_are_preserved(authorized):
    client, key = authorized
    body = batch()
    content = gzip.compress(json.dumps(body).encode())
    result = client.post("/api/v1/usage/batches", content=(content[index:index + 17] for index in range(0, len(content), 17)),
                        headers={"Content-Encoding": "gzip", "Authorization": "Bearer " + key,
                                 "Content-Type": "application/json"})
    assert result.status_code == 200 and result.json()["inserted"] == 1
    assert client.post("/api/v1/usage/batches", content=content,
                       headers={"Content-Encoding": "gzip", "Content-Type": "application/json"}).status_code == 401


@pytest.mark.parametrize("encoding", ["br", "gzip, gzip"])
def test_unrecognized_encoding_is_explicitly_rejected(client, encoding):
    assert client.post("/api/v1/usage/batches", content=b"{}",
                       headers={"Content-Encoding": encoding}).status_code == 415
