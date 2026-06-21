from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_SERVICES_PATH = Path("data/services.json")
TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class Stop(BaseModel):
    """A scheduled call within a rail service."""

    model_config = ConfigDict(extra="forbid")

    station_id: str
    arrival: str | None = None
    departure: str | None = None
    arrival_day_offset: int = 0
    departure_day_offset: int = 0

    @field_validator("arrival", "departure")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is not None and not TIME_PATTERN.match(value):
            raise ValueError("time must use HH:MM 24-hour format")
        return value

    @model_validator(mode="after")
    def validate_has_time(self) -> Stop:
        if self.arrival is None and self.departure is None:
            raise ValueError("a stop must have an arrival, departure, or both")
        return self


class Service(BaseModel):
    """A scheduled train service from services.json."""

    model_config = ConfigDict(extra="forbid")

    id: str
    operator: str
    route_id: str
    source_id: str
    direction: str
    service_days: list[str]
    footnote_codes: list[str] = Field(default_factory=list)
    origin: str
    destination: str
    stops: list[Stop]

    @model_validator(mode="after")
    def validate_stops(self) -> Service:
        if len(self.stops) < 2:
            raise ValueError("a service must have at least two stops")
        if self.stops[0].station_id != self.origin:
            raise ValueError("first stop must match service origin")
        if self.stops[-1].station_id != self.destination:
            raise ValueError("last stop must match service destination")
        return self

    @property
    def first_departure(self) -> str | None:
        return self.stops[0].departure

    @property
    def final_arrival(self) -> str | None:
        return self.stops[-1].arrival


class ServicesFile(BaseModel):
    """Top-level structure for data/services.json."""

    model_config = ConfigDict(extra="forbid")

    services: list[Service]


def load_services(path: Path | str = DEFAULT_SERVICES_PATH) -> list[Service]:
    """Load and validate services from a services JSON file."""

    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return ServicesFile.model_validate(data).services


def services_by_direction(services: list[Service], direction: str) -> list[Service]:
    """Return services matching a direction ID."""

    return [service for service in services if service.direction == direction]


def services_for_day(services: list[Service], day: str) -> list[Service]:
    """Return services that run on a given lowercase day name."""

    return [service for service in services if day in service.service_days]


def flatten_services(services: list[Service]) -> list[dict[str, str | int | None]]:
    """Convert services into stop-level rows for tables and charts."""

    rows: list[dict[str, str | int | None]] = []
    for service in services:
        for stop_index, stop in enumerate(service.stops):
            rows.append(
                {
                    "service_id": service.id,
                    "operator": service.operator,
                    "route_id": service.route_id,
                    "direction": service.direction,
                    "source_id": service.source_id,
                    "origin": service.origin,
                    "destination": service.destination,
                    "service_days": ", ".join(service.service_days),
                    "footnote_codes": ", ".join(service.footnote_codes),
                    "stop_index": stop_index,
                    "station_id": stop.station_id,
                    "arrival": stop.arrival,
                    "departure": stop.departure,
                    "arrival_day_offset": stop.arrival_day_offset,
                    "departure_day_offset": stop.departure_day_offset,
                }
            )
    return rows
