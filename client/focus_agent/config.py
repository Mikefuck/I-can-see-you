import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Config:
    host: str = ""
    port: int = 8080
    protocol: str = "http"
    api_key: str = ""
    account_id: int = 0
    username: str = ""
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    device_ids: dict = field(default_factory=dict)
    device_name: str = field(default_factory=socket.gethostname)
    startup: bool = False
    silent_start: bool = False
    idle_seconds: int = 300
    upload_seconds: int = 30
    upload_on_app_change: bool = False
    battery_enabled: bool = True
    battery_seconds: int = 300
    upload_on_shutdown: bool = True
    upload_on_suspend: bool = True
    app_aliases: dict = field(default_factory=dict)
    app_colors: dict = field(default_factory=dict)
    theme: str = "system"
    fallback_host: str = ""
    fallback_port: int = 8080
    fallback_protocol: str = "http"
    preferred_endpoint: str = field(default="", repr=False, compare=False)

    @property
    def base_url(self):
        return self.endpoint_url(self.host, self.port, self.protocol)

    @staticmethod
    def endpoint_url(host, port, protocol):
        host = host.strip().strip("[]")
        return f"{protocol}://{'[' + host + ']' if ':' in host else host}:{port}"

    @property
    def base_urls(self):
        urls = [self.base_url]
        if self.fallback_host.strip():
            fallback = self.endpoint_url(self.fallback_host, self.fallback_port, self.fallback_protocol)
            if fallback not in urls:
                urls.append(fallback)
        return tuple(urls)

    @property
    def connection_urls(self):
        urls = self.base_urls
        if self.preferred_endpoint in urls:
            return (self.preferred_endpoint,) + tuple(url for url in urls if url != self.preferred_endpoint)
        return urls

    @property
    def active_url(self):
        return self.connection_urls[0]

    @property
    def destination(self):
        return hashlib.sha256(f"{self.base_url}|{self.account_id}".encode()).hexdigest()

    @property
    def configured(self):
        return bool(self.host and self.api_key and self.account_id)

    @property
    def status_enabled(self):
        """Device-status records (battery and startup/shutdown/sleep/resume) are produced at all."""
        return self.battery_enabled or self.upload_on_shutdown or self.upload_on_suspend

    def bind_account(self, account_id, username, device_id=None):
        from dataclasses import replace
        bound = replace(self, account_id=account_id, username=username, device_ids=dict(self.device_ids))
        bound.device_id = device_id or bound.device_ids.get(bound.destination) or (
            self.device_id if not self.device_ids and self.account_id == account_id else str(uuid.uuid4()))
        uuid.UUID(bound.device_id)
        bound.device_ids[bound.destination] = bound.device_id
        return bound

    def validate_endpoint(self):
        self.host = self.validate_address(self.host, self.port, self.protocol)
        self.fallback_host = self.fallback_host.strip()
        if self.fallback_host:
            try:
                self.fallback_host = self.validate_address(
                    self.fallback_host, self.fallback_port, self.fallback_protocol)
            except ValueError as exc:
                raise ValueError("备用地址：" + str(exc)) from None

    @staticmethod
    def validate_address(host, port, protocol):
        host = host.strip().strip("[]")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?", host):
                raise ValueError("服务器地址须为 IP 或域名，请勿包含协议、端口或路径")
        if not 1 <= port <= 65535 or protocol not in {"http", "https"}:
            raise ValueError("端口须为 1–65535，协议须为 HTTP 或 HTTPS")
        return host

    def validate(self):
        self.validate_endpoint()
        if self.theme not in ("system", "light", "dark"):
            raise ValueError("主题须为跟随系统、浅色或深色")
        if not 32 <= len(self.api_key) <= 256 or any(c.isspace() for c in self.api_key):
            raise ValueError("请填写网页中生成的完整上传密钥")
        if not 1 <= len(self.device_name.strip()) <= 100:
            raise ValueError("设备名称须为 1–100 个字符")
        self.device_name = self.device_name.strip()
        if not 0 <= self.idle_seconds <= 3600 or not 10 <= self.upload_seconds <= 300:
            raise ValueError("空闲阈值须为 0–3600 秒，上传间隔须为 10–300 秒")
        if not isinstance(self.upload_on_app_change, bool):
            raise ValueError("前台应用变化上传选项无效")
        if not isinstance(self.battery_enabled, bool) or not 30 <= self.battery_seconds <= 3600:
            raise ValueError("电池状态采集间隔须为 30–3600 秒")
        if not isinstance(self.upload_on_shutdown, bool) or not isinstance(self.upload_on_suspend, bool):
            raise ValueError("关机和休眠上传选项无效")
        if not isinstance(self.app_aliases, dict) or len(self.app_aliases) > 500:
            raise ValueError("应用名翻译最多支持 500 条")
        aliases = {}
        for process, display_name in self.app_aliases.items():
            if not isinstance(process, str) or not isinstance(display_name, str):
                raise ValueError("应用名翻译必须使用文本键和值")
            # A pasted full path is reduced to the file name, which is what the reader matches.
            process = process.strip().replace("/", "\\").rsplit("\\", 1)[-1].casefold()
            display_name = display_name.strip()
            if not 1 <= len(process) <= 200 or not 1 <= len(display_name) <= 200:
                raise ValueError("应用名翻译的进程名和显示名须为 1–200 个字符")
            aliases[process] = display_name
        self.app_aliases = aliases
        from .app_colors import normalize_colors
        self.app_colors = normalize_colors(self.app_colors)
        uuid.UUID(self.device_id)
        if not isinstance(self.device_ids, dict):
            raise ValueError("设备身份配置无效")
        for destination, identity in self.device_ids.items():
            if not isinstance(destination, str) or not re.fullmatch(r"[0-9a-f]{64}", destination):
                raise ValueError("设备身份配置无效")
            uuid.UUID(identity)


def data_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "FocusLedger"


def load_config(path, decrypt):
    if not path.exists():
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))
    encrypted = raw.pop("protected_api_key", "")
    allowed = Config.__dataclass_fields__.keys()
    config = Config(**{k: v for k, v in raw.items() if k in allowed and k not in {"api_key", "preferred_endpoint"}})
    if config.theme not in ("system", "light", "dark"):
        config.theme = "system"
    try:
        config.api_key = decrypt(encrypted) if encrypted else ""
    except (OSError, ValueError):
        # DPAPI data from another Windows account or machine: keep the other settings and ask for the key again.
        logging.exception("Stored upload key cannot be decrypted")
        config.api_key = ""
    if config.configured:
        config.validate()
    if config.host and config.account_id:
        config.device_ids[config.destination] = config.device_id
    return config


def save_config(path, config, encrypt):
    raw = asdict(config)
    raw.pop("preferred_endpoint")  # The last reachable route is only a hint for this process.
    key = raw.pop("api_key")
    raw["protected_api_key"] = encrypt(key) if key else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
