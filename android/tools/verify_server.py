"""Run the actual Java HTTP client against an isolated local Focus Ledger server."""
import argparse
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import uvicorn
from server.app.config import Settings
from server.app.main import create_app
from server.app.security import token_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--java", required=True)
    parser.add_argument("--classpath", required=True)
    args = parser.parse_args()
    runtime = ROOT / ".runtime" / "android"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="server-check-", dir=runtime) as temporary:
        directory = Path(temporary)
        password = "android-integration-only-123456"
        key = "android-integration-only-token-" + "x" * 40
        app = create_app(Settings(directory / "server.db", admin_username="android_admin", admin_password=password))
        app.state.database.initialize()
        with app.state.database.connect() as db:
            db.execute("UPDATE users SET upload_hash=?, shared=1 WHERE id=1", (token_hash(key),))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            if not server.started:
                raise RuntimeError("Isolated test server did not start")
            fixture = directory / "fixture.json"
            fixture.write_text(json.dumps({"url": f"http://127.0.0.1:{listener.getsockname()[1]}", "key": key, "password": password}), encoding="utf-8")
            result = subprocess.run([args.java, "-Dfile.encoding=UTF-8", "-cp", args.classpath,
                                     "com.focusledger.android.ServerIntegrationProbe", str(fixture)], cwd=ROOT, timeout=60)
            if result.returncode:
                raise RuntimeError("Java real-server probe failed")
            with app.state.database.connect() as db:
                assert db.execute("SELECT count(*),sum(duration_seconds) FROM events").fetchone()[:] == (1, 30)
                assert db.execute("SELECT count(*) FROM status_events").fetchone()[0] == 1
                assert db.execute("SELECT platform FROM devices").fetchone()[0] == "android"
                assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 2
            print("Database verified: retries and key rotation did not duplicate app usage or battery events.")
        finally:
            server.should_exit = True
            thread.join(10)
            listener.close()


if __name__ == "__main__":
    main()
