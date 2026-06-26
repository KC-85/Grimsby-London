from __future__ import annotations

from functools import lru_cache

from backend.schemas import (
    ConflictRow,
    DailyMetrics,
    DaySimulationResponse,
    OccupationRow,
    RollingStockSummary,
    ServiceSummary,
    StopTimeRow,
    WeekSimulationResponse,
)
from simulation.disruption import Disruption
from simulation.engine import SimulationResult, run_simulation
from simulation.infrastructure import (
    InfrastructureData,
    Route,
    Station,
    load_infrastructure,
    route_lookup,
    station_lookup,
)
from simulation.timetable import Service, load_services
from simulation.train import (
    RollingStock,
    ServiceRollingStock,
    load_rolling_stock,
    resolve_service_rolling_stock,
)


DAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


@lru_cache(maxsize=1)
def load_simulation_data() -> tuple[
    InfrastructureData,
    list[Service],
    list[Service],
    list[RollingStock],
]:
    """Load validated JSON data for the API service layer."""

    infrastructure = load_infrastructure()
    baseline_services = load_services()
    proposed_services = load_services("data/proposed_services.json")
    rolling_stock = load_rolling_stock()
    return infrastructure, baseline_services, proposed_services, rolling_stock


def selected_services(
    baseline_services: list[Service],
    proposed_services: list[Service],
    *,
    include_proposal: bool,
) -> list[Service]:
    """Return the service set requested by the API call."""

    return [
        *baseline_services,
        *(proposed_services if include_proposal else []),
    ]


def service_label(service: Service) -> str:
    """Return the display label used for a service."""

    return service.first_departure or service.id


def timetable_type(service: Service) -> str:
    """Return whether a service is current or proposed."""

    return "Proposed" if "PROPOSED" in service.footnote_codes else "Current"


def station_name(station_id: str, stations_by_id: dict[str, Station]) -> str:
    """Return a station name, falling back to the ID if needed."""

    station = stations_by_id.get(station_id)
    return station.name if station else station_id


def route_name(route_id: str, routes_by_id: dict[str, Route]) -> str:
    """Return a route name, falling back to the ID if needed."""

    route = routes_by_id.get(route_id)
    return route.name if route else route_id


def section_label(section_key: str, stations_by_id: dict[str, Station]) -> str:
    """Return a human-readable label for a physical section key."""

    return " to ".join(
        station_name(station_id, stations_by_id)
        for station_id in section_key.split("::")
    )


def rolling_stock_summary(
    resolved_stock: ServiceRollingStock | None,
) -> RollingStockSummary | None:
    """Return a frontend-safe summary of resolved rolling stock."""

    if resolved_stock is None:
        return None

    stock = resolved_stock.rolling_stock
    formation = resolved_stock.formation
    return RollingStockSummary(
        id=stock.id,
        name=stock.name,
        family=stock.family,
        cars=formation.cars,
        length_metres=formation.length_metres,
        seats=formation.seats,
        maximum_speed_mph=stock.traction.maximum_speed_mph,
        traction=stock.traction.type,
        coupling=stock.coupling.type,
    )


def build_service_rows(
    result: SimulationResult,
    routes_by_id: dict[str, Route],
    stations_by_id: dict[str, Station],
    rolling_stock_by_service: dict[str, ServiceRollingStock],
) -> list[ServiceSummary]:
    """Build one API row per simulated service."""

    rows: list[ServiceSummary] = []
    for simulated in result.services:
        service = simulated.service
        rows.append(
            ServiceSummary(
                service_id=service.id,
                service_label=service_label(service),
                operator=service.operator,
                timetable_type=timetable_type(service),
                route_id=service.route_id,
                route=route_name(service.route_id, routes_by_id),
                direction=service.direction,
                origin=station_name(service.origin, stations_by_id),
                destination=station_name(service.destination, stations_by_id),
                first_departure=service.first_departure,
                final_arrival=service.final_arrival,
                status=simulated.status.value,
                delay_minutes=simulated.delay_minutes,
                service_days=service.service_days,
                footnote_codes=service.footnote_codes,
                rolling_stock=rolling_stock_summary(
                    rolling_stock_by_service.get(service.id)
                ),
            )
        )
    return rows


def build_timetable_rows(
    result: SimulationResult,
    routes_by_id: dict[str, Route],
    stations_by_id: dict[str, Station],
    rolling_stock_by_service: dict[str, ServiceRollingStock],
) -> list[StopTimeRow]:
    """Build stop-level API timetable rows."""

    rows: list[StopTimeRow] = []
    for simulated in result.services:
        service = simulated.service
        for stop_index, stop in enumerate(service.stops):
            rows.append(
                StopTimeRow(
                    service_id=service.id,
                    service_label=service_label(service),
                    operator=service.operator,
                    timetable_type=timetable_type(service),
                    route_id=service.route_id,
                    route=route_name(service.route_id, routes_by_id),
                    direction=service.direction,
                    origin=station_name(service.origin, stations_by_id),
                    destination=station_name(service.destination, stations_by_id),
                    service_days=service.service_days,
                    station_id=stop.station_id,
                    station=station_name(stop.station_id, stations_by_id),
                    stop_index=stop_index,
                    arrival=stop.arrival,
                    departure=stop.departure,
                    status=simulated.status.value,
                    delay_minutes=simulated.delay_minutes,
                    footnote_codes=service.footnote_codes,
                    rolling_stock=rolling_stock_summary(
                        rolling_stock_by_service.get(service.id)
                    ),
                )
            )
    return rows


def build_conflict_rows(
    result: SimulationResult,
    stations_by_id: dict[str, Station],
    rolling_stock_by_service: dict[str, ServiceRollingStock],
) -> list[ConflictRow]:
    """Build API rows for detected section conflicts."""

    services_by_id = {
        simulated.service.id: simulated.service
        for simulated in result.services
    }
    rows: list[ConflictRow] = []

    for conflict in result.conflicts:
        first_service = services_by_id[conflict.first_service_id]
        second_service = services_by_id[conflict.second_service_id]
        first_stock = rolling_stock_by_service.get(conflict.first_service_id)
        second_stock = rolling_stock_by_service.get(conflict.second_service_id)

        rows.append(
            ConflictRow(
                section=section_label(conflict.section_key, stations_by_id),
                first_service_id=first_service.id,
                first_service=service_label(first_service),
                first_operator=first_service.operator,
                first_train=first_stock.rolling_stock.name if first_stock else None,
                first_cars=first_stock.cars if first_stock else None,
                second_service_id=second_service.id,
                second_service=service_label(second_service),
                second_operator=second_service.operator,
                second_train=second_stock.rolling_stock.name if second_stock else None,
                second_cars=second_stock.cars if second_stock else None,
                service_days=conflict.service_days,
                overlap_start=conflict.overlap_start,
                overlap_end=conflict.overlap_end,
                overlap_minutes=conflict.overlap_minutes,
            )
        )

    return rows


def build_occupation_rows(
    result: SimulationResult,
    routes_by_id: dict[str, Route],
    stations_by_id: dict[str, Station],
    rolling_stock_by_service: dict[str, ServiceRollingStock],
) -> list[OccupationRow]:
    """Build API rows for route section occupations."""

    services_by_id = {
        simulated.service.id: simulated.service
        for simulated in result.services
    }
    rows: list[OccupationRow] = []

    for occupation in result.occupations:
        service = services_by_id[occupation.service_id]
        rows.append(
            OccupationRow(
                service_id=occupation.service_id,
                service_label=service_label(service),
                operator=occupation.operator,
                route_id=occupation.route_id,
                route=route_name(occupation.route_id, routes_by_id),
                section_id=occupation.section_id,
                section=section_label(occupation.section_key, stations_by_id),
                from_station=station_name(occupation.from_station, stations_by_id),
                to_station=station_name(occupation.to_station, stations_by_id),
                track_layout=occupation.capacity_model.value,
                directional_capacity=occupation.directional_capacity,
                enter=occupation.enter_time,
                exit=occupation.exit_time,
                enter_minutes=occupation.enter_time_minutes,
                exit_minutes=occupation.exit_time_minutes,
                duration_minutes=occupation.duration_minutes,
                service_days=occupation.service_days,
                status=occupation.status.value,
                delay_minutes=occupation.delay_minutes,
                rolling_stock=rolling_stock_summary(
                    rolling_stock_by_service.get(occupation.service_id)
                ),
            )
        )

    return rows


def rows_for_day(rows, day: str):
    """Return rows that operate on the requested day."""

    return [row for row in rows if day in row.service_days]


def daily_metrics(
    services: list[ServiceSummary],
    conflicts: list[ConflictRow],
    occupations: list[OccupationRow],
) -> DailyMetrics:
    """Calculate metrics for one operating day."""

    active_services = [
        service
        for service in services
        if service.status != "cancelled"
    ]
    known_seats = sum(
        service.rolling_stock.seats or 0
        for service in active_services
        if service.rolling_stock is not None
    )
    unknown_capacity_services = sum(
        1
        for service in active_services
        if service.rolling_stock is None or service.rolling_stock.seats is None
    )

    return DailyMetrics(
        services=len(services),
        proposed_services=sum(
            1
            for service in services
            if service.timetable_type == "Proposed"
        ),
        active_services=len(active_services),
        delayed_services=sum(1 for service in services if service.status == "delayed"),
        cancelled_services=sum(1 for service in services if service.status == "cancelled"),
        operators=len({service.operator for service in services}),
        routes=len({service.route for service in services}),
        known_seats=known_seats,
        unknown_capacity_services=unknown_capacity_services,
        section_occupations=len(occupations),
        conflicts=len(conflicts),
        conflict_minutes=sum(conflict.overlap_minutes for conflict in conflicts),
    )


def run_backend_simulation(
    *,
    include_proposal: bool = True,
    disruptions: list[Disruption] | None = None,
) -> tuple[InfrastructureData, SimulationResult, dict[str, ServiceRollingStock], list[str]]:
    """Run the simulation and resolve rolling stock for API consumers."""

    infrastructure, baseline_services, proposed_services, rolling_stock = load_simulation_data()
    services = selected_services(
        baseline_services,
        proposed_services,
        include_proposal=include_proposal,
    )
    result = run_simulation(services, infrastructure, disruptions or [])
    simulated_services = [
        simulated.service
        for simulated in result.services
    ]
    rolling_stock_by_service, rolling_stock_warnings = resolve_service_rolling_stock(
        simulated_services,
        rolling_stock,
    )

    return infrastructure, result, rolling_stock_by_service, rolling_stock_warnings


def get_day_simulation(
    day: str,
    *,
    include_proposal: bool = True,
    disruptions: list[Disruption] | None = None,
) -> DaySimulationResponse:
    """Return simulated services, timetable rows, conflicts, and occupations for one day."""

    infrastructure, result, rolling_stock_by_service, rolling_stock_warnings = run_backend_simulation(
        include_proposal=include_proposal,
        disruptions=disruptions,
    )
    routes_by_id = route_lookup(infrastructure.routes)
    stations_by_id = station_lookup(infrastructure.stations)

    services = rows_for_day(
        build_service_rows(result, routes_by_id, stations_by_id, rolling_stock_by_service),
        day,
    )
    timetable = rows_for_day(
        build_timetable_rows(result, routes_by_id, stations_by_id, rolling_stock_by_service),
        day,
    )
    conflicts = [
        conflict
        for conflict in build_conflict_rows(result, stations_by_id, rolling_stock_by_service)
        if day in conflict.service_days
    ]
    occupations = rows_for_day(
        build_occupation_rows(result, routes_by_id, stations_by_id, rolling_stock_by_service),
        day,
    )

    return DaySimulationResponse(
        day=day,
        include_proposal=include_proposal,
        metrics=daily_metrics(services, conflicts, occupations),
        services=sorted(services, key=lambda row: (row.service_label, row.operator, row.route)),
        timetable=sorted(
            timetable,
            key=lambda row: (row.service_label, row.operator, row.route, row.stop_index),
        ),
        conflicts=sorted(
            conflicts,
            key=lambda row: (
                row.overlap_start,
                row.section,
                row.first_service,
                row.second_service,
            ),
        ),
        occupations=sorted(
            occupations,
            key=lambda row: (row.enter_minutes, row.section, row.service_label),
        ),
        warnings=[*result.warnings, *rolling_stock_warnings],
    )


def get_week_simulation(
    *,
    include_proposal: bool = True,
) -> WeekSimulationResponse:
    """Return simulated services, conflicts, and occupations for every operating day."""

    days = [
        get_day_simulation(day, include_proposal=include_proposal)
        for day in DAYS
    ]
    warnings = sorted({warning for day in days for warning in day.warnings})

    return WeekSimulationResponse(
        include_proposal=include_proposal,
        days=days,
        warnings=warnings,
    )
