import io
import json
import urllib.error
from dataclasses import replace

import pytest

from focus_agent.config import Config, load_config, save_config
from focus_agent import network
from focus_agent.management import ManagementSession
from focus_agent.store import EventStore


def connection(**kwargs):
    return Config(host="public.example.com", port=443, protocol="https", api_key="x" * 43,
                  account_id=1, username="alice", fallback_host="192.168.1.10", **kwargs)


def test_two_endpoints_preserve_existing_queue_and_identity(tmp_path):
    old = replace(connection(), fallback_host="")
    old.device_ids[old.destination] = old.device_id
    path = tmp_path / "config.json"
    save_config(path, old, lambda key: key)
    # This is the same shape as an existing single-address configuration.
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("fallback_host", "fallback_port", "fallback_protocol"):
        raw.pop(key)
    path.write_text(json.dumps(raw), encoding="utf-8")
    restored = load_config(path, lambda key: key)
    assert restored.base_urls == (old.base_url,)
    dual = replace(restored, fallback_host="192.168.1.10")
    assert dual.base_urls == ("https://public.example.com:443", "http://192.168.1.10:8080")
    assert dual.destination == old.destination
    assert dual.bind_account(1, "alice").device_id == old.device_id
    dual.preferred_endpoint = dual.base_urls[1]
    assert dual.destination == old.destination
    save_config(path, dual, lambda key: key)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "preferred_endpoint" not in raw
    assert load_config(path, lambda key: key).base_urls == dual.base_urls


@pytest.mark.parametrize("fields", [
    {"fallback_host": "https://example.com"}, {"fallback_host": "host:8080"},
    {"fallback_host": "host/path"}, {"fallback_port": 0}, {"fallback_port": 65536},
    {"fallback_protocol": "ftp"},
])
def test_invalid_fallback_is_reported(fields):
    with pytest.raises(ValueError, match="备用地址"):
        replace(connection(), **fields).validate()


def test_fallback_ipv6_duplicate_and_stale_preference():
    config = replace(connection(), fallback_host=" [::1] ", fallback_port=8443, fallback_protocol="https")
    config.validate()
    assert config.base_urls[1] == "https://[::1]:8443"
    config.preferred_endpoint = config.base_urls[1]
    assert config.active_url == config.base_urls[1]
    assert replace(config, fallback_host="").active_url == config.base_url
    duplicate = replace(config, fallback_host=config.host, fallback_port=config.port,
                        fallback_protocol=config.protocol)
    assert duplicate.connection_urls == (config.base_url,)


def install_transport(monkeypatch, action):
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(json.dumps(action(request, timeout)).encode())

    monkeypatch.setattr(network.urllib.request, "build_opener", lambda *args: Opener())


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("offline"), TimeoutError("timeout"), OSError("connection reset"),
    urllib.error.HTTPError("http://x", 503, "unavailable", {}, None),
])
def test_failed_route_switches_and_remembers_success(monkeypatch, failure):
    config = connection()
    primary, fallback = config.base_urls
    calls = []
    available = {fallback}

    def transport(request, timeout):
        calls.append((request.full_url, timeout))
        if not any(request.full_url.startswith(url) for url in available):
            raise failure
        assert request.get_header("Authorization") == "Bearer " + config.api_key
        return {"acknowledged_ids": ["record"]}

    install_transport(monkeypatch, transport)
    assert network.request_json(config, "/upload", {"events": ["record"]})["acknowledged_ids"] == ["record"]
    assert calls == [(primary + "/upload", 3), (fallback + "/upload", 3)]
    calls.clear()
    network.request_json(config, "/check")
    assert calls == [(fallback + "/check", 3)]
    available.clear()
    available.add(primary)
    calls.clear()
    network.request_json(config, "/check")
    assert calls == [(fallback + "/check", 3), (primary + "/check", 3)]
    assert config.active_url == primary


@pytest.mark.parametrize("code", [301, 401, 403, 409, 413, 422, 429])
def test_account_validation_and_redirect_errors_do_not_switch(monkeypatch, code):
    config, calls = connection(), []

    def transport(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, code, "error", {}, io.BytesIO(b"{}"))

    install_transport(monkeypatch, transport)
    with pytest.raises(RuntimeError):
        network.request_json(config, "/api/v1/usage/batches", {"events": []})
    assert calls == [config.base_url + "/api/v1/usage/batches"]


def test_both_routes_offline_keep_preference_and_report_failure(monkeypatch):
    config = connection()
    config.preferred_endpoint = config.base_urls[1]
    calls = []

    def transport(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.URLError("offline")

    install_transport(monkeypatch, transport)
    with pytest.raises(RuntimeError, match="两个服务器地址均无法连接"):
        network.request_json(config, "/upload")
    assert calls == [url + "/upload" for url in config.connection_urls]
    assert config.active_url == config.base_urls[1]


def test_uploader_keeps_route_across_settings_updates(tmp_path):
    config = connection()
    uploader = network.Uploader(EventStore(tmp_path / "events.db"), config)
    uploader.config.preferred_endpoint = config.base_urls[1]
    uploader.configure(replace(config, upload_seconds=60))
    assert uploader.config.active_url == config.base_urls[1]
    uploader.configure(replace(config, fallback_host="192.168.1.20"))
    assert uploader.config.active_url == config.base_url


def test_management_login_can_choose_backup_but_session_stays_on_origin(monkeypatch):
    config, calls = connection(), []
    session = ManagementSession(config)

    def transport(request, timeout):
        calls.append(request.full_url)
        if request.full_url.startswith(config.base_url):
            raise urllib.error.URLError("offline")
        return {"ok": True}

    monkeypatch.setattr(session.opener, "open", lambda request, timeout: io.BytesIO(
        json.dumps(transport(request, timeout)).encode()))
    assert session.request("/login", {"username": "alice", "password": "example"}) == {"ok": True}
    assert session.base_url == config.base_urls[1]
    assert len(calls) == 2
    session.user = {"username": "alice"}
    calls.clear()
    def offline(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(session.opener, "open", offline)
    with pytest.raises(RuntimeError, match="重新登录"):
        session.request("/settings", {"retention_days": 30}, "PUT")
    assert calls == [session.base_url + "/api/v1/management/settings"]
