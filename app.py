from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from simulation.disruption import (
    DwellExtension,
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


DATA_PATHS = (
    Path("data/services.json"),
    Path("data/stations.json"),
    Path("data/routes.json"),
    Path("data/sources.json"),
)


def data_file_signature() -> tuple[tuple[str, int, int], ...]:
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in DATA_PATHS)


@st.cache_data
def load_app_data(data_signature):
    infrastructure = load_infrastructure()
    services = load_services()
    return infrastructure, services


def build_timetable_dataframe(
    services: list[Service],
    stations_by_id,
    routes_by_id,
    service_status: dict[str, str] | None = None,
    service_delays: dict[str, int] | None = None,
) -> pd.DataFrame:
    rows = flatten_services(services)
    df = pd.DataFrame(rows)
    df["station"] = df["station_id"].map(lambda station_id: stations_by_id[station_id].name)
    df["route"] = df["route_id"].map(lambda route_id: routes_by_id[route_id].name)
    df["service_label"] = df["service_id"].str.replace("tpe-", "", regex=False)
    df["status"] = df["service_id"].map(service_status or {}).fillna("scheduled")
    df["delay_minutes"] = df["service_id"].map(service_delays or {}).fillna(0).astype(int)
    return df


def section_label(section_key: str, stations_by_id) -> str:
    station_ids = section_key.split("::")
    return " to ".join(stations_by_id[station_id].name for station_id in station_ids)


def build_conflicts_dataframe(result: SimulationResult, stations_by_id) -> pd.DataFrame:
    rows = [
        {
            "section": section_label(conflict.section_key, stations_by_id),
            "first_service": conflict.first_service_id,
            "second_service": conflict.second_service_id,
            "days": ", ".join(conflict.service_days),
            "overlap_start": conflict.overlap_start,
            "overlap_end": conflict.overlap_end,
            "overlap_minutes": conflict.overlap_minutes,
        }
        for conflict in result.conflicts
    ]
    return pd.DataFrame(rows)


def build_occupations_dataframe(result: SimulationResult, stations_by_id, routes_by_id) -> pd.DataFrame:
    rows = [
        {
            "service_id": occupation.service_id,
            "operator": occupation.operator,
            "route": routes_by_id[occupation.route_id].name,
            "from": stations_by_id[occupation.from_station].name,
            "to": stations_by_id[occupation.to_station].name,
            "enter": occupation.enter_time,
            "exit": occupation.exit_time,
            "duration_minutes": occupation.duration_minutes,
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


def render_disruption_controls(services: list[Service], stations_by_id) -> list:
    st.sidebar.header("Scenario")

    if "disruptions" not in st.session_state:
        st.session_state.disruptions = []

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

    days = sorted({day for value in df["service_days"] for day in value.split(", ")})
    operators = sorted(df["operator"].unique())
    routes = sorted(df["route"].unique())
    statuses = sorted(df["status"].unique())

    selected_day = st.sidebar.selectbox("Day", days)
    selected_operators = st.sidebar.multiselect("Operator", operators, default=operators)
    selected_route = st.sidebar.selectbox("Route", routes)
    selected_statuses = st.sidebar.multiselect("Status", statuses, default=statuses)

    return df[
        df["service_days"].str.contains(selected_day, regex=False)
        & df["operator"].isin(selected_operators)
        & (df["route"] == selected_route)
        & df["status"].isin(selected_statuses)
    ]


def render_metric_cards(result: SimulationResult) -> None:
    metrics = calculate_metrics(result)

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Services", metrics.total_services)
    col2.metric("Active", metrics.active_services)
    col3.metric("Delayed", metrics.delayed_services)
    col4.metric("Cancelled", metrics.cancelled_services)
    col5.metric("Conflicts", metrics.conflicts)
    col6.metric("Warnings", metrics.warnings)

    col7, col8, col9, col10 = st.columns(4)
    col7.metric("Total Delay", metrics.total_delay_minutes)
    col8.metric("Average Delay", f"{metrics.average_delay_minutes:.1f}")
    col9.metric("Max Delay", metrics.max_delay_minutes)
    col10.metric("Conflict Minutes", metrics.total_conflict_minutes)


def render_timetable(df: pd.DataFrame) -> None:
    display_columns = [
        "service_label",
        "operator",
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
        use_container_width=True,
        hide_index=True,
    )


def render_conflicts(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No section conflicts detected.")
        return

    st.dataframe(df, use_container_width=True, hide_index=True)


def render_occupations(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No section occupation rows generated.")
        return

    st.dataframe(df, use_container_width=True, hide_index=True)


def render_breakdowns(result: SimulationResult, stations_by_id, routes_by_id) -> None:
    route_labels = {route_id: route.name for route_id, route in routes_by_id.items()}
    section_labels = {
        item.label: section_label(item.label, stations_by_id)
        for item in conflicts_by_section(result)
    }

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Services By Operator")
        st.dataframe(build_breakdown_dataframe(services_by_operator(result)), use_container_width=True, hide_index=True)
        st.subheader("Conflicts By Section")
        st.dataframe(
            build_breakdown_dataframe(conflicts_by_section(result), section_labels),
            use_container_width=True,
            hide_index=True,
        )

    with col2:
        st.subheader("Services By Route")
        st.dataframe(
            build_breakdown_dataframe(services_by_route(result), route_labels),
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Conflicts By Day")
        st.dataframe(build_breakdown_dataframe(conflicts_by_day(result)), use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Grimsby-London Rail Simulation", layout="wide")
    st.title("Grimsby-London Rail Simulation")

    st.sidebar.header("Data")
    if st.sidebar.button("Reload data"):
        st.cache_data.clear()
        st.rerun()

    infrastructure, services = load_app_data(data_file_signature())
    stations_by_id = station_lookup(infrastructure.stations)
    routes_by_id = route_lookup(infrastructure.routes)
    disruptions = render_disruption_controls(services, stations_by_id)
    simulation_result = run_simulation(services, infrastructure, disruptions)

    if simulation_result.warnings:
        for warning in simulation_result.warnings:
            st.warning(warning)

    simulated_services = [simulated.service for simulated in simulation_result.services]
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
        service_status=service_status,
        service_delays=service_delays,
    )
    filtered_df = render_filters(df)
    conflicts_df = build_conflicts_dataframe(simulation_result, stations_by_id)
    occupations_df = build_occupations_dataframe(simulation_result, stations_by_id, routes_by_id)

    render_metric_cards(simulation_result)

    timetable_tab, conflicts_tab, occupations_tab, metrics_tab = st.tabs(
        ["Timetable", "Conflicts", "Section Occupations", "Metrics"]
    )
    with timetable_tab:
        render_timetable(filtered_df)
    with conflicts_tab:
        render_conflicts(conflicts_df)
    with occupations_tab:
        render_occupations(occupations_df)
    with metrics_tab:
        render_breakdowns(simulation_result, stations_by_id, routes_by_id)


if __name__ == "__main__":
    main()
