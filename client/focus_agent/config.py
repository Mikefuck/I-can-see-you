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
    device_name: str = field(default_factory=socket.gethostname)
    startup: bool = False
    silent_start: bool = False
    idle_seconds: int = 300
    upload_seconds: int = 30
    battery_enabled: bool = True
    battery_seconds: int = 300
    upload_on_shutdown: bool = True
    upload_on_suspend: bool = True
    app_aliases: dict = field(default_factory=dict)

    @property
    def base_url(self):
        host = self.host.strip().strip("[]")
        return f"{self.protocol}://{'[' + host + ']' if ':' in host else host}:{self.port}"

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

    def validate(self):
        self.host = self.host.strip().strip("[]")
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?", self.host):
                raise ValueError("服务器地址须为 IP 或域名，请勿包含协议、端口或路径")
        if not 1 <= self.port <= 65535 or self.protocol not in {"http", "https"}:
            raise ValueError("端口须为 1–65535，协议须为 HTTP 或 HTTPS")
        if not 32 <= len(self.api_key) <= 256 or any(c.isspace() for c in self.api_key):
            raise ValueError("请填写网页中生成的完整上传密钥")
        if not 1 <= len(self.device_name.strip()) <= 100:
            raise ValueError("设备名称须为 1–100 个字符")
        self.device_name = self.device_name.strip()
        if not 0 <= self.idle_seconds <= 3600 or not 10 <= self.upload_seconds <= 300:
            raise ValueError("空闲阈值须为 0–3600 秒，上传间隔须为 10–300 秒")
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
        uuid.UUID(self.device_id)


def data_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "FocusLedger"


def load_config(path, decrypt):
    if not path.exists():
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))
    encrypted = raw.pop("protected_api_key", "")
    allowed = Config.__dataclass_fields__.keys()
    config = Config(**{k: v for k, v in raw.items() if k in allowed and k != "api_key"})
    try:
        config.api_key = decrypt(encrypted) if encrypted else ""
    except (OSError, ValueError):
        # DPAPI data from another Windows account or machine: keep the other settings and ask for the key again.
        logging.exception("Stored upload key cannot be decrypted")
        config.api_key = ""
    if config.configured:
        config.validate()
    return config


def save_config(path, config, encrypt):
    raw = asdict(config)
    key = raw.pop("api_key")
    raw["protected_api_key"] = encrypt(key) if key else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
