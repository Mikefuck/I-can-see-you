from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .app_colors import COLOR_IDS, process_key


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Device(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")
    agent_version: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def device_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("设备名称不能为空")
        return value


class UsageEvent(StrictModel):
    id: UUID
    kind: Literal["app_usage"] = "app_usage"
    app_name: str = Field(min_length=1, max_length=200)
    process_name: str = Field(min_length=1, max_length=200)
    started_at: datetime
    ended_at: datetime
    duration_seconds: float = Field(gt=0, le=600, allow_inf_nan=False)

    @field_validator("started_at", "ended_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def valid_span(self):
        span = (self.ended_at - self.started_at).total_seconds()
        if span <= 0 or span > 600 or abs(span - self.duration_seconds) > 0.01:
            raise ValueError("Duration must match the positive time span (at most 600 seconds)")
        return self


class DeviceStatusEvent(StrictModel):
    id: UUID
    kind: Literal["device_status"] = "device_status"
    occurred_at: datetime
    reason: Literal["periodic", "shutdown", "suspend", "resume", "startup"]
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    charging: bool | None = None
    ac_online: bool | None = None
    battery_life_seconds: int | None = Field(default=None, ge=0)

    @field_validator("occurred_at")
    @classmethod
    def status_timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value


BatchEvent = Annotated[Union[UsageEvent, DeviceStatusEvent], Field(discriminator="kind")]


class ForegroundApplication(StrictModel):
    app_name: str = Field(min_length=1, max_length=200)
    process_name: str = Field(min_length=1, max_length=200)


class Foreground(StrictModel):
    observed_at: datetime
    since: datetime
    app: ForegroundApplication | None

    @field_validator("observed_at", "since")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def valid_span(self):
        if self.since > self.observed_at:
            raise ValueError("Foreground start must not follow its observation")
        return self


class MusicTrack(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    artist: str = Field(default="", max_length=300)
    album: str = Field(default="", max_length=300)
    app_name: str = Field(min_length=1, max_length=200)
    process_name: str = Field(min_length=1, max_length=200)
    state: Literal["playing", "paused"]

    @field_validator("title", "artist", "album", "app_name", "process_name")
    @classmethod
    def clean_text(cls, value, info):
        value = value.strip()
        if info.field_name in {"title", "app_name", "process_name"} and not value:
            raise ValueError("Music title and player must not be blank")
        return value


class Music(StrictModel):
    observed_at: datetime
    track: MusicTrack | None

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value


class Batch(StrictModel):
    schema_version: Literal[1] = 1
    device: Device
    events: list[BatchEvent] = Field(max_length=500)
    foreground: Foreground | None = None
    music: Music | None = None


class AppAliases(StrictModel):
    device: Device
    app_aliases: dict[str, str] = Field(max_length=500)

    @field_validator("app_aliases")
    @classmethod
    def valid_aliases(cls, value):
        result = {}
        for process, name in value.items():
            key = process.strip().replace("/", "\\").rsplit("\\", 1)[-1].casefold()
            name = name.strip()
            if not 1 <= len(key) <= 200 or not 1 <= len(name) <= 200:
                raise ValueError("进程名和显示名须为 1–200 个字符")
            if key in result:
                raise ValueError("进程名重复")
            result[key] = name
        return result


class AppColors(StrictModel):
    device: Device
    app_colors: dict[str, str] = Field(max_length=500)

    @field_validator("app_colors")
    @classmethod
    def valid_colors(cls, value):
        result = {}
        for process, color in value.items():
            key = process_key(process)
            if not 1 <= len(key) <= 200 or color not in COLOR_IDS:
                raise ValueError("程序颜色须使用预设配色，进程名须为 1–200 个字符")
            if key in result:
                raise ValueError("进程名重复")
            result[key] = color
        return result
