import socket
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import uvicorn

from focus_agent.config import Config
from focus_agent.network import Uploader, check_connection, request_json
from focus_agent import network
from focus_agent.management import ManagementSession
from focus_agent.store import EventStore
from server.app.config import Settings
from server.app.main import create_app
from server.app.security import token_hash

from test_server import PASSWORD, batch
import pytest
from fastapi.responses import JSONResponse


def test_real_http_foreground_changes_retry_latest_state_and_preserve_usage(tmp_path, monkeypatch):
    from focus_agent.tracker import Application

    app = create_app(Settings(tmp_path / "foreground.db", admin_username="admin", admin_password=PASSWORD))
    app.state.database.initialize()
    key = "foreground-token-" + "x" * 30
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET upload_hash=?,shared=1 WHERE id=1", (token_hash(key),))
    unavailable = threading.Event()

    @app.middleware("http")
    async def simulated_outage(request, call_next):
        if request.url.path == "/api/v1/usage/batches" and unavailable.is_set():
            await request.body()
            return JSONResponse({"detail": "temporary outage"}, 503)
        return await call_next(request)

    monkeypatch.setattr(network, "machine_identity", lambda: "a" * 64)
    with real_server(app) as port:
        config = Config(host="127.0.0.1", port=port, api_key=key, account_id=1, upload_on_app_change=True, upload_seconds=10)
        store = EventStore(tmp_path / "events.db")
        uploader = Uploader(store, config)
        uploader.observe_foreground(Application("Browser", "browser.exe"), time.time())
        uploader.start()

        def live_device():
            return request_json(config, "/api/web/live")["people"][0]["devices"][0]

        try:
            assert uploader.messages.get(timeout=3)[0]
            assert live_device()["last"]["process"] == "browser.exe"
            unavailable.set()
            usage = batch()["events"]
            store.add(config, usage)
            uploader.observe_foreground(Application("Editor", "editor.exe"), time.time())
            assert not uploader.messages.get(timeout=3)[0]
            assert store.counts(config.destination) == (1, 1)
            unavailable.clear()
            uploader.observe_foreground(Application("Terminal", "terminal.exe"), time.time())
            # App changes update the snapshot during backoff; the scheduled retry sends the latest one.
            assert uploader.messages.get(timeout=12)[0]
            assert live_device()["last"]["process"] == "terminal.exe"
            assert store.counts(config.destination) == (0, 0)
            uploader.observe_foreground(None, time.time())
            assert uploader.messages.get(timeout=3)[0]
            assert live_device()["state"] == "idle"
            with app.state.database.connect() as db:
                assert db.execute("SELECT COUNT(*),SUM(duration_seconds) FROM events").fetchone()[:] == (1, 30)
        finally:
            uploader.stop()
            uploader.thread.join(3)


@contextmanager
def real_server(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield listener.getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_real_http_compressed_backlog_and_lost_ack_keep_exact_usage(tmp_path, monkeypatch):
    import gzip

    app = create_app(Settings(tmp_path / "compressed.db", admin_username="admin", admin_password=PASSWORD))
    app.state.database.initialize()
    key = "compressed-upload-token-" + "x" * 30
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET upload_hash=? WHERE id=1", (token_hash(key),))
    requests, lose_ack = [], [True]

    @app.middleware("http")
    async def capture_and_drop_one_ack(request, call_next):
        is_upload = request.url.path == "/api/v1/usage/batches"
        compressed = request.headers.get("content-encoding") == "gzip"
        if is_upload:
            data = await request.body()
            body = json.loads(gzip.decompress(data) if compressed else data)
            requests.append((compressed, len(data), body))
        response = await call_next(request)
        if is_upload and compressed and lose_ack[0]:
            assert response.status_code == 200
            lose_ack[0] = False
            return JSONResponse({"detail": "Synthetic lost acknowledgement after commit"}, 503)
        return response

    monkeypatch.setattr(network, "machine_identity", lambda: "a" * 64)
    with real_server(app) as port:
        current = Config(host="127.0.0.1", port=port, api_key=key, account_id=1)
        store = EventStore(tmp_path / "queue.db")
        now = time.time()
        records = [batch(end=now - 30 * offset)["events"][0] for offset in range(1200, 0, -1)]
        store.add(current, records)
        uploader = Uploader(store, current)
        uploader.start()
        try:
            assert uploader.messages.get(timeout=5)[0]
            assert not uploader.messages.get(timeout=5)[0]
            assert store.counts(current.destination) == (700, 700)
            uploader.trigger()
            assert uploader.messages.get(timeout=5)[0]
            assert uploader.messages.get(timeout=5)[0]
            assert store.counts(current.destination) == (0, 0)
        finally:
            uploader.stop()
            uploader.thread.join(5)
        assert [len(body["events"]) for _, _, body in requests] == [500, 500, 500, 200]
        assert [compressed for compressed, _, _ in requests] == [False, True, True, True]
        assert requests[1][2]["events"] == requests[2][2]["events"]
        assert requests[1][1] < len(json.dumps(requests[1][2]).encode()) * .25
        with app.state.database.connect() as db:
            assert db.execute("SELECT COUNT(*),SUM(duration_seconds) FROM events").fetchone()[:] == (1200, 36000)


def test_real_http_color_sync_retries_offline_and_restores_history_defaults(tmp_path, monkeypatch):
    from focus_agent.app_colors import default_color
    app = create_app(Settings(tmp_path / "colors.db", admin_username="admin", admin_password=PASSWORD))
    app.state.database.initialize()
    key = "program-colors-token-" + "x" * 30
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET upload_hash=?,shared=1 WHERE id=1", (token_hash(key),))
    unavailable = threading.Event()
    unavailable.set()

    @app.middleware("http")
    async def simulated_outage(request, call_next):
        if request.url.path == "/api/v1/agent/app-colors" and unavailable.is_set():
            await request.body()
            return JSONResponse({"detail": "temporary outage"}, 503)
        return await call_next(request)

    monkeypatch.setattr(network, "machine_identity", lambda: "a" * 64)
    with real_server(app) as port:
        current = Config(host="127.0.0.1", port=port, api_key=key, account_id=1,
                         device_name="配色测试电脑", app_colors={"example.exe": "teal"})
        store = EventStore(tmp_path / "queue.db")
        store.add(current, batch()["events"])
        uploader = Uploader(store, current)
        uploader.start()
        try:
            success, message = uploader.messages.get(timeout=5)
            assert not success and "配色同步失败" in message
            assert uploader.color_state is None and store.counts(current.destination) == (0, 0)
            unavailable.clear()
            uploader.trigger()
            success, message = uploader.messages.get(timeout=5)
            assert success and "配色已同步" in message
            data = request_json(current, "/api/web/board")
            assert data["app_colors"] == ["teal"]
            reset = replace(current, app_colors={})
            uploader.configure(reset)
            assert uploader.messages.get(timeout=5)[0]
            assert request_json(reset, "/api/web/board")["app_colors"] == [default_color("example.exe")]
            with app.state.database.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
                assert db.execute("SELECT machine_id FROM device_computers").fetchone()[0] == "a" * 64
        finally:
            uploader.stop()
            uploader.thread.join(5)


def test_real_http_device_name_identity_upgrade_conflict_and_rename(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path / "names.db", admin_username="admin", admin_password=PASSWORD))
    app.state.database.initialize()
    key = "device-name-token-" + "x" * 30
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET upload_hash=? WHERE id=1", (token_hash(key),))
    machine = ["a" * 64]
    monkeypatch.setattr(network, "machine_identity", lambda: machine[0])
    with real_server(app) as port:
        original = Config(host="127.0.0.1", port=port, api_key=key, account_id=1, device_name="家用电脑")
        assert check_connection(original)["upload_verified"]
        records = batch()["events"]
        store = EventStore(tmp_path / "queue.db")
        store.add(original, records)
        # A clean client installation gets a new UUID but must reuse the name's history.
        upgraded = Config(host=original.host, port=port, api_key=key, account_id=1, device_name=original.device_name)
        assert original.device_id != upgraded.device_id
        assert check_connection(upgraded)["upload_verified"]
        uploader = Uploader(store, upgraded)
        uploader.start()
        try:
            assert uploader.flush(3)
        finally:
            uploader.stop()
            uploader.thread.join(3)
        machine[0] = "b" * 64
        other = Config(host=original.host, port=port, api_key=key, account_id=1, device_name=original.device_name)
        with pytest.raises(network.DeviceNameConflict, match="设备名称已被占用"):
            check_connection(other)
        store.add(other, batch()["events"])
        renamed = replace(other, device_name="另一台家用电脑")
        assert check_connection(renamed)["upload_verified"]
        uploader = Uploader(store, renamed)
        uploader.start()
        try:
            assert uploader.flush(3)
        finally:
            uploader.stop()
            uploader.thread.join(3)
        with app.state.database.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 2
            assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
            assert {row[0] for row in db.execute("SELECT name FROM devices")} == {"家用电脑", "另一台家用电脑"}


def test_real_http_management_and_upload_permissions(tmp_path):
    app = create_app(Settings(tmp_path / "management.db", admin_username="admin", admin_password=PASSWORD))
    with real_server(app) as port:
        endpoint = Config(host="127.0.0.1", port=port)
        admin = ManagementSession(endpoint)
        assert admin.login("admin", PASSWORD)["is_admin"]
        assert len(admin.overview()["users"]) == 1
        member_id = admin.request("/users", {"username": "alice", "password": PASSWORD, "is_admin": False}, "POST")["id"]
        member = ManagementSession(endpoint)
        assert not member.login("alice", PASSWORD)["is_admin"]
        with pytest.raises(RuntimeError, match="管理员"):
            member.overview()
        token = member.request("/token", {}, "POST")["api_key"]
        endpoint.api_key = token
        checked = check_connection(endpoint)
        assert checked["account_id"] == member_id and checked["upload_verified"]
        config = endpoint.bind_account(member_id, "alice", checked["device_id"])
        assert request_json(config, "/api/v1/usage/batches", batch(device=config.device_id))["inserted"] == 1
        admin.request("/settings", {"retention_days": 10}, "PUT")
        assert admin.overview()["settings"]["retention_days"] == 10
        admin.request(f"/users/{member_id}", {"enabled": False}, "PATCH")
        with pytest.raises(RuntimeError):
            member.request("/token", {}, "POST")
        with pytest.raises(RuntimeError, match="密钥无效"):
            check_connection(config)
        admin.request("/logout", {}, "POST")
        admin.close()


def test_real_http_connection_probe_detects_blocked_upload(tmp_path):
    app = create_app(Settings(tmp_path / "blocked.db", admin_username="admin", admin_password=PASSWORD))

    @app.middleware("http")
    async def block_post(request, call_next):
        if request.url.path == "/api/v1/usage/batches":
            await request.body()  # Deliver a deterministic HTTP rejection rather than resetting a pending POST.
            return JSONResponse({"detail": "Synthetic blocked upload"}, 403)
        return await call_next(request)

    with real_server(app) as port:
        config = Config(host="127.0.0.1", port=port)
        session = ManagementSession(config)
        session.login("admin", PASSWORD)
        config.api_key = session.request("/token", {}, "POST")["api_key"]
        assert request_json(config, "/api/v1/agent/check")["ok"]
        with pytest.raises(RuntimeError, match="HTTP 403"):
            check_connection(config)


def test_real_http_dual_addresses_switch_both_ways_and_keep_offline_queue(tmp_path):
    settings = Settings(tmp_path / "dual.db", admin_username="admin", admin_password=PASSWORD)
    primary, fallback = create_app(settings), create_app(settings)
    primary.state.database.initialize()
    key = "dual-address-token-" + "x" * 30
    with primary.state.database.connect() as db:
        db.execute("UPDATE users SET upload_hash=? WHERE id=1", (token_hash(key),))
    unavailable = set()

    def gate(app, name):
        @app.middleware("http")
        async def availability(request, call_next):
            if name in unavailable:
                await request.body()
                return JSONResponse({"detail": "Synthetic unavailable route"}, 503)
            return await call_next(request)

    gate(primary, "primary")
    gate(fallback, "fallback")
    with real_server(primary) as primary_port, real_server(fallback) as fallback_port:
        original = Config(host="127.0.0.1", port=primary_port, api_key=key, account_id=1, username="admin")
        checked = check_connection(original)
        config = replace(original, fallback_host="127.0.0.1", fallback_port=fallback_port, upload_seconds=10)
        assert config.destination == original.destination
        unavailable.add("primary")
        assert check_connection(config)["device_id"] == checked["device_id"]
        assert config.active_url == f"http://127.0.0.1:{fallback_port}"
        session = ManagementSession(replace(config, preferred_endpoint=""))
        assert session.login("admin", PASSWORD)["is_admin"]
        assert session.base_url == config.active_url
        session.close()

        store = EventStore(tmp_path / "dual-queue.db")
        first = batch(device=config.device_id)["events"]
        store.add(original, first)  # Records collected before the second address was added.
        uploader = Uploader(store, config)
        uploader.start()
        try:
            assert uploader.flush(5)
            assert store.counts(original.destination)[0] == 0
            assert uploader.config.active_url == config.base_urls[1]
            unavailable.clear()
            unavailable.add("fallback")
            second = batch(device=config.device_id)["events"]
            store.add(config, second)
            assert uploader.flush(5)
            assert uploader.config.active_url == original.base_url
            assert uploader.config.device_id == original.device_id
            unavailable.add("primary")
            third = batch(device=config.device_id)["events"]
            store.add(config, third)
            assert not uploader.flush(0.5)
            assert store.batch(original.destination)["events"] == third
            unavailable.remove("fallback")
            assert uploader.flush(5)
            assert store.counts(original.destination)[0] == 0
            with primary.state.database.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == len(first + second + third)
        finally:
            uploader.stop()
            uploader.thread.join(5)


def test_real_http_client_to_server_and_offline_queue(tmp_path):
    app = create_app(Settings(tmp_path / "server.db", admin_username="admin", admin_password=PASSWORD))
    app.state.database.initialize()
    key = "integration-test-token-" + "x"*24
    with app.state.database.connect() as db:
        db.execute("UPDATE users SET upload_hash=? WHERE id=1", (token_hash(key),))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    uploader = None
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        config = Config(host="127.0.0.1", port=port, api_key=key, account_id=1)
        assert check_connection(config)["username"] == "admin"
        payload = batch(device=config.device_id)
        first = request_json(config, "/api/v1/usage/batches", payload)
        assert first["inserted"] == 1
        assert request_json(config, "/api/v1/usage/batches", payload)["duplicates"] == 1
        store = EventStore(tmp_path / "client.db")
        second = batch(device=config.device_id)
        store.add(config, second["events"])
        # Reopening the queue simulates process restart after an offline period.
        reopened = EventStore(tmp_path / "client.db")
        uploader = Uploader(reopened, config)
        uploader.start()
        deadline = time.monotonic()+5
        while reopened.counts(config.destination)[0] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert reopened.counts(config.destination) == (0, 0)
        with app.state.database.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    finally:
        if uploader:
            uploader.stop()
            uploader.thread.join(5)
        server.should_exit = True
        thread.join(5)
        listener.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows client GUI integration")
def test_gui_save_syncs_historical_and_new_names_over_real_http_and_retries(tmp_path, monkeypatch):
    """A settings save must update server history even when collection is paused and the queue is empty."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from focus_agent import gui
    from focus_agent.aliases import alias_for
    from focus_agent.config import load_config
    from focus_agent.tracker import Application, SessionTracker
    from focus_agent.winapi import decrypt

    qt = QApplication.instance() or QApplication([])
    server_app = create_app(Settings(tmp_path / "aliases.db", admin_username="admin", admin_password=PASSWORD))
    unavailable, attempted = threading.Event(), threading.Event()

    @server_app.middleware("http")
    async def alias_outage(request, call_next):
        if request.url.path == "/api/v1/agent/app-aliases" and unavailable.is_set():
            await request.body()
            attempted.set()
            return JSONResponse({"detail": "Synthetic offline alias endpoint"}, 503)
        return await call_next(request)

    class Reader:
        def set_aliases(self, aliases):
            self.aliases = aliases

        def sample(self, idle):
            return Application(alias_for(self.aliases, "example.exe") or "Example App", "example.exe"), "sample"

    class NoEvents:
        def __init__(self, callback):
            pass

        def close(self):
            pass

    monkeypatch.setattr(gui, "ForegroundReader", Reader)
    monkeypatch.setattr(gui, "SystemEventWindow", NoEvents)
    monkeypatch.setattr(gui, "set_startup", lambda enabled: None)
    monkeypatch.setattr(gui, "startup_enabled", lambda: False)

    def wait_for(predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qt.processEvents()
            if predicate():
                return
            time.sleep(0.02)
        assert predicate()

    with real_server(server_app) as port:
        config = Config(host="127.0.0.1", port=port, upload_seconds=10,
                        battery_enabled=False, upload_on_shutdown=False, upload_on_suspend=False)
        session = ManagementSession(config)
        session.login("admin", PASSWORD)
        config.api_key = session.request("/token", {}, "POST")["api_key"]
        config = config.bind_account(1, "admin", check_connection(config)["device_id"])
        historical = batch(device=config.device_id, end=time.time() - 86400)
        assert request_json(config, "/api/v1/usage/batches", historical)["inserted"] == 1

        def historical_names():
            with session.opener.open(config.base_url + f"/api/web/people/admin?start={time.time()-172800}&end={time.time()}", timeout=3) as response:
                return json.load(response)

        window = gui.MainWindow(config, tmp_path / "config.json", EventStore(tmp_path / "client.db"))
        try:
            window.stop_collection()
            wait_for(lambda: window.uploader.alias_state is not None)
            unavailable.set()
            window.add_process_aliases([Application("Example App", "example.exe")])
            window.aliases.item(0, 1).setText("历史与新记录统一名称")
            window.connection_job(True)  # No test-connection, upload button or new usage is required.
            wait_for(attempted.is_set)
            assert load_config(tmp_path / "config.json", decrypt).app_aliases == {"example.exe": "历史与新记录统一名称"}
            assert ["历史与新记录统一名称", "example.exe"] not in historical_names()["apps"]
            unavailable.clear()
            # Retry happens automatically at the normal ten-second backoff, while collection remains paused.
            wait_for(lambda: ["历史与新记录统一名称", "example.exe"] in historical_names()["apps"], timeout=13)
            assert not window.running
            data = historical_names()
            index = data["apps"].index(["历史与新记录统一名称", "example.exe"])
            assert any(row[0] == index for row in data["ranking"])
            assert request_json(config, "/api/v1/usage/batches", historical)["duplicates"] == 1

            application, _ = window.reader.sample(0)
            assert application.app_name == "历史与新记录统一名称"
            tracker = SessionTracker(segment_seconds=1)
            moment = time.time() - 3
            tracker.observe(application, moment, 1)
            records = tracker.observe(application, moment + 1, 2)
            window.store.add(window.config, records)
            window.uploader.trigger()
            wait_for(lambda: window.store.counts(config.destination)[0] == 0)
            with server_app.state.database.connect() as db:
                assert db.execute("SELECT app_name FROM events WHERE event_id=?", (records[0]["id"],)).fetchone()[0] == application.app_name

            # Clearing the mapping is also synchronized, including after a client restart.
            window.aliases.selectAll()
            window.remove_alias()
            window.connection_job(True)
            saved = load_config(tmp_path / "config.json", decrypt)
            window.uploader.stop()
            window.uploader.thread.join(5)
            window.uploader = Uploader(window.store, saved)
            window.uploader.start()
            wait_for(lambda: ["Example App", "example.exe"] in historical_names()["apps"])
        finally:
            window.quit_app()
            window.uploader.thread.join(5)
            session.close()


@pytest.mark.parametrize("missing", ["app-aliases", "app-colors"])
def test_old_server_keeps_uploading_and_reports_missing_history_sync(tmp_path, missing):
    app = create_app(Settings(tmp_path / "legacy.db", admin_username="admin", admin_password=PASSWORD))

    @app.middleware("http")
    async def legacy_server(request, call_next):
        if request.url.path == "/api/v1/agent/" + missing:
            await request.body()
            return JSONResponse({"detail": "Not Found"}, 404)
        return await call_next(request)

    with real_server(app) as port:
        config = Config(host="127.0.0.1", port=port, app_aliases={"example.exe": "新名称"},
                        app_colors={"example.exe": "teal"})
        session = ManagementSession(config)
        session.login("admin", PASSWORD)
        config.api_key = session.request("/token", {}, "POST")["api_key"]
        config = config.bind_account(1, "admin", check_connection(config)["device_id"])
        store = EventStore(tmp_path / "client.db")
        store.add(config, batch(device=config.device_id)["events"])
        uploader = Uploader(store, config)
        uploader.start()
        try:
            success, message = uploader.messages.get(timeout=5)
            assert not success and "记录已上传" in message and "升级服务端" in message
            assert store.counts(config.destination) == (0, 0)
            with app.state.database.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        finally:
            uploader.stop()
            uploader.thread.join(5)
            session.close()
