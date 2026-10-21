from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator

class CityEvent(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: Literal[1]=1
    event_id: str=Field(default_factory=lambda:str(uuid4()))
    timestamp_utc: datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
    simulation_time: float=Field(ge=0)
    source: str
    zone_id: str|None=None
    asset_id: str
    event_type: str
    severity: Literal["info","warning","critical"]="info"
    correlation_id: str|None=None
    payload: dict[str,Any]=Field(default_factory=dict)
    @field_validator("timestamp_utc")
    @classmethod
    def utc_time(cls, value): return value.astimezone(timezone.utc)

class Command(BaseModel):
    command_id: str=Field(default_factory=lambda:str(uuid4()))
    action: Literal["inject_fault","restore_fault","stop"]
    fault_type: str|None=None
    asset_id: str|None=None
