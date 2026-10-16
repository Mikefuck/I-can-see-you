import gzip
import io
import json
import time
import urllib.error
from dataclasses import replace

import pytest

from focus_agent import network
from focus_agent.store import EventStore
from focus_agent.tracker import Application
from test_client import config, event


def transport(monkeypatch, action):
    class Opener:
        def open(self, request, timeout):
            headers = {key.lower(): value for key, value in request.header_items()}
            data = gzip.decompress(request.data) if headers.get("content-encoding") == "gzip" else request.data
            result = action(request, headers, json.loads(data))
            return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr(network.urllib.request, "build_opener", lambda *args: Opener())


def payload(store, current, count=1):
    now = time.time()
    store.add(current, [event(now - 30 * offset) for offset in range(count, 0, -1)])
    return store.batch(current.destination)


def test_compact_json_and_gzip_preserve_every_event_value(tmp_path):
    current = config(device_name="工作电脑", app_aliases={"editor.exe": "编程"})
    body = payload(EventStore(tmp_path / "queue.db"), current, 500)
    body["events"][0]["app_name"] = '编辑器 : "项目" 😀'
    original = json.dumps(body, ensure_ascii=False).encode("utf-8")
    compact, compressed = network.encode_json(body)
    assert not compressed and json.loads(compact) == body and len(compact) < len(original)
    encoded, compressed = network.encode_json(body, compress=True)
    assert compressed and json.loads(gzip.decompress(encoded)) == body
    assert len(encoded) < len(original) * .25


@pytest.mark.parametrize("advertise", [True, False])
def test_compression_is_negotiated_without_an_extra_request(tmp_path, monkeypatch, advertise):
    current = config()
    store = EventStore(tmp_path / "queue.db")
    body = payload(store, current)
    uploader, calls = network.Uploader(store, current), []

    def action(request, headers, decoded):
        calls.append(headers.get("content-encoding"))
        assert decoded == body
        return {"acknowledged_ids": [item["id"] for item in decoded["events"]],
                **({"upload_encodings": ["gzip"]} if advertise else {})}

    transport(monkeypatch, action)
    for _ in range(2):
        uploader._request(current, "/api/v1/usage/batches", body)
    assert calls == [None, "gzip" if advertise else None]
    # A successful capability from one server must not enable gzip on a different server.
    other = replace(current, host="other.example.com")
    uploader._request(other, "/api/v1/usage/batches", body)
    assert calls[-1] is None


@pytest.mark.parametrize("status", [400, 415])
def test_compression_rejection_retries_same_ids_once_and_remembers_fallback(tmp_path, monkeypatch, status):
    current = config()
    body = payload(EventStore(tmp_path / "queue.db"), current)
    uploader, calls = network.Uploader(EventStore(tmp_path / "other.db"), current), []

    def action(request, headers, decoded):
        calls.append(headers.get("content-encoding"))
        assert decoded == body
        if calls[-1] == "gzip":
            raise urllib.error.HTTPError(request.full_url, status, "encoding rejected", {}, io.BytesIO(b"{}"))
        # Proxies may reject gzip even though the backend continues to advertise it.
        return {"acknowledged_ids": [item["id"] for item in decoded["events"]], "upload_encodings": ["gzip"]}

    transport(monkeypatch, action)
    for _ in range(3):
        result = uploader._request(current, "/api/v1/usage/batches", body)
        assert result["acknowledged_ids"] == [item["id"] for item in body["events"]]
    assert calls == [None, "gzip", None, None]


def test_small_heartbeat_stays_plain_even_when_gzip_is_supported(monkeypatch):
    body, sent = {"events": []}, []

    def action(request, headers, decoded):
        assert decoded == body
        sent.append(headers.get("content-encoding"))
        return {"acknowledged_ids": []}

    transport(monkeypatch, action)
    network.request_json(config(), "/api/v1/usage/batches", body, compress=True)
    assert sent == [None]


def test_gzip_rejected_by_fallback_does_not_revisit_an_offline_primary(tmp_path, monkeypatch):
    current = config(fallback_host="fallback.example.com")
    body = payload(EventStore(tmp_path / "queue.db"), current)
    uploader, calls = network.Uploader(EventStore(tmp_path / "other.db"), current), []
    uploader.compression_state = ((current.base_urls, current.api_key), True)

    def action(request, headers, decoded):
        calls.append((request.full_url, headers.get("content-encoding")))
        if request.full_url.startswith(current.base_url + "/"):
            raise urllib.error.URLError("offline")
        if headers.get("content-encoding") == "gzip":
            raise urllib.error.HTTPError(request.full_url, 415, "encoding rejected", {}, io.BytesIO(b"{}"))
        return {"acknowledged_ids": [item["id"] for item in decoded["events"]]}

    transport(monkeypatch, action)
    uploader._request(current, "/api/v1/usage/batches", body)
    assert calls == [(current.base_urls[0] + "/api/v1/usage/batches", "gzip"),
                     (current.base_urls[1] + "/api/v1/usage/batches", "gzip"),
                     (current.base_urls[1] + "/api/v1/usage/batches", None)]


def test_backlog_uses_full_server_limit_without_dropping_the_remainder(tmp_path):
    store, current = EventStore(tmp_path / "queue.db"), config()
    first = payload(store, current, 501)
    assert len(first["events"]) == 500
    first_ids = {item["id"] for item in first["events"]}
    store.acknowledge(current.destination, first_ids)
    second = store.batch(current.destination)
    assert len(second["events"]) == 1 and second["events"][0]["id"] not in first_ids
    assert store.counts(current.destination) == (1, 1)
    store.acknowledge(current.destination, [second["events"][0]["id"]])
    assert store.counts(current.destination) == (0, 0)


def test_unrelated_settings_do_not_resend_confirmed_mappings(tmp_path, monkeypatch):
    current = config(app_aliases={"editor.exe": "编辑器"}, app_colors={"editor.exe": "teal"})
    uploader, calls = network.Uploader(EventStore(tmp_path / "queue.db"), current), []

    def request(candidate, path, body, method):
        calls.append((path, body))
        return {"ok": True, "device_id": candidate.device_id,
                **{key: value for key, value in body.items() if key != "device"}}

    monkeypatch.setattr(network, "request_json", request)

    def sync(candidate):
        uploader.sync_aliases(candidate)
        uploader.sync_colors(candidate)

    sync(current)
    updated = replace(current, upload_seconds=60, theme="dark")
    uploader.configure(updated)
    sync(updated)
    assert len(calls) == 2
    updated = replace(updated, app_aliases={})
    uploader.configure(updated)
    sync(updated)
    assert len(calls) == 3 and calls[-1][1]["app_aliases"] == {}
    updated = replace(updated, device_name="新名称")
    uploader.configure(updated)
    sync(updated)
    assert len(calls) == 5  # Device metadata changes still synchronize both mappings.
    updated = replace(updated, api_key="y" * 43)
    uploader.configure(updated)
    sync(updated)
    assert len(calls) == 7


def test_app_changes_respect_failure_backoff_and_manual_upload_can_retry(tmp_path, monkeypatch):
    current = config(upload_on_app_change=True)
    store = EventStore(tmp_path / "queue.db")
    payload(store, current)
    uploader, batches, offline = network.Uploader(store, current), [], [True]

    def request(candidate, path, body=None, method=None):
        if path.endswith("/check"):
            return {"features": ["foreground"]}
        if path != "/api/v1/usage/batches":
            return {"ok": True, "device_id": candidate.device_id,
                    **{key: value for key, value in body.items() if key != "device"}}
        batches.append(body)
        if offline[0]:
            raise RuntimeError("offline")
        return {"acknowledged_ids": [item["id"] for item in body["events"]]}

    monkeypatch.setattr(network, "request_json", request)
    uploader.observe_foreground(Application("First", "first.exe"), time.time())
    uploader.start()
    try:
        assert not uploader.messages.get(timeout=3)[0]
        for index in range(20):
            uploader.observe_foreground(Application(str(index), f"app{index}.exe"), time.time())
        time.sleep(.15)
        assert len(batches) == 1 and store.counts(current.destination) == (1, 1)
        offline[0] = False
        uploader.trigger()
        assert uploader.messages.get(timeout=3)[0]
        assert batches[-1]["foreground"]["app"]["process_name"] == "app19.exe"
        assert store.counts(current.destination) == (0, 0)
    finally:
        uploader.stop()
        uploader.thread.join(3)


def test_healthy_app_changes_are_immediate_even_with_maximum_upload_interval(tmp_path, monkeypatch):
    current = config(upload_on_app_change=True, upload_seconds=300)
    uploader = network.Uploader(EventStore(tmp_path / "queue.db"), current)

    def request(candidate, path, body=None, method=None):
        if path.endswith("/check"):
            return {"features": ["foreground"]}
        if path == "/api/v1/usage/batches":
            return {"acknowledged_ids": []}
        return {"ok": True, "device_id": candidate.device_id,
                **{key: value for key, value in body.items() if key != "device"}}

    monkeypatch.setattr(network, "request_json", request)
    uploader.observe_foreground(Application("First", "first.exe"), time.time())
    uploader.start()
    try:
        assert uploader.messages.get(timeout=3)[0]
        uploader.observe_foreground(Application("Next", "next.exe"), time.time())
        assert uploader.messages.get(timeout=3)[0]
    finally:
        uploader.stop()
        uploader.thread.join(3)
