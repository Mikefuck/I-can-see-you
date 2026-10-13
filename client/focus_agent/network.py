import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from queue import Queue

from . import __version__


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RejectedEvents(RuntimeError):
    """The server pinpointed invalid events (by batch index); retrying them can never succeed."""
    def __init__(self, indexes):
        super().__init__("服务器拒收格式无效的记录")
        self.indexes = indexes


def rejected_event_indexes(error):
    # Only validation errors located at body.events[i] identify a bad record. Other 422s
    # (for example a device clock running ahead) are temporary and must keep the queue intact.
    try:
        detail = json.loads(error.read(64 * 1024)).get("detail")
    except Exception:
        return set()
    if not isinstance(detail, list):
        return set()
    indexes = set()
    for item in detail:
        location = item.get("loc") if isinstance(item, dict) else None
        if isinstance(location, list) and location[:2] == ["body", "events"] and \
                len(location) > 2 and isinstance(location[2], int):
            indexes.add(location[2])
    return indexes


def request_json(config, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(config.base_url + path, data=data,
        headers={"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json",
                 "User-Agent": "FocusLedger/" + __version__})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("服务器响应过大")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 422 and body is not None:
            indexes = rejected_event_indexes(exc)
            if indexes:
                raise RejectedEvents(indexes) from None
        messages = {401: "上传密钥无效或账户已停用", 409: "设备身份或记录冲突", 422: "记录格式或设备时钟错误",
                    413: "上传包过大", 429: "请求过于频繁"}
        raise RuntimeError(messages.get(exc.code, f"服务器返回 HTTP {exc.code}")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("无法连接服务器，请检查地址、端口、网络和 HTTPS 证书") from exc


def check_connection(config):
    result = request_json(config, "/api/v1/agent/check")
    if result.get("schema_version") != 1 or not isinstance(result.get("account_id"), int):
        raise RuntimeError("服务器接口版本不兼容")
    if config.status_enabled and "device_status" not in result.get("features", []):
        raise RuntimeError("服务器不支持电池和关机状态，请先升级服务端")
    return result


class Uploader:
    def __init__(self, store, config):
        self.store = store
        self.lock = threading.Lock()
        self.config = replace(config)
        self.messages = Queue()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="focus-upload", daemon=True)

    def start(self):
        self.thread.start()

    def configure(self, config):
        with self.lock:
            self.config = replace(config)
        self.wake.set()

    def trigger(self):
        self.wake.set()

    def flush(self, timeout=3.0):
        """Request an immediate upload and wait briefly for the current queue.

        The local SQLite queue remains the source of truth when the network is
        unavailable or Windows gives the process too little shutdown time.
        """
        with self.lock:
            config = replace(self.config)
        if not config.configured:
            return False
        self.trigger()
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            try:
                if self.store.counts(config.destination)[0] == 0:
                    return True
            except Exception:
                return False
            time.sleep(0.05)
        return False

    def stop(self):
        self.stop_event.set()
        self.wake.set()

    def _run(self):
        failures = 0
        last_cleanup = 0
        while not self.stop_event.is_set():
            # Clear before snapshot/upload so a configuration change during the request is not lost.
            self.wake.clear()
            with self.lock:
                config = replace(self.config)
            wait = config.upload_seconds
            if config.configured:
                try:
                    if time.monotonic() - last_cleanup > 60:
                        self.store.cleanup()
                        last_cleanup = time.monotonic()
                    payload = self.store.batch(config.destination)
                    if payload is None:
                        payload = {"schema_version": 1, "device": {"id": config.device_id, "name": config.device_name,
                                   "platform": "windows", "agent_version": __version__}, "events": []}
                    result = request_json(config, "/api/v1/usage/batches", payload)
                    sent_ids = {event["id"] for event in payload["events"]}
                    acknowledged = result.get("acknowledged_ids")
                    if not isinstance(acknowledged, list) or set(acknowledged) != sent_ids:
                        raise RuntimeError("服务器未完整确认记录，保留缓存等待重试")
                    self.store.acknowledge(config.destination, acknowledged)
                    failures = 0
                    self.messages.put((True, "上传成功 · " + time.strftime("%H:%M:%S")))
                    if self.store.counts(config.destination)[0]:
                        wait = 1
                except RejectedEvents as exc:
                    ids = [payload["events"][i]["id"] for i in sorted(exc.indexes) if i < len(payload["events"])]
                    self.store.reject(config.destination, ids)
                    logging.warning("Server rejected invalid events, set aside locally: %s", ids)
                    self.messages.put((False, f"服务器拒收 {len(ids)} 条无效记录，已跳过并保留在本地"))
                    wait = 1
                except Exception as exc:
                    failures += 1
                    wait = min(300, config.upload_seconds * 2 ** min(failures - 1, 5))
                    self.messages.put((False, f"{exc} · {wait}秒后重试"))
            self.wake.wait(wait)
