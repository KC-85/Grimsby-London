from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Basic backend health response."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str


class DaySimulationResponse(BaseModel):
    """First-pass response for one simulated operating day."""

    model_config = ConfigDict(extra="forbid")

    day: str
    include_proposal: bool
    status: str


class WeekSimulationResponse(BaseModel):
    """First-pass response for the Monday-to-Sunday simulation view."""

    model_config = ConfigDict(extra="forbid")

    include_proposal: bool
    days: list[DaySimulationResponse]
