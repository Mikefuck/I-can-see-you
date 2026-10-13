import socket
import threading
import time
from pathlib import Path

import uvicorn

from focus_agent.config import Config
from focus_agent.network import Uploader, check_connection, request_json
from focus_agent.store import EventStore
from server.app.config import Settings
from server.app.main import create_app
from server.app.security import token_hash

from test_server import PASSWORD, batch


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
