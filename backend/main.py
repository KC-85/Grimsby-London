from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from backend.schemas import (
    DaySimulationResponse,
    HealthResponse,
    WeekSimulationResponse,
)
from backend.services.simulation_service import (
    DAYS,
    get_day_simulation,
    get_week_simulation,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Grimsby-London Rail Simulation API",
        version="0.1.0",
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="grimsby-london-backend")

    @app.get("/simulation/days", response_model=list[str])
    async def simulation_days() -> list[str]:
        return DAYS

    @app.get("/simulation/day/{day}", response_model=DaySimulationResponse)
    async def simulation_day(
        day: str,
        include_proposal: bool = Query(default=True),
    ) -> DaySimulationResponse:
        normalised_day = day.lower()
        if normalised_day not in DAYS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown day '{day}'. Expected one of: {', '.join(DAYS)}",
            )

        return get_day_simulation(
            normalised_day,
            include_proposal=include_proposal,
        )

    @app.get("/simulation/week", response_model=WeekSimulationResponse)
    async def simulation_week(
        include_proposal: bool = Query(default=True),
    ) -> WeekSimulationResponse:
        return get_week_simulation(include_proposal=include_proposal)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)


def run() -> None:
    main()


if __name__ == "__main__":
    run()
