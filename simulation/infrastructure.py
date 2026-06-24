from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_STATIONS_PATH = Path("data/stations.json")
DEFAULT_ROUTES_PATH = Path("data/routes.json")


class Station(BaseModel):
    """A station that can appear in timetable or route data."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    crs: str | None = None
    tags: list[str] = Field(default_factory=list)


class StationsFile(BaseModel):
    """Top-level structure for data/stations.json."""

    model_config = ConfigDict(extra="forbid")

    stations: list[Station]

    @model_validator(mode="after")
    def validate_unique_station_ids(self) -> StationsFile:
        station_ids = [station.id for station in self.stations]
        duplicate_ids = sorted({station_id for station_id in station_ids if station_ids.count(station_id) > 1})
        if duplicate_ids:
            raise ValueError(f"duplicate station IDs: {', '.join(duplicate_ids)}")
        return self


class RouteEndpointPair(BaseModel):
    """A pair of station IDs marking a section or optional-call boundary."""

    model_config = ConfigDict(extra="forbid")

    from_station: str = Field(alias="from")
    to_station: str = Field(alias="to")


class CapacityModel(StrEnum):
    """Supported physical track layouts for a route section."""

    SINGLE_TRACK = "single_track"
    DOUBLE_TRACK = "double_track"
    FOUR_TRACK = "four_track"


class RouteSection(BaseModel):
    """A simplified route section used by the MVP simulation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    from_station: str = Field(alias="from")
    to_station: str = Field(alias="to")
    scheduled_runtime_minutes: int
    capacity_model: CapacityModel

    @model_validator(mode="after")
    def validate_runtime(self) -> RouteSection:
        if self.scheduled_runtime_minutes <= 0:
            raise ValueError("scheduled_runtime_minutes must be greater than zero")
        return self

    @property
    def directional_capacity(self) -> int:
        """Return simultaneous trains allowed in one direction."""

        if self.capacity_model == CapacityModel.FOUR_TRACK:
            return 2
        return 1


class OptionalCallGroup(BaseModel):
    """A group of extra calls activated by timetable footnotes."""

    model_config = ConfigDict(extra="forbid")

    id: str
    applies_to_footnotes: list[str]
    between: RouteEndpointPair
    station_sequence: list[str]


class Route(BaseModel):
    """A route definition from routes.json."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    operator_scope: list[str]
    source_ids: list[str]
    direction: str
    origin: str
    destination: str
    core_station_sequence: list[str]
    sections: list[RouteSection]
    optional_call_groups: list[OptionalCallGroup] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_route_shape(self) -> Route:
        if len(self.core_station_sequence) < 2:
            raise ValueError("core_station_sequence must contain at least two stations")
        if self.core_station_sequence[0] != self.origin:
            raise ValueError("first core station must match route origin")
        if self.core_station_sequence[-1] != self.destination:
            raise ValueError("last core station must match route destination")
        if len(self.sections) != len(self.core_station_sequence) - 1:
            raise ValueError("sections must connect each adjacent core station")

        for index, section in enumerate(self.sections):
            expected_from = self.core_station_sequence[index]
            expected_to = self.core_station_sequence[index + 1]
            if section.from_station != expected_from or section.to_station != expected_to:
                raise ValueError(f"section {section.id} does not match core station sequence")

        return self


class RoutesFile(BaseModel):
    """Top-level structure for data/routes.json."""

    model_config = ConfigDict(extra="forbid")

    routes: list[Route]

    @model_validator(mode="after")
    def validate_unique_route_ids(self) -> RoutesFile:
        route_ids = [route.id for route in self.routes]
        duplicate_ids = sorted({route_id for route_id in route_ids if route_ids.count(route_id) > 1})
        if duplicate_ids:
            raise ValueError(f"duplicate route IDs: {', '.join(duplicate_ids)}")
        return self


class InfrastructureData(BaseModel):
    """Validated stations and routes loaded together."""

    model_config = ConfigDict(extra="forbid")

    stations: list[Station]
    routes: list[Route]

    @property
    def station_ids(self) -> set[str]:
        return {station.id for station in self.stations}

    @property
    def route_ids(self) -> set[str]:
        return {route.id for route in self.routes}

    @model_validator(mode="after")
    def validate_route_station_references(self) -> InfrastructureData:
        station_ids = self.station_ids
        missing_references: list[str] = []
        capacity_by_section: dict[tuple[str, str], CapacityModel] = {}

        for route in self.routes:
            route_station_refs = [route.origin, route.destination]
            route_station_refs.extend(route.core_station_sequence)
            for section in route.sections:
                route_station_refs.extend([section.from_station, section.to_station])
            for call_group in route.optional_call_groups:
                route_station_refs.extend([call_group.between.from_station, call_group.between.to_station])
                route_station_refs.extend(call_group.station_sequence)

            for station_id in route_station_refs:
                if station_id not in station_ids:
                    missing_references.append(f"{route.id}:{station_id}")

            for section in route.sections:
                physical_section = tuple(sorted((section.from_station, section.to_station)))
                existing_capacity = capacity_by_section.setdefault(
                    physical_section,
                    section.capacity_model,
                )
                if existing_capacity != section.capacity_model:
                    raise ValueError(
                        f"inconsistent capacity model for {' to '.join(physical_section)}"
                    )

        if missing_references:
            raise ValueError(f"missing station references: {', '.join(sorted(set(missing_references)))}")

        return self


def load_stations(path: Path | str = DEFAULT_STATIONS_PATH) -> list[Station]:
    """Load and validate stations from a stations JSON file."""

    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return StationsFile.model_validate(data).stations


def load_routes(path: Path | str = DEFAULT_ROUTES_PATH) -> list[Route]:
    """Load and validate routes from a routes JSON file."""

    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return RoutesFile.model_validate(data).routes


def load_infrastructure(
    stations_path: Path | str = DEFAULT_STATIONS_PATH,
    routes_path: Path | str = DEFAULT_ROUTES_PATH,
) -> InfrastructureData:
    """Load and cross-validate station and route data."""

    return InfrastructureData(
        stations=load_stations(stations_path),
        routes=load_routes(routes_path),
    )


def station_lookup(stations: list[Station]) -> dict[str, Station]:
    """Return stations keyed by station ID."""

    return {station.id: station for station in stations}


def route_lookup(routes: list[Route]) -> dict[str, Route]:
    """Return routes keyed by route ID."""

    return {route.id: route for route in routes}
