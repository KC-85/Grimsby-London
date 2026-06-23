from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from simulation.disruption import ServiceStatus
from simulation.engine import SimulationResult


class SimulationMetrics(BaseModel):
    """Summary metrics for a simulation run."""

    model_config = ConfigDict(extra="forbid")

    total_services: int
    active_services: int
    cancelled_services: int
    delayed_services: int
    total_delay_minutes: int
    average_delay_minutes: float
    max_delay_minutes: int
    section_occupations: int
    conflicts: int
    total_conflict_minutes: int
    warnings: int


class MetricBreakdown(BaseModel):
    """A simple label/count metric row."""

    model_config = ConfigDict(extra="forbid")

    label: str
    count: int


def calculate_metrics(result: SimulationResult) -> SimulationMetrics:
    """Calculate headline metrics from a simulation result."""

    total_services = len(result.services)
    cancelled_services = sum(1 for service in result.services if service.status == ServiceStatus.CANCELLED)
    delayed_services = sum(1 for service in result.services if service.status == ServiceStatus.DELAYED)
    active_services = total_services - cancelled_services
    delay_values = [
        service.delay_minutes
        for service in result.services
        if service.status == ServiceStatus.DELAYED
    ]
    total_delay_minutes = sum(delay_values)

    return SimulationMetrics(
        total_services=total_services,
        active_services=active_services,
        cancelled_services=cancelled_services,
        delayed_services=delayed_services,
        total_delay_minutes=total_delay_minutes,
        average_delay_minutes=total_delay_minutes / delayed_services if delayed_services else 0,
        max_delay_minutes=max(delay_values, default=0),
        section_occupations=len(result.occupations),
        conflicts=len(result.conflicts),
        total_conflict_minutes=sum(conflict.overlap_minutes for conflict in result.conflicts),
        warnings=len(result.warnings),
    )


def _counter_to_breakdown(counter: Counter[str]) -> list[MetricBreakdown]:
    return [
        MetricBreakdown(label=label, count=count)
        for label, count in counter.most_common()
    ]


def services_by_operator(result: SimulationResult) -> list[MetricBreakdown]:
    """Count simulated services by operator."""

    return _counter_to_breakdown(Counter(service.service.operator for service in result.services))


def services_by_route(result: SimulationResult) -> list[MetricBreakdown]:
    """Count simulated services by route ID."""

    return _counter_to_breakdown(Counter(service.service.route_id for service in result.services))


def delayed_services_by_operator(result: SimulationResult) -> list[MetricBreakdown]:
    """Count delayed services by operator."""

    return _counter_to_breakdown(
        Counter(
            service.service.operator
            for service in result.services
            if service.status == ServiceStatus.DELAYED
        )
    )


def cancelled_services_by_operator(result: SimulationResult) -> list[MetricBreakdown]:
    """Count cancelled services by operator."""

    return _counter_to_breakdown(
        Counter(
            service.service.operator
            for service in result.services
            if service.status == ServiceStatus.CANCELLED
        )
    )


def conflicts_by_section(result: SimulationResult) -> list[MetricBreakdown]:
    """Count conflicts by physical section key."""

    return _counter_to_breakdown(Counter(conflict.section_key for conflict in result.conflicts))


def conflicts_by_day(result: SimulationResult) -> list[MetricBreakdown]:
    """Count conflicts by operating day."""

    return _counter_to_breakdown(
        Counter(day for conflict in result.conflicts for day in conflict.service_days)
    )
