import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from focus_agent.config import Config
from focus_agent.network import Uploader, check_connection, request_json
from focus_agent.management import ManagementSession
from focus_agent.store import EventStore
from server.app.config import Settings
from server.app.main import create_app
from server.app.security import token_hash

from test_server import PASSWORD, batch
import pytest
from fastapi.responses import JSONResponse


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
