from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Device(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")
    agent_version: str = Field(min_length=1, max_length=40)


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


class Batch(StrictModel):
    schema_version: Literal[1] = 1
    device: Device
    events: list[BatchEvent] = Field(max_length=500)
