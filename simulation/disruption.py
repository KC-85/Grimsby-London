from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from simulation.timetable import Service, Stop


MINUTES_PER_DAY = 24 * 60


class DisruptionType(StrEnum):
    """Supported MVP disruption actions."""

    SERVICE_DELAY = "service_delay"
    SERVICE_CANCELLATION = "service_cancellation"
    DWELL_EXTENSION = "dwell_extension"


class ServiceStatus(StrEnum):
    """Simulation status for a service after disruptions are applied."""

    SCHEDULED = "scheduled"
    DELAYED = "delayed"
    CANCELLED = "cancelled"


def generate_disruption_id() -> str:
    """Return a stable unique ID for a disruption scenario item."""

    return str(uuid4())


class BaseDisruption(BaseModel):
    """Common fields shared by all disruptions."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=generate_disruption_id)
    service_id: str
    description: str | None = None


class ServiceDelay(BaseDisruption):
    """Delay every timed stop in a service by a fixed number of minutes."""

    type: Literal[DisruptionType.SERVICE_DELAY] = DisruptionType.SERVICE_DELAY
    delay_minutes: int = Field(..., gt=0)


class ServiceCancellation(BaseDisruption):
    """Mark a service as cancelled."""

    type: Literal[DisruptionType.SERVICE_CANCELLATION] = DisruptionType.SERVICE_CANCELLATION


class DwellExtension(BaseDisruption):
    """Extend dwell at a station and shift later timings by the same amount."""

    type: Literal[DisruptionType.DWELL_EXTENSION] = DisruptionType.DWELL_EXTENSION
    station_id: str
    extra_minutes: int = Field(..., gt=0)


Disruption = Annotated[
    ServiceDelay | ServiceCancellation | DwellExtension,
    Field(discriminator="type"),
]


class Scenario(BaseModel):
    """A named set of disruptions to apply in order."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=generate_disruption_id)
    name: str
    disruptions: list[Disruption] = Field(default_factory=list)


class SimulatedService(BaseModel):
    """A service plus its disruption status and metadata."""

    model_config = ConfigDict(extra="forbid")

    service: Service
    status: ServiceStatus = ServiceStatus.SCHEDULED
    delay_minutes: int = 0
    applied_disruption_ids: list[str] = Field(default_factory=list)


class DisruptionApplication(BaseModel):
    """Result of applying disruptions to a set of services."""

    model_config = ConfigDict(extra="forbid")

    services: list[SimulatedService]
    warnings: list[str] = Field(default_factory=list)

    @property
    def active_services(self) -> list[SimulatedService]:
        return [service for service in self.services if service.status != ServiceStatus.CANCELLED]

    @property
    def cancelled_services(self) -> list[SimulatedService]:
        return [service for service in self.services if service.status == ServiceStatus.CANCELLED]


def minutes_from_time(value: str, day_offset: int = 0) -> int:
    """Convert an HH:MM time and day offset into absolute minutes."""

    hours, minutes = value.split(":", maxsplit=1)
    return day_offset * MINUTES_PER_DAY + int(hours) * 60 + int(minutes)


def time_from_minutes(total_minutes: int) -> tuple[str, int]:
    """Convert absolute minutes back to HH:MM plus day offset."""

    day_offset, minute_of_day = divmod(total_minutes, MINUTES_PER_DAY)
    hours, minutes = divmod(minute_of_day, 60)
    return f"{hours:02d}:{minutes:02d}", day_offset


def shift_time(value: str | None, day_offset: int, minutes: int) -> tuple[str | None, int]:
    """Shift a single optional time by a number of minutes."""

    if value is None:
        return None, day_offset
    return time_from_minutes(minutes_from_time(value, day_offset) + minutes)


def shift_stop(
    stop: Stop,
    minutes: int,
    *,
    shift_arrival: bool = True,
    shift_departure: bool = True,
) -> Stop:
    """Return a copy of a stop with selected timings shifted."""

    update: dict[str, str | int | None] = {}

    if shift_arrival:
        arrival, arrival_day_offset = shift_time(stop.arrival, stop.arrival_day_offset, minutes)
        update["arrival"] = arrival
        update["arrival_day_offset"] = arrival_day_offset

    if shift_departure:
        departure, departure_day_offset = shift_time(stop.departure, stop.departure_day_offset, minutes)
        update["departure"] = departure
        update["departure_day_offset"] = departure_day_offset

    return stop.model_copy(update=update)


def delay_service(service: Service, delay_minutes: int) -> Service:
    """Return a service with every timed stop shifted later."""

    return service.model_copy(
        update={
            "stops": [
                shift_stop(stop, delay_minutes)
                for stop in service.stops
            ]
        }
    )


def extend_dwell(service: Service, station_id: str, extra_minutes: int) -> Service:
    """Return a service with dwell extended at one station and later calls shifted."""

    station_indexes = [index for index, stop in enumerate(service.stops) if stop.station_id == station_id]
    if not station_indexes:
        raise ValueError(f"station {station_id} is not called by service {service.id}")

    start_index = station_indexes[0]
    updated_stops: list[Stop] = []

    for index, stop in enumerate(service.stops):
        if index < start_index:
            updated_stops.append(stop)
        elif index == start_index:
            updated_stops.append(
                shift_stop(
                    stop,
                    extra_minutes,
                    shift_arrival=False,
                    shift_departure=stop.departure is not None,
                )
            )
        else:
            updated_stops.append(shift_stop(stop, extra_minutes))

    return service.model_copy(update={"stops": updated_stops})


def apply_disruption(simulated_service: SimulatedService, disruption: Disruption) -> SimulatedService:
    """Apply one disruption to one matching simulated service."""

    if disruption.type == DisruptionType.SERVICE_CANCELLATION:
        return simulated_service.model_copy(
            update={
                "status": ServiceStatus.CANCELLED,
                "applied_disruption_ids": [
                    *simulated_service.applied_disruption_ids,
                    disruption.id,
                ],
            }
        )

    if simulated_service.status == ServiceStatus.CANCELLED:
        return simulated_service

    if disruption.type == DisruptionType.SERVICE_DELAY:
        return simulated_service.model_copy(
            update={
                "service": delay_service(simulated_service.service, disruption.delay_minutes),
                "status": ServiceStatus.DELAYED,
                "delay_minutes": simulated_service.delay_minutes + disruption.delay_minutes,
                "applied_disruption_ids": [
                    *simulated_service.applied_disruption_ids,
                    disruption.id,
                ],
            }
        )

    if disruption.type == DisruptionType.DWELL_EXTENSION:
        return simulated_service.model_copy(
            update={
                "service": extend_dwell(
                    simulated_service.service,
                    disruption.station_id,
                    disruption.extra_minutes,
                ),
                "status": ServiceStatus.DELAYED,
                "delay_minutes": simulated_service.delay_minutes + disruption.extra_minutes,
                "applied_disruption_ids": [
                    *simulated_service.applied_disruption_ids,
                    disruption.id,
                ],
            }
        )

    raise ValueError(f"Unsupported disruption type: {disruption.type}")


def apply_disruptions(services: list[Service], disruptions: list[Disruption]) -> DisruptionApplication:
    """Apply disruptions to services in order and return simulated services."""

    simulated_by_id = {
        service.id: SimulatedService(service=service)
        for service in services
    }
    warnings: list[str] = []

    for disruption in disruptions:
        simulated_service = simulated_by_id.get(disruption.service_id)
        if simulated_service is None:
            warnings.append(f"service {disruption.service_id} was not found for disruption {disruption.id}")
            continue

        try:
            simulated_by_id[disruption.service_id] = apply_disruption(simulated_service, disruption)
        except ValueError as error:
            warnings.append(str(error))

    return DisruptionApplication(
        services=list(simulated_by_id.values()),
        warnings=warnings,
    )


def apply_scenario(services: list[Service], scenario: Scenario) -> DisruptionApplication:
    """Apply every disruption in a scenario to a service list."""

    return apply_disruptions(services, scenario.disruptions)
