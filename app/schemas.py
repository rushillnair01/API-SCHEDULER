from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional
from datetime import datetime


# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------

class TargetBase(BaseModel):
    url: str
    method: str
    headers: dict = {}

    @field_validator("method")
    @classmethod
    def method_uppercase(cls, v: str) -> str:
        """Normalise HTTP method to uppercase so 'get' and 'GET' are equivalent."""
        return v.upper()

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("URL must not be empty")
        return v.strip()


class TargetCreate(TargetBase):
    pass


class Target(TargetBase):
    id: int
    # Pydantic v2 style (replaces inner class Config with from_attributes=True)
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

class ScheduleBase(BaseModel):
    target_id: int
    interval_seconds: int
    duration_seconds: Optional[int] = None

    @field_validator("interval_seconds")
    @classmethod
    def interval_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval_seconds must be at least 1")
        return v

    @field_validator("duration_seconds")
    @classmethod
    def duration_positive_or_none(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("duration_seconds must be at least 1 when provided")
        return v


class ScheduleCreate(ScheduleBase):
    pass


class Schedule(ScheduleBase):
    id: int
    next_run_at: datetime
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class Run(BaseModel):
    id: int
    schedule_id: int
    status: str
    scheduled_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    response_code: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)