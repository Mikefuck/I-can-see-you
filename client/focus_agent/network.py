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


class AliasSyncUnavailable(RuntimeError):
    pass


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


def request_json(config, path, body=None, method=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(config.base_url + path, data=data,
        headers={"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json",
                 "User-Agent": "FocusLedger/" + __version__}, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("服务器响应过大")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if path == "/api/v1/agent/app-aliases" and exc.code in (404, 405):
            raise AliasSyncUnavailable("服务端不支持历史名称同步，请升级服务端") from None
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
    if (not isinstance(result, dict) or result.get("schema_version") != 1 or
            type(result.get("account_id")) is not int or result["account_id"] <= 0 or
            not isinstance(result.get("username"), str) or not result["username"] or
            type(result.get("retention_days")) is not int or not 1 <= result["retention_days"] <= 365):
        raise RuntimeError("服务器接口版本不兼容")
    if config.status_enabled and "device_status" not in result.get("features", []):
        raise RuntimeError("服务器不支持电池和关机状态，请先升级服务端")
    bound = config.bind_account(result["account_id"], result["username"])
    response = request_json(bound, "/api/v1/usage/batches", {
        "schema_version": 1, "device": {"id": bound.device_id, "name": bound.device_name,
        "platform": "windows", "agent_version": __version__}, "events": []})
    if not isinstance(response, dict) or response.get("acknowledged_ids") != []:
        raise RuntimeError("服务器未确认设备上传测试，请检查上传接口")
    return {**result, "device_id": bound.device_id, "upload_verified": True}


class Uploader:
    def __init__(self, store, config):
        self.store = store
        self.lock = threading.Lock()
        self.config = replace(config)
        self.alias_state = None
        self.messages = Queue()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="focus-upload", daemon=True)

    def start(self):
        self.thread.start()

    def configure(self, config):
        with self.lock:
            self.config = replace(config)
            self.alias_state = None
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

    def sync_aliases(self, config):
        """Retry from the saved config after outages/restarts; cache only confirmed snapshots."""
        signature = (config.base_url, config.api_key, config.device_id, tuple(sorted(config.app_aliases.items())))
        with self.lock:
            state = self.alias_state
        if state is not None and state[0] == signature:
            return state[1]
        body = {"device": {"id": config.device_id, "name": config.device_name,
                "platform": "windows", "agent_version": __version__}, "app_aliases": config.app_aliases}
        try:
            result = request_json(config, "/api/v1/agent/app-aliases", body, method="PUT")
        except AliasSyncUnavailable as exc:
            # Older servers still receive usage records. Recheck on the next settings save/start.
            warning = str(exc)
        except RuntimeError as exc:
            raise RuntimeError("记录已上传，名称同步失败：" + str(exc)) from exc
        else:
            if (not isinstance(result, dict) or result.get("ok") is not True or
                    result.get("device_id") != config.device_id or result.get("app_aliases") != config.app_aliases):
                raise RuntimeError("服务器未确认应用名翻译，稍后重试")
            warning = ""
        with self.lock:
            self.alias_state = (signature, warning)
        return warning

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
                    warning = self.sync_aliases(config)
                    failures = 0
                    if warning:
                        self.messages.put((False, "记录已上传 · " + warning))
                    else:
                        self.messages.put((True, "上传成功 · " + time.strftime("%H:%M:%S") +
                                           (" · 名称已同步" if config.app_aliases else "")))
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
