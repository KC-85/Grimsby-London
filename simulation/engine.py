from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from simulation.disruption import (
    Disruption,
    DisruptionApplication,
    ServiceStatus,
    SimulatedService,
    apply_disruptions,
    minutes_from_time,
    time_from_minutes,
)
from simulation.infrastructure import CapacityModel, InfrastructureData, Route, route_lookup
from simulation.timetable import Service, Stop


class SectionOccupation(BaseModel):
    """A simulated service occupying a route section during a time window."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    operator: str
    route_id: str
    direction: str
    service_days: list[str]
    section_id: str
    section_key: str
    from_station: str
    to_station: str
    capacity_model: CapacityModel
    directional_capacity: int
    enter_time_minutes: int
    exit_time_minutes: int
    status: ServiceStatus
    delay_minutes: int = 0

    @property
    def enter_time(self) -> str:
        value, _ = time_from_minutes(self.enter_time_minutes)
        return value

    @property
    def exit_time(self) -> str:
        value, _ = time_from_minutes(self.exit_time_minutes)
        return value

    @property
    def duration_minutes(self) -> int:
        return self.exit_time_minutes - self.enter_time_minutes


class SectionConflict(BaseModel):
    """A simple overlap conflict on the same route section."""

    model_config = ConfigDict(extra="forbid")

    section_key: str
    first_service_id: str
    second_service_id: str
    service_days: list[str]
    overlap_start_minutes: int
    overlap_end_minutes: int
    overlap_minutes: int

    @property
    def overlap_start(self) -> str:
        value, _ = time_from_minutes(self.overlap_start_minutes)
        return value

    @property
    def overlap_end(self) -> str:
        value, _ = time_from_minutes(self.overlap_end_minutes)
        return value


class SimulationResult(BaseModel):
    """Output from a simulation run."""

    model_config = ConfigDict(extra="forbid")

    services: list[SimulatedService]
    occupations: list[SectionOccupation] = Field(default_factory=list)
    conflicts: list[SectionConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def active_services(self) -> list[SimulatedService]:
        return [service for service in self.services if service.status != ServiceStatus.CANCELLED]

    @property
    def cancelled_services(self) -> list[SimulatedService]:
        return [service for service in self.services if service.status == ServiceStatus.CANCELLED]


def section_key(from_station: str, to_station: str) -> str:
    """Return an undirected key for a physical route section."""

    return "::".join(sorted((from_station, to_station)))


def stop_departure_minutes(stop: Stop) -> int | None:
    """Return the best available departure-side time for a stop."""

    if stop.departure is not None:
        return minutes_from_time(stop.departure, stop.departure_day_offset)
    if stop.arrival is not None:
        return minutes_from_time(stop.arrival, stop.arrival_day_offset)
    return None


def stop_arrival_minutes(stop: Stop) -> int | None:
    """Return the best available arrival-side time for a stop."""

    if stop.arrival is not None:
        return minutes_from_time(stop.arrival, stop.arrival_day_offset)
    if stop.departure is not None:
        return minutes_from_time(stop.departure, stop.departure_day_offset)
    return None


def route_sections_between(route: Route, from_station: str, to_station: str):
    """Return route sections between two stations in route order."""

    station_sequence = route.core_station_sequence
    if from_station not in station_sequence or to_station not in station_sequence:
        return []

    from_index = station_sequence.index(from_station)
    to_index = station_sequence.index(to_station)
    if from_index >= to_index:
        return []

    return route.sections[from_index:to_index]


def distribute_section_times(
    start_minutes: int,
    end_minutes: int,
    sections,
) -> list[tuple[int, int]]:
    """Split a visible timing window across route sections."""

    total_duration = end_minutes - start_minutes
    total_scheduled_runtime = sum(section.scheduled_runtime_minutes for section in sections)

    if total_duration < 0:
        total_duration += 24 * 60

    if not sections:
        return []

    if total_scheduled_runtime <= 0:
        section_duration = max(1, round(total_duration / len(sections)))
        windows = []
        current = start_minutes
        for index, _section in enumerate(sections):
            if index == len(sections) - 1:
                next_time = end_minutes
            else:
                next_time = current + section_duration
            windows.append((current, next_time))
            current = next_time
        return windows

    windows = []
    current = start_minutes
    cumulative_runtime = 0
    for index, section in enumerate(sections):
        cumulative_runtime += section.scheduled_runtime_minutes
        if index == len(sections) - 1:
            next_time = end_minutes
        else:
            next_time = start_minutes + round(total_duration * cumulative_runtime / total_scheduled_runtime)
            next_time = max(current, next_time)
        windows.append((current, next_time))
        current = next_time

    return windows


def build_section_occupations(
    simulated_services: list[SimulatedService],
    infrastructure: InfrastructureData,
) -> tuple[list[SectionOccupation], list[str]]:
    """Create section occupation windows for active simulated services."""

    routes_by_id = route_lookup(infrastructure.routes)
    occupations: list[SectionOccupation] = []
    warnings: list[str] = []

    for simulated_service in simulated_services:
        if simulated_service.status == ServiceStatus.CANCELLED:
            continue

        service = simulated_service.service
        route = routes_by_id.get(service.route_id)
        if route is None:
            warnings.append(f"route {service.route_id} was not found for service {service.id}")
            continue

        for from_stop, to_stop in zip(service.stops, service.stops[1:]):
            start_minutes = stop_departure_minutes(from_stop)
            end_minutes = stop_arrival_minutes(to_stop)
            if start_minutes is None or end_minutes is None:
                warnings.append(f"service {service.id} has incomplete timing between {from_stop.station_id} and {to_stop.station_id}")
                continue

            sections = route_sections_between(route, from_stop.station_id, to_stop.station_id)
            if not sections:
                warnings.append(f"no route sections found for service {service.id} between {from_stop.station_id} and {to_stop.station_id}")
                continue

            section_windows = distribute_section_times(start_minutes, end_minutes, sections)
            for section, (enter_time, exit_time) in zip(sections, section_windows):
                occupations.append(
                    SectionOccupation(
                        service_id=service.id,
                        operator=service.operator,
                        route_id=service.route_id,
                        direction=service.direction,
                        service_days=service.service_days,
                        section_id=section.id,
                        section_key=section_key(section.from_station, section.to_station),
                        from_station=section.from_station,
                        to_station=section.to_station,
                        capacity_model=section.capacity_model,
                        directional_capacity=section.directional_capacity,
                        enter_time_minutes=enter_time,
                        exit_time_minutes=exit_time,
                        status=simulated_service.status,
                        delay_minutes=simulated_service.delay_minutes,
                    )
                )

    return occupations, warnings


def detect_section_conflicts(occupations: list[SectionOccupation]) -> list[SectionConflict]:
    """Detect overlapping movements on confirmed single-track sections."""

    occupations_by_section: dict[str, list[SectionOccupation]] = defaultdict(list)
    for occupation in occupations:
        if occupation.capacity_model != CapacityModel.SINGLE_TRACK:
            continue
        occupations_by_section[occupation.section_key].append(occupation)

    conflicts: list[SectionConflict] = []
    for section_occupations in occupations_by_section.values():
        section_days = sorted({day for occupation in section_occupations for day in occupation.service_days})
        for day in section_days:
            lane_occupations: dict[str, list[SectionOccupation]] = defaultdict(list)
            for occupation in section_occupations:
                if day not in occupation.service_days:
                    continue
                lane_occupations["shared"].append(occupation)

            for occupations_in_lane in lane_occupations.values():
                ordered = sorted(
                    occupations_in_lane,
                    key=lambda occupation: (occupation.enter_time_minutes, occupation.exit_time_minutes),
                )
                active: list[SectionOccupation] = []
                for occupation in ordered:
                    active = [
                        existing
                        for existing in active
                        if existing.exit_time_minutes > occupation.enter_time_minutes
                        and existing.service_id != occupation.service_id
                    ]

                    if len(active) >= occupation.directional_capacity:
                        blocking = max(active, key=lambda existing: existing.exit_time_minutes)
                        overlap_end = min(blocking.exit_time_minutes, occupation.exit_time_minutes)
                        if overlap_end > occupation.enter_time_minutes:
                            conflicts.append(
                                SectionConflict(
                                    section_key=occupation.section_key,
                                    first_service_id=blocking.service_id,
                                    second_service_id=occupation.service_id,
                                    service_days=[day],
                                    overlap_start_minutes=occupation.enter_time_minutes,
                                    overlap_end_minutes=overlap_end,
                                    overlap_minutes=overlap_end - occupation.enter_time_minutes,
                                )
                            )

                    active.append(occupation)

    merged_conflicts: dict[tuple, SectionConflict] = {}
    for conflict in conflicts:
        signature = (
            conflict.section_key,
            conflict.first_service_id,
            conflict.second_service_id,
            conflict.overlap_start_minutes,
            conflict.overlap_end_minutes,
        )
        existing = merged_conflicts.get(signature)
        if existing is None:
            merged_conflicts[signature] = conflict
            continue
        existing.service_days = sorted(set(existing.service_days + conflict.service_days))

    return list(merged_conflicts.values())


def run_simulation(
    services: list[Service],
    infrastructure: InfrastructureData,
    disruptions: list[Disruption] | None = None,
) -> SimulationResult:
    """Run the MVP simulation pipeline."""

    disruption_application: DisruptionApplication = apply_disruptions(services, disruptions or [])
    occupations, occupation_warnings = build_section_occupations(
        disruption_application.services,
        infrastructure,
    )
    conflicts = detect_section_conflicts(occupations)

    return SimulationResult(
        services=disruption_application.services,
        occupations=occupations,
        conflicts=conflicts,
        warnings=[
            *disruption_application.warnings,
            *occupation_warnings,
        ],
    )
