import io
import json
import sys
import time
import urllib.error
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from focus_agent.config import Config, load_config, save_config
from focus_agent.store import PENDING, REJECTED, SENT, EventStore
from focus_agent.tracker import Application, SessionTracker


APP = Application("Example", "example.exe")


def config(**kwargs):
    return Config(host="127.0.0.1", api_key="x"*43, account_id=1, **kwargs)


def event(end=None):
    end = end or time.time()
    return {"id": str(uuid4()), "kind": "app_usage", "app_name": APP.app_name, "process_name": APP.process_name,
            "started_at": datetime.fromtimestamp(end-30, timezone.utc).isoformat(),
            "ended_at": datetime.fromtimestamp(end, timezone.utc).isoformat(), "duration_seconds": 30}


def status_event(when=None, reason="suspend"):
    when = when or time.time()
    return {"id": str(uuid4()), "kind": "device_status",
            "occurred_at": datetime.fromtimestamp(when, timezone.utc).isoformat(),
            "reason": reason, "battery_percent": 73, "charging": False,
            "ac_online": False, "battery_life_seconds": 3600}


def test_tracker_segments_and_app_changes():
    tracker = SessionTracker()
    events = []
    for i in range(31):
        events += tracker.observe(APP, 1000+i, i)
    assert len(events) == 1
    assert events[0]["duration_seconds"] == 30
    other = Application("Other", "other.exe")
    assert tracker.observe(other, 1031, 31)[0]["duration_seconds"] == 1


@pytest.mark.parametrize("wall,monotonic", [(10000, 1000), (900, 4), (1100, 4)])
def test_sleep_and_clock_changes_do_not_inflate_usage(wall, monotonic):
    tracker = SessionTracker()
    tracker.observe(APP, 1000, 0)
    tracker.observe(APP, 1001, 1)
    result = tracker.observe(APP, wall, monotonic)
    assert result[0]["duration_seconds"] == 1


def test_idle_and_stop_flush_without_counting_gap():
    tracker = SessionTracker()
    tracker.observe(APP, 1000, 0)
    tracker.observe(APP, 1001, 1)
    assert tracker.observe(None, 1002, 2)[0]["duration_seconds"] == 1
    assert tracker.observe(None, 1030, 30) == []
    tracker.observe(APP, 1031, 31)
    tracker.observe(APP, 1032, 32)
    assert tracker.stop(1033, 33)[0]["duration_seconds"] == 1
    assert tracker.stop(1034, 34) == []


def test_durable_queue_acknowledgement_and_isolation(tmp_path):
    path = tmp_path / "queue.db"
    store, first = EventStore(path), config()
    record = event()
    store.add(first, [record])
    restored = EventStore(path)
    assert restored.batch(first.destination)["events"] == [record]
    second = replace(first, account_id=2)
    assert restored.batch(second.destination) is None
    # Rotating a key for the same confirmed account preserves its queue.
    rotated = replace(first, api_key="y"*43)
    assert rotated.destination == first.destination
    restored.acknowledge(first.destination, [record["id"]])
    assert restored.counts(first.destination) == (0, 0)
    assert restored.recent(first.destination)[0][1] == SENT


def test_local_cache_retention(tmp_path):
    store, first = EventStore(tmp_path / "db"), config()
    old = event(time.time()-31*86400)
    uploaded = event(time.time()-8*86400)
    recent = event()
    store.add(first, [old, uploaded, recent])
    store.acknowledge(first.destination, [uploaded["id"]])
    store.cleanup()
    assert store.batch(first.destination)["events"] == [recent]


def test_multiple_device_queues_have_separate_batches(tmp_path):
    store, first = EventStore(tmp_path / "db"), config()
    second = replace(first, device_id=str(uuid4()))
    one, two = event(), event()
    store.add(first, [one])
    store.add(second, [two])
    result = store.batch(first.destination)
    assert result["device"]["id"] == first.device_id
    assert result["events"] == [one]


def test_status_events_share_durable_queue_and_batch(tmp_path):
    store, first = EventStore(tmp_path / "db"), config()
    record = status_event()
    store.add(first, [record])
    assert store.batch(first.destination)["events"] == [record]
    store.acknowledge(first.destination, [record["id"]])
    assert store.recent(first.destination)[0][0] == record


def test_day_query_returns_sent_and_pending_records_of_one_connection(tmp_path):
    store, first = EventStore(tmp_path / "db"), config()
    other = replace(first, account_id=2)
    now = time.time()
    early, sent, pending, outside = event(now - 7200), event(now - 600), status_event(now - 60), event(now - 90000)
    store.add(first, [pending, sent, early, outside])
    store.add(other, [event(now - 300)])
    store.acknowledge(first.destination, [sent["id"]])
    assert store.between(first.destination, now - 86400, now) == [early, sent, pending]


def test_config_aliases_and_power_options_validate():
    first = config(app_aliases={" Chrome.EXE ": "浏览器", r"C:\Program Files\Code\Code.exe": "编辑器"},
                   battery_seconds=60, upload_on_shutdown=True, upload_on_suspend=False)
    first.validate()
    assert first.app_aliases == {"chrome.exe": "浏览器", "code.exe": "编辑器"}
    with pytest.raises(ValueError):
        replace(first, app_aliases={"chrome.exe": ""}).validate()
    assert first.status_enabled
    assert not replace(first, battery_enabled=False, upload_on_shutdown=False).status_enabled


def test_alias_lookup_matches_with_or_without_exe_suffix():
    from focus_agent.winapi import ForegroundReader

    reader = ForegroundReader.__new__(ForegroundReader)  # lookup logic only, no Windows handles
    reader.set_aliases({"chrome.exe": "浏览器", "notepad": "记事本"})
    assert reader.alias_for("Chrome.EXE") == "浏览器"
    assert reader.alias_for("notepad.exe") == "记事本"
    assert reader.alias_for("code.exe") is None


def test_unpaired_surrogates_are_made_encodable():
    from focus_agent.winapi import clean_text

    cleaned = clean_text("bad\ud800name.exe")
    assert cleaned == "bad\ufffdname.exe"
    cleaned.encode("utf-8")


@pytest.mark.parametrize("raw,expected", [
    # Desktop without battery: the old code reported charging/unknown inconsistently.
    ((1, 128, 255, 0xFFFFFFFF), {"battery_percent": None, "charging": None, "ac_online": True,
                                 "battery_life_seconds": None}),
    # Status unknown (flag 255) must not be read as "charging" from bit 3.
    ((255, 255, 255, 0xFFFFFFFF), {"battery_percent": None, "charging": None, "ac_online": None,
                                   "battery_life_seconds": None}),
    ((1, 8 | 1, 57, 0xFFFFFFFF), {"battery_percent": 57, "charging": True, "ac_online": True,
                                  "battery_life_seconds": None}),
    ((0, 2, 18, 3600), {"battery_percent": 18, "charging": False, "ac_online": False,
                        "battery_life_seconds": 3600}),
    # Out-of-range firmware values never reach the server (it would reject the whole batch).
    ((1, 1, 140, 0xFFFFFFFF), {"battery_percent": None, "charging": False, "ac_online": True,
                               "battery_life_seconds": None}),
])
def test_power_status_normalization(raw, expected):
    from focus_agent.winapi import power_status

    assert power_status(*raw) == expected


def test_rejected_events_are_set_aside_without_blocking_queue(tmp_path):
    store, first = EventStore(tmp_path / "db"), config()
    bad, good = event(time.time() - 60), event()
    store.add(first, [bad, good])
    store.reject(first.destination, [bad["id"]])
    assert store.batch(first.destination)["events"] == [good]
    assert store.counts(first.destination) == (1, 1)
    assert dict((e["id"], state) for e, state in store.recent(first.destination)) == {
        bad["id"]: REJECTED, good["id"]: PENDING}
    # Rejected records follow the 7-day retention of settled records.
    old = event(time.time() - 8 * 86400)
    store.add(first, [old])
    store.reject(first.destination, [old["id"]])
    store.cleanup()
    assert old["id"] not in {e["id"] for e, _ in store.recent(first.destination)}


def http_error(code, body):
    return urllib.error.HTTPError("http://x/api", code, "error", {}, io.BytesIO(json.dumps(body).encode()))


def test_validation_errors_identify_only_located_events():
    from focus_agent.network import rejected_event_indexes

    located = {"detail": [{"loc": ["body", "events", 3, "device_status", "battery_percent"], "msg": "x"},
                          {"loc": ["body", "events", 0, "app_usage"], "msg": "x"}]}
    assert rejected_event_indexes(http_error(422, located)) == {0, 3}
    # A device-level problem or the clock-skew message must keep the queue intact for retries.
    assert rejected_event_indexes(http_error(422, {"detail": [{"loc": ["body", "device", "name"]}]})) == set()
    assert rejected_event_indexes(http_error(422, {"detail": "设备时间超前超过 5 分钟"})) == set()


def test_uploader_sets_aside_rejected_event_and_uploads_the_rest(tmp_path, monkeypatch):
    from focus_agent import network

    store, first = EventStore(tmp_path / "db"), config(upload_seconds=10)
    events = [event(time.time() - 90), event(time.time() - 60), event()]
    store.add(first, events)
    calls = []

    def fake_request(config, path, body=None, method=None):
        if path == "/api/v1/agent/app-aliases":
            return {"ok": True, "device_id": config.device_id, "app_aliases": body["app_aliases"]}
        calls.append([e["id"] for e in body["events"]])
        if len(calls) == 1:
            raise network.RejectedEvents({1})
        return {"acknowledged_ids": [e["id"] for e in body["events"]]}

    monkeypatch.setattr(network, "request_json", fake_request)
    uploader = network.Uploader(store, first)
    uploader.start()
    try:
        assert uploader.flush(3.0)
    finally:
        uploader.stop()
    states = dict((e["id"], state) for e, state in store.recent(first.destination))
    assert states == {events[0]["id"]: SENT, events[1]["id"]: REJECTED, events[2]["id"]: SENT}
    assert calls[1] == [events[0]["id"], events[2]["id"]]


def test_undecryptable_key_keeps_settings_and_asks_again(tmp_path):
    path, first = tmp_path / "config.json", config(device_name="办公室电脑")
    save_config(path, first, lambda text: "Zm9v")

    def broken(_):
        raise OSError("DPAPI data belongs to another account")

    loaded = load_config(path, broken)
    assert loaded.api_key == "" and not loaded.configured
    assert loaded.device_name == "办公室电脑" and loaded.device_id == first.device_id


@pytest.mark.parametrize("theme", ["system", "light", "dark"])
def test_theme_preference_survives_config_roundtrip(tmp_path, theme):
    path, first = tmp_path / "config.json", config(theme=theme)
    first.validate()
    save_config(path, first, lambda text: text)
    loaded = load_config(path, lambda text: text)
    assert loaded.theme == theme and loaded.device_id == first.device_id
    assert loaded.api_key == first.api_key


@pytest.mark.parametrize("theme", [None, "invalid", []])
def test_old_or_unknown_theme_preferences_follow_system(tmp_path, theme):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": theme}), encoding="utf-8")
    assert load_config(path, lambda text: text).theme == "system"
    path.write_text("{}", encoding="utf-8")
    assert load_config(path, lambda text: text).theme == "system"
    with pytest.raises(ValueError, match="主题"):
        config(theme=theme).validate()


def test_startup_state_respects_task_manager_disable(monkeypatch):
    from focus_agent import winapi

    values = {}
    monkeypatch.setattr(winapi, "registry_value", lambda path, name: values.get(path))
    assert not winapi.startup_enabled()
    values[winapi.RUN_KEY] = '"C:\\FocusLedger\\FocusLedger.exe" --startup'
    assert winapi.startup_enabled()
    values[winapi.APPROVED_KEY] = bytes([3]) + bytes(11)  # disabled in Task Manager
    assert not winapi.startup_enabled()
    values[winapi.APPROVED_KEY] = bytes([2]) + bytes(11)
    assert winapi.startup_enabled()


def test_connection_requires_status_capability(monkeypatch):
    from focus_agent import network

    monkeypatch.setattr(network, "request_json", lambda config, path: {
        "schema_version": 1, "account_id": 1, "username": "alice", "retention_days": 365
    })
    with pytest.raises(RuntimeError, match="不支持电池"):
        network.check_connection(config())
    monkeypatch.setattr(network, "request_json", lambda config, path, body=None: {
        "schema_version": 1, "account_id": 1, "username": "alice",
        "features": ["app_usage", "device_status"], "retention_days": 365
    } if body is None else {"acknowledged_ids": []})
    assert network.check_connection(config())["account_id"] == 1


def test_connection_probe_uses_the_bound_device_and_requires_upload_ack(monkeypatch):
    from focus_agent import network
    first = config()
    bound = first.bind_account(2, "bob")
    calls = []

    def request(candidate, path, body=None):
        calls.append((candidate, path, body))
        if body is None:
            return {"schema_version": 1, "account_id": 2, "username": "bob", "retention_days": 365,
                    "features": ["app_usage", "device_status"]}
        return {"acknowledged_ids": []}

    first.device_ids[bound.destination] = bound.device_id
    monkeypatch.setattr(network, "request_json", request)
    result = network.check_connection(first)
    assert result["upload_verified"]
    assert result["device_id"] == bound.device_id
    assert calls[1][1] == "/api/v1/usage/batches"
    assert calls[1][2]["events"] == []
    assert calls[1][2]["device"]["id"] == bound.device_id
    assert first.account_id == 1


def test_device_identity_mapping_survives_restart_and_key_rotation(tmp_path):
    first = config()
    first.device_ids[first.destination] = first.device_id
    other = first.bind_account(2, "bob")
    returned = other.bind_account(1, "alice")
    assert returned.device_id == first.device_id
    assert other.device_id != first.device_id
    path = tmp_path / "config.json"
    save_config(path, other, lambda text: text)
    restored = load_config(path, lambda text: text)
    assert restored.bind_account(1, "alice").device_id == first.device_id
    assert replace(restored, api_key="y" * 43).bind_account(2, "bob").device_id == other.device_id


@pytest.mark.skipif(sys.platform != "win32", reason="Windows power API")
def test_windows_battery_reader_returns_normalized_status():
    from focus_agent.winapi import BatteryReader

    status = BatteryReader().status()
    assert status is None or set(status) == {
        "battery_percent", "charging", "ac_online", "battery_life_seconds"
    }
    if status and status["battery_percent"] is not None:
        assert 0 <= status["battery_percent"] <= 100


@pytest.mark.parametrize("host", ["https://example.com", "host:8080", "example.com/path", "a@b.com", ""])
def test_invalid_server_addresses(host):
    with pytest.raises(ValueError):
        replace(config(), host=host).validate()


def test_ipv6_address():
    ipv6 = replace(config(), host="::1")
    ipv6.validate()
    assert ipv6.base_url == "http://[::1]:8080"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI")
def test_dpapi_configuration_roundtrip(tmp_path):
    from focus_agent.winapi import decrypt, encrypt
    path, first = tmp_path / "config.json", config()
    save_config(path, first, encrypt)
    assert first.api_key not in path.read_text(encoding="utf-8")
    assert load_config(path, decrypt).api_key == first.api_key
    assert decrypt(encrypt("中文密钥123")) == "中文密钥123"
