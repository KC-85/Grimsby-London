from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Basic backend health response."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str


class RollingStockSummary(BaseModel):
    """Resolved train type and formation for a service."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    family: str | None = None
    cars: int | None = None
    length_metres: float | None = None
    seats: int | None = None
    maximum_speed_mph: int | None = None
    traction: str | None = None
    coupling: str | None = None


class ServiceSummary(BaseModel):
    """One train service in an operating day."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    service_label: str
    operator: str
    timetable_type: str
    route_id: str
    route: str
    direction: str
    origin: str
    destination: str
    first_departure: str | None = None
    final_arrival: str | None = None
    status: str
    delay_minutes: int
    service_days: list[str]
    footnote_codes: list[str]
    rolling_stock: RollingStockSummary | None = None


class StopTimeRow(BaseModel):
    """One station call in a simulated timetable."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    service_label: str
    operator: str
    timetable_type: str
    route_id: str
    route: str
    direction: str
    origin: str
    destination: str
    service_days: list[str]
    station_id: str
    station: str
    stop_index: int
    arrival: str | None = None
    departure: str | None = None
    status: str
    delay_minutes: int
    footnote_codes: list[str]
    rolling_stock: RollingStockSummary | None = None


class ConflictRow(BaseModel):
    """One detected route section conflict."""

    model_config = ConfigDict(extra="forbid")

    section: str
    first_service_id: str
    first_service: str
    first_operator: str
    first_train: str | None = None
    first_cars: int | None = None
    second_service_id: str
    second_service: str
    second_operator: str
    second_train: str | None = None
    second_cars: int | None = None
    service_days: list[str]
    overlap_start: str
    overlap_end: str
    overlap_minutes: int


class OccupationRow(BaseModel):
    """One train occupying one route section during a time window."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    service_label: str
    operator: str
    route_id: str
    route: str
    section_id: str
    section: str
    from_station: str
    to_station: str
    track_layout: str
    directional_capacity: int
    enter: str
    exit: str
    enter_minutes: int
    exit_minutes: int
    duration_minutes: int
    service_days: list[str]
    status: str
    delay_minutes: int
    rolling_stock: RollingStockSummary | None = None


class DailyMetrics(BaseModel):
    """Headline metrics for one operating day."""

    model_config = ConfigDict(extra="forbid")

    services: int
    proposed_services: int
    active_services: int
    delayed_services: int
    cancelled_services: int
    operators: int
    routes: int
    known_seats: int
    unknown_capacity_services: int
    section_occupations: int
    conflicts: int
    conflict_minutes: int


class DaySimulationResponse(BaseModel):
    """Simulation payload for one operating day."""

    model_config = ConfigDict(extra="forbid")

    day: str
    include_proposal: bool
    metrics: DailyMetrics
    services: list[ServiceSummary]
    timetable: list[StopTimeRow]
    conflicts: list[ConflictRow]
    occupations: list[OccupationRow]
    warnings: list[str]


class WeekSimulationResponse(BaseModel):
    """Simulation payload for Monday-to-Sunday operations."""

    model_config = ConfigDict(extra="forbid")

    include_proposal: bool
    days: list[DaySimulationResponse]
    warnings: list[str]
