import io
import json
import threading
import urllib.error
from dataclasses import replace

import pytest

from focus_agent import identity, network
from focus_agent.config import Config
from focus_agent.store import EventStore
from test_client import event


def test_computer_identity_is_stable_hashed_and_independent_of_client_version(monkeypatch):
    identity.machine_identity.cache_clear()
    monkeypatch.setattr(identity.sys, "platform", "win32")
    guid = "00000000-1111-2222-3333-444444444444"
    monkeypatch.setattr(identity, "_windows_machine_guid", lambda: guid)
    try:
        first = identity.machine_identity()
        identity.machine_identity.cache_clear()
        assert identity.machine_identity() == first
        assert len(first) == 64 and guid not in first
        monkeypatch.setattr(identity, "_windows_machine_guid", lambda: "another-computer")
        identity.machine_identity.cache_clear()
        assert identity.machine_identity() != first
    finally:
        identity.machine_identity.cache_clear()


def test_computer_identity_read_failure_is_reported_without_hostname_fallback(monkeypatch):
    identity.machine_identity.cache_clear()
    monkeypatch.setattr(identity.sys, "platform", "win32")
    def denied():
        raise PermissionError("denied")
    monkeypatch.setattr(identity, "_windows_machine_guid", denied)
    with pytest.raises(RuntimeError, match="无法读取本机电脑识别值"):
        identity.machine_identity()


@pytest.mark.parametrize("path", ["/api/v1/usage/batches", "/api/v1/agent/app-aliases"])
def test_device_requests_send_identity_and_report_name_conflict_without_fallback(monkeypatch, path):
    config = Config(host="public.example.com", fallback_host="192.168.1.10", api_key="x" * 43)
    calls = []
    monkeypatch.setattr(network, "machine_identity", lambda: "a" * 64)
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            detail = {"detail": {"code": "device_name_conflict", "message": "server text"}}
            raise urllib.error.HTTPError(request.full_url, 409, "Conflict", {},
                                         io.BytesIO(json.dumps(detail).encode()))
    monkeypatch.setattr(network.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(network.DeviceNameConflict, match="设备名称已被占用.*修改设备名称"):
        network.request_json(config, path, {})
    assert len(calls) == 1
    assert dict((key.lower(), value) for key, value in calls[0].header_items())["x-focusledger-machine-id"] == "a" * 64


def test_uploader_preserves_conflicting_queue_then_uploads_with_saved_new_name(tmp_path, monkeypatch):
    config = Config(host="127.0.0.1", api_key="x" * 43, account_id=1, device_name="重名电脑")
    store = EventStore(tmp_path / "events.db")
    records = [event()]
    store.add(config, records)
    conflict_seen = threading.Event()
    calls = []
    def request(candidate, path, body=None, method=None):
        if path == "/api/v1/agent/app-aliases":
            return {"ok": True, "device_id": candidate.device_id, "app_aliases": body["app_aliases"]}
        if path == "/api/v1/agent/app-colors":
            return {"ok": True, "device_id": candidate.device_id, "app_colors": body["app_colors"]}
        calls.append(body)
        if body["device"]["name"] == "重名电脑":
            conflict_seen.set()
            raise network.DeviceNameConflict("设备名称已被占用，请在设置中修改设备名称后重试")
        return {"acknowledged_ids": [record["id"] for record in body["events"]]}
    monkeypatch.setattr(network, "request_json", request)
    uploader = network.Uploader(store, config)
    uploader.start()
    try:
        assert conflict_seen.wait(3)
        ok, message = uploader.messages.get(timeout=3)
        assert not ok and "修改设备名称" in message
        assert store.counts(config.destination)[0] == 1
        uploader.configure(replace(config, device_name="新名称"))
        assert uploader.flush(3)
        assert calls[-1]["device"]["name"] == "新名称"
        assert calls[-1]["events"] == records
    finally:
        uploader.stop()
        uploader.thread.join(3)
