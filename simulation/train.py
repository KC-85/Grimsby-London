from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simulation.timetable import Service


DEFAULT_ROLLING_STOCK_PATH = Path("data/rolling_stock.json")


class Formation(BaseModel):
    """The normal physical and passenger formation of a train."""

    model_config = ConfigDict(extra="forbid")

    cars: int = Field(gt=0)
    length_metres: float | None = Field(default=None, gt=0)
    seats: int | None = Field(default=None, ge=0)
    tip_up_seats: int | None = Field(default=None, ge=0)


class OperatingFormation(Formation):
    """An alternative operating formation for the same rolling-stock class."""

    id: str
    units: int = Field(gt=0)
    usage: str


class Traction(BaseModel):
    """Traction type and maximum operating speed."""

    model_config = ConfigDict(extra="forbid")

    type: str
    maximum_speed_mph: int = Field(gt=0)


class Coupling(BaseModel):
    """Coupling equipment and multiple-unit capability."""

    model_config = ConfigDict(extra="forbid")

    type: str
    multiple_unit_compatible: bool = False


class RouteAssignment(BaseModel):
    """Permitted rolling-stock formation on one or more modelled routes."""

    model_config = ConfigDict(extra="forbid")

    route_ids: list[str] = Field(min_length=1)
    formation_cars: int = Field(gt=0)
    alternative_formation_cars: int | None = Field(default=None, gt=0)
    assignment_status: str

    @model_validator(mode="after")
    def validate_unique_route_ids(self) -> RouteAssignment:
        if len(self.route_ids) != len(set(self.route_ids)):
            raise ValueError("route assignment contains duplicate route IDs")
        return self


class RollingStockSource(BaseModel):
    """A source used for rolling-stock specifications."""

    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    accessed: str
    source_type: str


class RollingStock(BaseModel):
    """A rolling-stock class and its modelled operating formations."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    family: str
    operator_scope: list[str] = Field(min_length=1)
    status: str
    formation: Formation
    operating_formations: list[OperatingFormation] = Field(default_factory=list)
    traction: Traction
    coupling: Coupling
    route_assignments: list[RouteAssignment] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    sources: list[RollingStockSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_formations_and_routes(self) -> RollingStock:
        operating_ids = [formation.id for formation in self.operating_formations]
        if len(operating_ids) != len(set(operating_ids)):
            raise ValueError("duplicate operating formation IDs")

        available_car_counts = {
            self.formation.cars,
            *(formation.cars for formation in self.operating_formations),
        }
        assigned_route_ids: list[str] = []
        for assignment in self.route_assignments:
            assigned_route_ids.extend(assignment.route_ids)
            if assignment.formation_cars not in available_car_counts:
                raise ValueError(
                    f"route assignment uses unavailable {assignment.formation_cars}-car formation"
                )
            if (
                assignment.alternative_formation_cars is not None
                and assignment.alternative_formation_cars not in available_car_counts
            ):
                raise ValueError(
                    "route assignment uses an unavailable alternative formation"
                )

        if len(assigned_route_ids) != len(set(assigned_route_ids)):
            raise ValueError("rolling stock assigns the same route more than once")
        return self

    def assignment_for_route(self, route_id: str) -> RouteAssignment | None:
        """Return this stock's assignment for a route, if present."""

        return next(
            (
                assignment
                for assignment in self.route_assignments
                if route_id in assignment.route_ids
            ),
            None,
        )

    def formation_for_cars(self, cars: int) -> Formation | OperatingFormation:
        """Return the formation matching a requested car count."""

        if self.formation.cars == cars:
            return self.formation

        for formation in self.operating_formations:
            if formation.cars == cars:
                return formation

        raise ValueError(f"{self.id} has no {cars}-car formation")


class RollingStockFile(BaseModel):
    """Top-level structure for data/rolling_stock.json."""

    model_config = ConfigDict(extra="forbid")

    rolling_stock: list[RollingStock]

    @model_validator(mode="after")
    def validate_unique_ids_and_route_assignments(self) -> RollingStockFile:
        stock_ids = [stock.id for stock in self.rolling_stock]
        if len(stock_ids) != len(set(stock_ids)):
            raise ValueError("duplicate rolling-stock IDs")

        route_owners: dict[str, str] = {}
        for stock in self.rolling_stock:
            for assignment in stock.route_assignments:
                for route_id in assignment.route_ids:
                    existing_owner = route_owners.get(route_id)
                    if existing_owner is not None:
                        raise ValueError(
                            f"route {route_id} is assigned to both "
                            f"{existing_owner} and {stock.id}"
                        )
                    route_owners[route_id] = stock.id
        return self


class ServiceRollingStock(BaseModel):
    """Resolved rolling stock and formation for a timetable service."""

    model_config = ConfigDict(extra="forbid")

    service_id: str
    rolling_stock: RollingStock
    assignment: RouteAssignment
    formation: Formation | OperatingFormation

    @property
    def cars(self) -> int:
        return self.formation.cars

    @property
    def seats(self) -> int | None:
        return self.formation.seats


def load_rolling_stock(
    path: Path | str = DEFAULT_ROLLING_STOCK_PATH,
) -> list[RollingStock]:
    """Load and validate rolling-stock data from JSON."""

    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return RollingStockFile.model_validate(data).rolling_stock


def rolling_stock_lookup(
    rolling_stock: list[RollingStock],
) -> dict[str, RollingStock]:
    """Return rolling stock keyed by its unique ID."""

    return {stock.id: stock for stock in rolling_stock}


def rolling_stock_by_route(
    rolling_stock: list[RollingStock],
) -> dict[str, RollingStock]:
    """Return the assigned rolling stock for each route ID."""

    assignments: dict[str, RollingStock] = {}
    for stock in rolling_stock:
        for assignment in stock.route_assignments:
            for route_id in assignment.route_ids:
                existing = assignments.get(route_id)
                if existing is not None:
                    raise ValueError(
                        f"route {route_id} is assigned to both "
                        f"{existing.id} and {stock.id}"
                    )
                assignments[route_id] = stock
    return assignments


def rolling_stock_for_service(
    service: Service,
    rolling_stock: list[RollingStock],
    *,
    formation_cars: int | None = None,
) -> ServiceRollingStock:
    """Resolve the stock and operating formation assigned to a service."""

    stock = rolling_stock_by_route(rolling_stock).get(service.route_id)
    if stock is None:
        raise ValueError(f"no rolling stock is assigned to route {service.route_id}")
    if service.operator not in stock.operator_scope:
        raise ValueError(
            f"{stock.id} is not assigned to operator {service.operator}"
        )

    assignment = stock.assignment_for_route(service.route_id)
    if assignment is None:
        raise ValueError(f"{stock.id} has no assignment for route {service.route_id}")

    selected_cars = formation_cars or assignment.formation_cars
    permitted_car_counts = {
        assignment.formation_cars,
        assignment.alternative_formation_cars,
    }
    if selected_cars not in permitted_car_counts:
        raise ValueError(
            f"{selected_cars}-car formation is not permitted on route "
            f"{service.route_id}"
        )

    return ServiceRollingStock(
        service_id=service.id,
        rolling_stock=stock,
        assignment=assignment,
        formation=stock.formation_for_cars(selected_cars),
    )


def resolve_service_rolling_stock(
    services: list[Service],
    rolling_stock: list[RollingStock],
) -> tuple[dict[str, ServiceRollingStock], list[str]]:
    """Resolve all services, returning successful assignments and warnings."""

    resolved: dict[str, ServiceRollingStock] = {}
    warnings: list[str] = []

    for service in services:
        try:
            resolved[service.id] = rolling_stock_for_service(service, rolling_stock)
        except ValueError as error:
            warnings.append(f"{service.id}: {error}")

    return resolved, warnings
