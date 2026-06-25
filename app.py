from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from simulation.disruption import (
    DwellExtension,
    Scenario,
    ServiceCancellation,
    ServiceDelay,
)
from simulation.engine import SimulationResult, run_simulation
from simulation.infrastructure import load_infrastructure, route_lookup, station_lookup
from simulation.metrics import (
    calculate_metrics,
    conflicts_by_day,
    conflicts_by_section,
    services_by_operator,
    services_by_route,
)
from simulation.timetable import Service, flatten_services, load_services
from simulation.train import (
    ServiceRollingStock,
    load_rolling_stock,
    resolve_service_rolling_stock,
)


DATA_PATHS = (
    Path("data/services.json"),
    Path("data/proposed_services.json"),
    Path("data/stations.json"),
    Path("data/routes.json"),
    Path("data/sources.json"),
    Path("data/rolling_stock.json"),
)
SCENARIOS_PATH = Path("data/scenarios.json")
TIMELINE_BASE_DATE = pd.Timestamp("2026-01-01")
DAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def data_file_signature() -> tuple[tuple[str, int, int], ...]:
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in DATA_PATHS)


@st.cache_data
def load_app_data(data_signature):
    infrastructure = load_infrastructure()
    services = load_services()
    proposed_services = load_services("data/proposed_services.json")
    rolling_stock = load_rolling_stock()
    return infrastructure, services, proposed_services, rolling_stock


def service_labels(services: list[Service]) -> dict[str, str]:
    """Return user-facing service labels based on first departure time."""

    return {
        service.id: service.first_departure or service.id
        for service in services
    }


def build_timetable_dataframe(
    services: list[Service],
    stations_by_id,
    routes_by_id,
    rolling_stock_by_service: dict[str, ServiceRollingStock],
    service_status: dict[str, str] | None = None,
    service_delays: dict[str, int] | None = None,
) -> pd.DataFrame:
    rows = flatten_services(services)
    df = pd.DataFrame(rows)
    df["station"] = df["station_id"].map(lambda station_id: stations_by_id[station_id].name)
    df["origin_name"] = df["origin"].map(lambda station_id: stations_by_id[station_id].name)
    df["destination_name"] = df["destination"].map(lambda station_id: stations_by_id[station_id].name)
    df["route"] = df["route_id"].map(lambda route_id: routes_by_id[route_id].name)
    df["service_label"] = df["service_id"].map(service_labels(services))
    df["timetable_type"] = df["footnote_codes"].map(
        lambda value: "Proposed" if "PROPOSED" in value.split(", ") else "Current"
    )
    df["status"] = df["service_id"].map(service_status or {}).fillna("scheduled")
    df["delay_minutes"] = df["service_id"].map(service_delays or {}).fillna(0).astype(int)
    df["rolling_stock_id"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].rolling_stock.id
    )
    df["train_class"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].rolling_stock.name
    )
    df["train_family"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].rolling_stock.family
    )
    df["formation_cars"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].cars
    )
    df["length_metres"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].formation.length_metres
    )
    df["seats"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].seats
    )
    df["maximum_speed_mph"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].rolling_stock.traction.maximum_speed_mph
    )
    df["traction"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].rolling_stock.traction.type
    )
    df["coupling"] = df["service_id"].map(
        lambda service_id: rolling_stock_by_service[service_id].rolling_stock.coupling.type
    )
    return df


def section_label(section_key: str, stations_by_id) -> str:
    station_ids = section_key.split("::")
    return " to ".join(stations_by_id[station_id].name for station_id in station_ids)


def build_conflicts_dataframe(
    result: SimulationResult,
    stations_by_id,
    rolling_stock_by_service: dict[str, ServiceRollingStock],
) -> pd.DataFrame:
    services_by_id = {
        simulated.service.id: simulated.service
        for simulated in result.services
    }
    labels_by_id = service_labels(list(services_by_id.values()))
    rows = [
        {
            "section": section_label(conflict.section_key, stations_by_id),
            "first_operator": services_by_id[conflict.first_service_id].operator,
            "first_service": labels_by_id.get(conflict.first_service_id, conflict.first_service_id),
            "first_train": rolling_stock_by_service[conflict.first_service_id].rolling_stock.name,
            "first_cars": rolling_stock_by_service[conflict.first_service_id].cars,
            "second_operator": services_by_id[conflict.second_service_id].operator,
            "second_service": labels_by_id.get(conflict.second_service_id, conflict.second_service_id),
            "second_train": rolling_stock_by_service[conflict.second_service_id].rolling_stock.name,
            "second_cars": rolling_stock_by_service[conflict.second_service_id].cars,
            "days": ", ".join(conflict.service_days),
            "overlap_start": conflict.overlap_start,
            "overlap_end": conflict.overlap_end,
            "overlap_minutes": conflict.overlap_minutes,
        }
        for conflict in result.conflicts
    ]
    return pd.DataFrame(rows)


def build_occupations_dataframe(
    result: SimulationResult,
    stations_by_id,
    routes_by_id,
    rolling_stock_by_service: dict[str, ServiceRollingStock],
) -> pd.DataFrame:
    labels_by_id = service_labels(
        [simulated.service for simulated in result.services]
    )
    rows = [
        {
            "service_id": occupation.service_id,
            "service_label": labels_by_id.get(occupation.service_id, occupation.service_id),
            "operator": occupation.operator,
            "train_class": rolling_stock_by_service[occupation.service_id].rolling_stock.name,
            "formation_cars": rolling_stock_by_service[occupation.service_id].cars,
            "seats": rolling_stock_by_service[occupation.service_id].seats,
            "route": routes_by_id[occupation.route_id].name,
            "section": section_label(occupation.section_key, stations_by_id),
            "from": stations_by_id[occupation.from_station].name,
            "to": stations_by_id[occupation.to_station].name,
            "track_layout": occupation.capacity_model.value.replace("_", " ").title(),
            "directional_capacity": occupation.directional_capacity,
            "enter": occupation.enter_time,
            "exit": occupation.exit_time,
            "enter_minutes": occupation.enter_time_minutes,
            "exit_minutes": occupation.exit_time_minutes,
            "duration_minutes": occupation.duration_minutes,
            "service_days": ", ".join(occupation.service_days),
            "status": occupation.status.value,
            "delay_minutes": occupation.delay_minutes,
        }
        for occupation in result.occupations
    ]
    return pd.DataFrame(rows)


def build_breakdown_dataframe(items, label_map: dict[str, str] | None = None) -> pd.DataFrame:
    rows = []
    for item in items:
        row = item.model_dump()
        if label_map is not None:
            row["label"] = label_map.get(row["label"], row["label"])
        rows.append(row)
    return pd.DataFrame(rows)


def service_option_label(service: Service, stations_by_id) -> str:
    origin = stations_by_id[service.origin].name
    destination = stations_by_id[service.destination].name
    departure = service.first_departure or "No departure"
    days = "/".join(day[:3].title() for day in service.service_days)
    return f"{departure} {origin} to {destination} ({days})"


def load_saved_scenarios() -> list[Scenario]:
    if not SCENARIOS_PATH.exists():
        return []

    with SCENARIOS_PATH.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    return [
        Scenario.model_validate(item)
        for item in payload.get("scenarios", [])
    ]


def save_scenarios(scenarios: list[Scenario]) -> None:
    SCENARIOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenarios": [
            scenario.model_dump(mode="json")
            for scenario in scenarios
        ]
    }

    with SCENARIOS_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")


def upsert_scenario(scenarios: list[Scenario], scenario: Scenario) -> list[Scenario]:
    return [
        existing
        for existing in scenarios
        if existing.name.lower() != scenario.name.lower()
    ] + [scenario]


def render_saved_scenario_controls() -> None:
    saved_scenarios = load_saved_scenarios()

    if saved_scenarios:
        scenario_by_id = {scenario.id: scenario for scenario in saved_scenarios}
        selected_scenario_id = st.sidebar.selectbox(
            "Saved scenario",
            list(scenario_by_id),
            format_func=lambda scenario_id: scenario_by_id[scenario_id].name,
        )

        if st.sidebar.button("Load scenario"):
            st.session_state.disruptions = scenario_by_id[selected_scenario_id].disruptions
            st.rerun()
    else:
        st.sidebar.caption("No saved scenarios yet")

    with st.sidebar.form("save_scenario"):
        scenario_name = st.text_input("Scenario name")
        submitted = st.form_submit_button("Save scenario")

    if submitted:
        clean_name = scenario_name.strip()
        if not clean_name:
            st.sidebar.warning("Add a scenario name before saving.")
            return

        scenario = Scenario(
            name=clean_name,
            disruptions=list(st.session_state.disruptions),
        )
        save_scenarios(upsert_scenario(saved_scenarios, scenario))
        st.sidebar.success(f"Saved {clean_name}")


def render_disruption_controls(services: list[Service], stations_by_id) -> list:
    st.sidebar.header("Scenario")

    if "disruptions" not in st.session_state:
        st.session_state.disruptions = []

    render_saved_scenario_controls()

    services_by_id = {service.id: service for service in services}
    service_ids = list(services_by_id)

    with st.sidebar.form("add_disruption"):
        selected_service_id = st.selectbox(
            "Service",
            service_ids,
            format_func=lambda service_id: service_option_label(services_by_id[service_id], stations_by_id),
        )
        action = st.selectbox(
            "Action",
            ["Delay service", "Cancel service", "Extend station dwell"],
        )

        delay_minutes = 5
        extra_minutes = 2
        selected_station_id = None

        if action == "Delay service":
            delay_minutes = st.number_input("Delay minutes", min_value=1, max_value=240, value=5, step=1)
        elif action == "Extend station dwell":
            stop_station_ids = [stop.station_id for stop in services_by_id[selected_service_id].stops]
            selected_station_id = st.selectbox(
                "Station",
                stop_station_ids,
                format_func=lambda station_id: stations_by_id[station_id].name,
            )
            extra_minutes = st.number_input("Extra dwell minutes", min_value=1, max_value=120, value=2, step=1)

        submitted = st.form_submit_button("Add disruption")

    if submitted:
        if action == "Delay service":
            st.session_state.disruptions.append(
                ServiceDelay(service_id=selected_service_id, delay_minutes=delay_minutes)
            )
        elif action == "Cancel service":
            st.session_state.disruptions.append(ServiceCancellation(service_id=selected_service_id))
        elif selected_station_id is not None:
            st.session_state.disruptions.append(
                DwellExtension(
                    service_id=selected_service_id,
                    station_id=selected_station_id,
                    extra_minutes=extra_minutes,
                )
            )

    if st.sidebar.button("Clear scenario"):
        st.session_state.disruptions = []
        st.rerun()

    if st.session_state.disruptions:
        st.sidebar.caption(f"{len(st.session_state.disruptions)} disruption(s) active")
        for index, disruption in enumerate(st.session_state.disruptions, start=1):
            service = services_by_id.get(disruption.service_id)
            service_label = service.first_departure if service else disruption.service_id
            st.sidebar.write(f"{index}. {disruption.type.value}: {service_label}")
    else:
        st.sidebar.caption("No disruptions active")

    return st.session_state.disruptions


def render_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filters")

    available_days = {day for value in df["service_days"] for day in value.split(", ")}
    days = [day for day in DAYS if day in available_days]
    operators = sorted(df["operator"].unique())
    train_classes = sorted(df["train_class"].unique())
    routes = sorted(df["route"].unique())
    statuses = sorted(df["status"].unique())

    selected_day = st.sidebar.selectbox("Day", days)
    selected_operators = st.sidebar.multiselect("Operator", operators, default=operators)
    selected_train_classes = st.sidebar.multiselect(
        "Rolling stock",
        train_classes,
        default=train_classes,
    )
    selected_route = st.sidebar.selectbox("Route", routes)
    selected_statuses = st.sidebar.multiselect("Status", statuses, default=statuses)

    return df[
        df["service_days"].str.contains(selected_day, regex=False)
        & df["operator"].isin(selected_operators)
        & df["train_class"].isin(selected_train_classes)
        & (df["route"] == selected_route)
        & df["status"].isin(selected_statuses)
    ]


def render_metric_cards(result: SimulationResult, timetable_df: pd.DataFrame) -> None:
    metrics = calculate_metrics(result)
    services = timetable_df.drop_duplicates(subset=["service_id"])
    active_services = services[services["status"] != "cancelled"]
    known_seat_capacity = int(active_services["seats"].fillna(0).sum())
    unknown_capacity_services = int(active_services["seats"].isna().sum())

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Services", metrics.total_services)
    col2.metric("Active", metrics.active_services)
    col3.metric("Delayed", metrics.delayed_services)
    col4.metric("Cancelled", metrics.cancelled_services)
    col5.metric("Conflicts", metrics.conflicts)
    col6.metric("Warnings", metrics.warnings)

    col7, col8, col9, col10, col11, col12 = st.columns(6)
    col7.metric("Total Delay", metrics.total_delay_minutes)
    col8.metric("Average Delay", f"{metrics.average_delay_minutes:.1f}")
    col9.metric("Max Delay", metrics.max_delay_minutes)
    col10.metric("Conflict Minutes", metrics.total_conflict_minutes)
    col11.metric("Known Seats", f"{known_seat_capacity:,}")
    col12.metric("Unknown Capacity", unknown_capacity_services)


def render_timetable(df: pd.DataFrame) -> None:
    display_columns = [
        "service_label",
        "operator",
        "train_class",
        "formation_cars",
        "length_metres",
        "seats",
        "maximum_speed_mph",
        "route",
        "station",
        "arrival",
        "departure",
        "status",
        "delay_minutes",
        "footnote_codes",
    ]

    st.dataframe(
        df[display_columns],
        width="stretch",
        hide_index=True,
    )


def render_conflicts(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No section conflicts detected.")
        return

    st.dataframe(df, width="stretch", hide_index=True)


def render_occupations(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No section occupation rows generated.")
        return

    display_columns = [
        "service_label",
        "operator",
        "train_class",
        "formation_cars",
        "seats",
        "route",
        "section",
        "track_layout",
        "directional_capacity",
        "enter",
        "exit",
        "duration_minutes",
        "service_days",
        "status",
        "delay_minutes",
    ]

    st.dataframe(df[display_columns], width="stretch", hide_index=True)


def rows_for_day(df: pd.DataFrame, day: str, days_column: str) -> pd.DataFrame:
    """Return dataframe rows that operate on the selected day."""

    if df.empty:
        return df.copy()
    return df[
        df[days_column].map(lambda value: day in value.split(", "))
    ].copy()


def build_daily_services_dataframe(timetable_df: pd.DataFrame) -> pd.DataFrame:
    """Return one operational summary row per service."""

    columns = [
        "service_id",
        "service_label",
        "operator",
        "timetable_type",
        "train_class",
        "formation_cars",
        "length_metres",
        "seats",
        "maximum_speed_mph",
        "route",
        "origin_name",
        "destination_name",
        "status",
        "delay_minutes",
        "footnote_codes",
    ]
    return (
        timetable_df[columns]
        .drop_duplicates(subset=["service_id"])
        .sort_values(["service_label", "operator", "route"])
    )


def render_daily_metric_cards(
    timetable_df: pd.DataFrame,
    conflicts_df: pd.DataFrame,
    occupations_df: pd.DataFrame,
) -> None:
    """Render summary metrics for one operating day."""

    services = timetable_df.drop_duplicates(subset=["service_id"])
    total_services = len(services)
    proposed_services = int((services["timetable_type"] == "Proposed").sum())
    delayed_services = int((services["status"] == "delayed").sum())
    cancelled_services = int((services["status"] == "cancelled").sum())
    active_services = services[services["status"] != "cancelled"]
    known_seat_capacity = int(active_services["seats"].fillna(0).sum())
    unknown_capacity_services = int(active_services["seats"].isna().sum())

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Services", total_services)
    col2.metric("Proposed", proposed_services)
    col3.metric("Delayed", delayed_services)
    col4.metric("Cancelled", cancelled_services)
    col5.metric("Conflicts", len(conflicts_df))
    col6.metric("Conflict Minutes", int(conflicts_df["overlap_minutes"].sum()) if not conflicts_df.empty else 0)

    col7, col8, col9, col10, col11 = st.columns(5)
    col7.metric("Operators", services["operator"].nunique())
    col8.metric("Routes", services["route"].nunique())
    col9.metric("Known Seats", f"{known_seat_capacity:,}")
    col10.metric("Unknown Capacity", unknown_capacity_services)
    col11.metric("Section Occupations", len(occupations_df))


def render_daily_timetables(
    timetable_df: pd.DataFrame,
    conflicts_df: pd.DataFrame,
    occupations_df: pd.DataFrame,
) -> None:
    """Render complete Monday-to-Sunday operational views."""

    day_tabs = st.tabs([day.title() for day in DAYS])
    for day, day_tab in zip(DAYS, day_tabs):
        with day_tab:
            day_timetable = rows_for_day(timetable_df, day, "service_days")
            day_conflicts = rows_for_day(conflicts_df, day, "days")
            day_occupations = rows_for_day(occupations_df, day, "service_days")

            day_timetable = day_timetable.sort_values(
                ["service_label", "operator", "route", "stop_index"]
            )
            day_conflicts = day_conflicts.sort_values(
                ["overlap_start", "section", "first_service", "second_service"]
            )
            day_occupations = day_occupations.sort_values(
                ["enter_minutes", "section", "service_label"]
            )

            render_daily_metric_cards(day_timetable, day_conflicts, day_occupations)

            services_tab, timetable_tab, conflicts_tab, occupations_tab = st.tabs(
                ["Services", "Full Timetable", "Conflicts", "Section Occupations"]
            )
            with services_tab:
                st.dataframe(
                    build_daily_services_dataframe(day_timetable),
                    width="stretch",
                    hide_index=True,
                )
            with timetable_tab:
                render_timetable(day_timetable)
            with conflicts_tab:
                render_conflicts(day_conflicts)
            with occupations_tab:
                render_occupations(day_occupations)


def minutes_to_timestamp(value: int) -> pd.Timestamp:
    return TIMELINE_BASE_DATE + pd.to_timedelta(value, unit="m")


def render_occupation_timeline(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No section occupation rows generated.")
        return

    days = sorted({day for value in df["service_days"] for day in value.split(", ")})
    operators = sorted(df["operator"].unique())
    train_classes = sorted(df["train_class"].unique())
    routes = sorted(df["route"].unique())
    statuses = sorted(df["status"].unique())

    col1, col2, col3, col4, col5 = st.columns(5)
    selected_day = col1.selectbox("Timeline day", days)
    selected_operators = col2.multiselect("Timeline operator", operators, default=operators)
    selected_train_classes = col3.multiselect(
        "Timeline rolling stock",
        train_classes,
        default=train_classes,
    )
    selected_route = col4.selectbox("Timeline route", routes)
    selected_statuses = col5.multiselect("Timeline status", statuses, default=statuses)

    timeline_df = df[
        df["service_days"].str.contains(selected_day, regex=False)
        & df["operator"].isin(selected_operators)
        & df["train_class"].isin(selected_train_classes)
        & (df["route"] == selected_route)
        & df["status"].isin(selected_statuses)
    ].copy()

    if timeline_df.empty:
        st.info("No section occupations match the selected timeline filters.")
        return

    timeline_df["start"] = timeline_df["enter_minutes"].map(minutes_to_timestamp)
    timeline_df["finish"] = timeline_df[["enter_minutes", "exit_minutes"]].max(axis=1)
    timeline_df["finish"] = timeline_df["finish"].where(
        timeline_df["finish"] > timeline_df["enter_minutes"],
        timeline_df["enter_minutes"] + 1,
    )
    timeline_df["finish"] = timeline_df["finish"].map(minutes_to_timestamp)

    height = min(900, max(420, 140 + timeline_df["section"].nunique() * 28))
    figure = px.timeline(
        timeline_df.sort_values(["section", "enter_minutes"]),
        x_start="start",
        x_end="finish",
        y="section",
        color="operator",
        hover_data={
            "service_label": True,
            "train_class": True,
            "formation_cars": True,
            "seats": True,
            "route": True,
            "enter": True,
            "exit": True,
            "status": True,
            "delay_minutes": True,
            "start": False,
            "finish": False,
        },
    )
    figure.update_yaxes(autorange="reversed", title=None)
    figure.update_xaxes(tickformat="%H:%M", title="Time")
    figure.update_layout(
        height=height,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        legend_title_text="Operator",
    )

    st.plotly_chart(figure, width="stretch")


def render_breakdowns(
    result: SimulationResult,
    stations_by_id,
    routes_by_id,
    timetable_df: pd.DataFrame,
) -> None:
    route_labels = {route_id: route.name for route_id, route in routes_by_id.items()}
    section_labels = {
        item.label: section_label(item.label, stations_by_id)
        for item in conflicts_by_section(result)
    }

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Services By Operator")
        st.dataframe(build_breakdown_dataframe(services_by_operator(result)), width="stretch", hide_index=True)
        st.subheader("Conflicts By Section")
        st.dataframe(
            build_breakdown_dataframe(conflicts_by_section(result), section_labels),
            width="stretch",
            hide_index=True,
        )

    with col2:
        st.subheader("Services By Route")
        st.dataframe(
            build_breakdown_dataframe(services_by_route(result), route_labels),
            width="stretch",
            hide_index=True,
        )
        st.subheader("Conflicts By Day")
        st.dataframe(build_breakdown_dataframe(conflicts_by_day(result)), width="stretch", hide_index=True)

    service_stock = (
        timetable_df[
            [
                "service_id",
                "operator",
                "train_class",
                "formation_cars",
                "length_metres",
                "seats",
                "maximum_speed_mph",
            ]
        ]
        .drop_duplicates(subset=["service_id"])
        .groupby(
            [
                "operator",
                "train_class",
                "formation_cars",
                "length_metres",
                "seats",
                "maximum_speed_mph",
            ],
            dropna=False,
        )
        .size()
        .reset_index(name="services")
        .sort_values(["operator", "train_class"])
    )
    st.subheader("Rolling Stock")
    st.dataframe(service_stock, width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Grimsby-London Rail Simulation", layout="wide")
    st.title("Grimsby-London Rail Simulation")

    st.sidebar.header("Data")
    if st.sidebar.button("Reload data"):
        st.cache_data.clear()
        st.rerun()

    infrastructure, baseline_services, proposed_services, rolling_stock = load_app_data(
        data_file_signature()
    )
    stations_by_id = station_lookup(infrastructure.stations)
    routes_by_id = route_lookup(infrastructure.routes)
    include_proposal = st.sidebar.toggle(
        "Include Grand Central proposal",
        value=True,
    )
    services = [
        *baseline_services,
        *(proposed_services if include_proposal else []),
    ]
    st.sidebar.caption(
        "Current timetable + Grand Central proposal"
        if include_proposal
        else "Current timetable baseline"
    )
    disruptions = render_disruption_controls(services, stations_by_id)
    simulation_result = run_simulation(services, infrastructure, disruptions)

    if simulation_result.warnings:
        for warning in simulation_result.warnings:
            st.warning(warning)

    simulated_services = [simulated.service for simulated in simulation_result.services]
    rolling_stock_by_service, rolling_stock_warnings = resolve_service_rolling_stock(
        simulated_services,
        rolling_stock,
    )
    for warning in rolling_stock_warnings:
        st.warning(warning)

    service_status = {
        simulated.service.id: simulated.status.value
        for simulated in simulation_result.services
    }
    service_delays = {
        simulated.service.id: simulated.delay_minutes
        for simulated in simulation_result.services
    }

    df = build_timetable_dataframe(
        simulated_services,
        stations_by_id,
        routes_by_id,
        rolling_stock_by_service,
        service_status=service_status,
        service_delays=service_delays,
    )
    filtered_df = render_filters(df)
    conflicts_df = build_conflicts_dataframe(
        simulation_result,
        stations_by_id,
        rolling_stock_by_service,
    )
    occupations_df = build_occupations_dataframe(
        simulation_result,
        stations_by_id,
        routes_by_id,
        rolling_stock_by_service,
    )

    render_metric_cards(simulation_result, df)

    daily_tab, timetable_tab, conflicts_tab, occupations_tab, metrics_tab = st.tabs(
        ["Daily Timetables", "Filtered Timetable", "Conflicts", "Section Occupations", "Metrics"]
    )
    with daily_tab:
        render_daily_timetables(df, conflicts_df, occupations_df)
    with timetable_tab:
        render_timetable(filtered_df)
    with conflicts_tab:
        render_conflicts(conflicts_df)
    with occupations_tab:
        timeline_tab, occupations_table_tab = st.tabs(["Timeline", "Table"])
        with timeline_tab:
            render_occupation_timeline(occupations_df)
        with occupations_table_tab:
            render_occupations(occupations_df)
    with metrics_tab:
        render_breakdowns(simulation_result, stations_by_id, routes_by_id, df)


if __name__ == "__main__":
    main()
