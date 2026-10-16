import gzip
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from queue import Queue

from . import __version__
from .identity import machine_identity


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


class ColorSyncUnavailable(RuntimeError):
    pass


class DeviceNameConflict(RuntimeError):
    pass


class UploadCompressionUnavailable(RuntimeError):
    pass


def encode_json(body, *, compress=False):
    """Keep event values intact; compress only when the request actually gets smaller."""
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if compress and len(data) >= 256:
        compressed = gzip.compress(data, compresslevel=6, mtime=0)
        if len(compressed) < len(data):
            return compressed, True
    return data, False


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


def request_json(config, path, body=None, method=None, *, compress=False):
    data, compressed = encode_json(body, compress=compress) if body is not None else (None, False)
    urls = config.connection_urls
    for index, base_url in enumerate(urls):
        try:
            result = _request_json(config, base_url, path, data, body, method,
                                   timeout=3 if len(urls) > 1 else 10, compressed=compressed)
        except UploadCompressionUnavailable:
            # This route is reachable; the plain retry should not revisit a failed route.
            config.preferred_endpoint = base_url
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if index + 1 < len(urls):
                continue
            if isinstance(exc, urllib.error.HTTPError):
                raise RuntimeError(f"服务器返回 HTTP {exc.code}，两个地址均无法完成请求" if len(urls) > 1
                                   else f"服务器返回 HTTP {exc.code}") from None
            raise RuntimeError("两个服务器地址均无法连接，请检查地址、端口、网络和 HTTPS 证书" if len(urls) > 1
                               else "无法连接服务器，请检查地址、端口、网络和 HTTPS 证书") from exc
        config.preferred_endpoint = base_url
        return result


def _request_json(config, base_url, path, data, body, method, timeout, *, compressed=False):
    headers = {"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json",
               "User-Agent": "FocusLedger/" + __version__}
    if compressed:
        headers["Content-Encoding"] = "gzip"
    if path in {"/api/v1/usage/batches", "/api/v1/agent/app-aliases", "/api/v1/agent/app-colors"}:
        machine_id = machine_identity()
        if machine_id:
            headers["X-FocusLedger-Machine-ID"] = machine_id
    request = urllib.request.Request(base_url + path, data=data,
                                     headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("服务器响应过大")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            raise
        if compressed and exc.code in (400, 415):
            exc.close()
            raise UploadCompressionUnavailable("服务器或代理未接受压缩上传") from None
        if path == "/api/v1/agent/app-aliases" and exc.code in (404, 405):
            raise AliasSyncUnavailable("服务端不支持历史名称同步，请升级服务端") from None
        if path == "/api/v1/agent/app-colors" and exc.code in (404, 405):
            raise ColorSyncUnavailable("服务端不支持程序配色，请升级服务端") from None
        if exc.code == 409:
            try:
                detail = json.loads(exc.read(64 * 1024)).get("detail")
            except (ValueError, AttributeError):
                detail = None
            finally:
                exc.close()
            if isinstance(detail, dict) and detail.get("code") == "device_name_conflict":
                raise DeviceNameConflict("设备名称已被占用，请在设置中修改设备名称后重试") from None
        if exc.code == 422 and body is not None:
            indexes = rejected_event_indexes(exc)
            if indexes:
                raise RejectedEvents(indexes) from None
        messages = {401: "上传密钥无效或账户已停用", 409: "设备身份或记录冲突", 422: "记录格式或设备时钟错误",
                    413: "上传包过大", 429: "请求过于频繁"}
        raise RuntimeError(messages.get(exc.code, f"服务器返回 HTTP {exc.code}")) from None


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
    config.preferred_endpoint = bound.active_url
    return {**result, "device_id": bound.device_id, "upload_verified": True, "connected_url": bound.active_url}


class Uploader:
    def __init__(self, store, config):
        self.store = store
        self.lock = threading.Lock()
        self.config = replace(config)
        self.alias_state = None
        self.color_state = None
        self.compression_state = None
        self.foreground = None
        self.foreground_supported = None
        self.messages = Queue()
        self.wake = threading.Event()
        self.force_upload = True
        self.retry_at = 0.0
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="focus-upload", daemon=True)

    def start(self):
        self.thread.start()

    def configure(self, config):
        with self.lock:
            if not config.upload_on_app_change or (self.config.destination, self.config.device_id) != (config.destination, config.device_id):
                self.foreground = None
            self.foreground_supported = None
            preferred = (self.config.active_url if self.config.base_urls == config.base_urls and
                         self.config.api_key == config.api_key else config.active_url)
            self.config = replace(config, preferred_endpoint=preferred)
            # Confirmed mappings remain valid when unrelated settings change. Retry warnings
            # on a settings save so an upgraded server can be detected without a restart.
            if self.alias_state is not None and self.alias_state[1]:
                self.alias_state = None
            if self.color_state is not None and self.color_state[1]:
                self.color_state = None
            if self.compression_state is not None and not self.compression_state[1]:
                self.compression_state = None
        self.trigger()

    def trigger(self):
        with self.lock:
            self.force_upload = True
        self.wake.set()

    def observe_foreground(self, app, wall, *, trigger=True):
        """Keep only the latest observation; usage records remain in the durable queue."""
        with self.lock:
            if not self.config.upload_on_app_change:
                return
            current = {"app_name": app.app_name, "process_name": app.process_name} if app else None
            previous = self.foreground
            changed = previous is None or previous["app"] != current
            observed = datetime.fromtimestamp(wall, timezone.utc).isoformat()
            since = observed if changed or observed < previous["observed_at"] else previous["since"]
            self.foreground = {"observed_at": observed, "since": since, "app": current}
        if changed and trigger:
            # Automatic app changes keep the newest snapshot, but respect failure backoff.
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

    def _request(self, config, path, body=None, method=None):
        # Capability discovery rides on the first ordinary upload, avoiding another request.
        signature = (config.base_urls, config.api_key)
        with self.lock:
            state = self.compression_state
        compress = state is not None and state[0] == signature and state[1]
        try:
            if compress:
                result = request_json(config, path, body, method, compress=True)
            else:
                result = request_json(config, path, body, method)
        except UploadCompressionUnavailable:
            # A reverse proxy or an older fallback server may reject Content-Encoding.
            # Retry the same IDs once as JSON, and stop trying compression for this connection.
            with self.lock:
                self.compression_state = (signature, False)
            result = request_json(config, path, body, method)
        if path == "/api/v1/usage/batches" and isinstance(result, dict):
            encodings = result.get("upload_encodings")
            with self.lock:
                if self.compression_state is None or self.compression_state[0] != signature:
                    self.compression_state = (signature, isinstance(encodings, list) and "gzip" in encodings)
        return result

    def sync_aliases(self, config):
        """Retry from the saved config after outages/restarts; cache only confirmed snapshots."""
        signature = (config.base_urls, config.api_key, config.device_id, config.device_name,
                     tuple(sorted(config.app_aliases.items())))
        with self.lock:
            state = self.alias_state
        if state is not None and state[0] == signature:
            return state[1]
        body = {"device": {"id": config.device_id, "name": config.device_name,
                "platform": "windows", "agent_version": __version__}, "app_aliases": config.app_aliases}
        try:
            result = self._request(config, "/api/v1/agent/app-aliases", body, method="PUT")
        except AliasSyncUnavailable as exc:
            # Older servers still receive usage records. Recheck on the next settings save/start.
            warning = str(exc)
        except DeviceNameConflict:
            raise
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

    def sync_colors(self, config):
        """An empty mapping clears overrides too; failures never acknowledge this snapshot."""
        signature = (config.base_urls, config.api_key, config.device_id, config.device_name,
                     tuple(sorted(config.app_colors.items())))
        with self.lock:
            state = self.color_state
        if state is not None and state[0] == signature:
            return state[1]
        body = {"device": {"id": config.device_id, "name": config.device_name,
                "platform": "windows", "agent_version": __version__}, "app_colors": config.app_colors}
        try:
            result = self._request(config, "/api/v1/agent/app-colors", body, method="PUT")
        except ColorSyncUnavailable as exc:
            warning = str(exc) if config.app_colors else ""
        except DeviceNameConflict:
            raise
        except RuntimeError as exc:
            raise RuntimeError("记录已上传，配色同步失败：" + str(exc)) from exc
        else:
            if (not isinstance(result, dict) or result.get("ok") is not True or
                    result.get("device_id") != config.device_id or result.get("app_colors") != config.app_colors):
                raise RuntimeError("服务器未确认程序配色，稍后重试")
            warning = ""
        with self.lock:
            self.color_state = (signature, warning)
        return warning

    def _run(self):
        failures = 0
        last_cleanup = 0
        while not self.stop_event.is_set():
            # Clear before snapshot/upload so a configuration change during the request is not lost.
            self.wake.clear()
            with self.lock:
                retry_wait = max(0, self.retry_at - time.monotonic()) if not self.force_upload else 0
                self.force_upload = False
                # configure() replaces the object; keep this snapshot so successful routes survive retries.
                config = self.config
                foreground, supported = self.foreground, self.foreground_supported
            if retry_wait:
                self.wake.wait(retry_wait)
                continue
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
                    elif payload["device"]["id"] == config.device_id:
                        # Renaming after a conflict must also repair pending records made under
                        # the old name. Event IDs and payloads stay unchanged for deduplication.
                        payload["device"] = {**payload["device"], "name": config.device_name}
                    foreground_warning = ""
                    if config.upload_on_app_change and foreground is not None and payload["device"]["id"] == config.device_id:
                        if supported is None:
                            capabilities = request_json(config, "/api/v1/agent/check")
                            supported = "foreground" in capabilities.get("features", [])
                            with self.lock:
                                if self.config is config:
                                    self.foreground_supported = supported
                        if supported:
                            payload["foreground"] = foreground
                        else:
                            foreground_warning = "服务端不支持实时前台状态，请升级服务端"
                    result = self._request(config, "/api/v1/usage/batches", payload)
                    sent_ids = {event["id"] for event in payload["events"]}
                    acknowledged = result.get("acknowledged_ids")
                    if not isinstance(acknowledged, list) or set(acknowledged) != sent_ids:
                        raise RuntimeError("服务器未完整确认记录，保留缓存等待重试")
                    self.store.acknowledge(config.destination, acknowledged)
                    warning = " · ".join(filter(None, (foreground_warning, self.sync_aliases(config), self.sync_colors(config))))
                    failures = 0
                    with self.lock:
                        self.retry_at = 0.0
                    if warning:
                        self.messages.put((False, "记录已上传 · " + warning))
                    else:
                        self.messages.put((True, "上传成功 · " + time.strftime("%H:%M:%S") +
                                           (" · 名称已同步" if config.app_aliases else "") +
                                           (" · 配色已同步" if config.app_colors else "") +
                                           (" · " + config.active_url if len(config.base_urls) > 1 else "")))
                    if self.store.counts(config.destination)[0]:
                        wait = 1
                except RejectedEvents as exc:
                    ids = [payload["events"][i]["id"] for i in sorted(exc.indexes) if i < len(payload["events"])]
                    self.store.reject(config.destination, ids)
                    logging.warning("Server rejected invalid events, set aside locally: %s", ids)
                    self.messages.put((False, f"服务器拒收 {len(ids)} 条无效记录，已跳过并保留在本地"))
                    wait = 1
                except DeviceNameConflict as exc:
                    wait = 300
                    with self.lock:
                        self.retry_at = time.monotonic() + wait
                    self.messages.put((False, str(exc)))
                except Exception as exc:
                    failures += 1
                    wait = min(300, config.upload_seconds * 2 ** min(failures - 1, 5))
                    with self.lock:
                        self.retry_at = time.monotonic() + wait
                    self.messages.put((False, f"{exc} · {wait}秒后重试"))
            self.wake.wait(wait)
