import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: Path
    retention_days: int = 365
    secure_cookies: bool = False
    admin_username: str = ""
    admin_password: str = ""

    def __post_init__(self):
        if not 1 <= self.retention_days <= 365:
            raise ValueError("RETENTION_DAYS must be between 1 and 365")

    @classmethod
    def from_env(cls):
        return cls(
            database=Path(os.getenv("DATA_DIR", "data")) / "focus.sqlite3",
            retention_days=int(os.getenv("RETENTION_DAYS", "365")),
            secure_cookies=os.getenv("SECURE_COOKIES", "false").lower() == "true",
            admin_username=os.getenv("ADMIN_USERNAME", ""),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
        )
