from __future__ import annotations

from backend.schemas import DaySimulationResponse, WeekSimulationResponse


DAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def get_day_simulation(
    day: str,
    *,
    include_proposal: bool = True,
) -> DaySimulationResponse:
    """Return a first-pass simulation response for one operating day."""

    return DaySimulationResponse(
        day=day,
        include_proposal=include_proposal,
        status="ready",
    )


def get_week_simulation(
    *,
    include_proposal: bool = True,
) -> WeekSimulationResponse:
    """Return a first-pass simulation response for the whole week."""

    return WeekSimulationResponse(
        include_proposal=include_proposal,
        days=[
            get_day_simulation(day, include_proposal=include_proposal)
            for day in DAYS
        ],
    )
