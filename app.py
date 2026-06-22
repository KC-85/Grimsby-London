from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from simulation.disruption import (
    DwellExtension,
    ServiceCancellation,
    ServiceDelay,
    apply_disruptions,
)
from simulation.infrastructure import load_infrastructure, station_lookup
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
    service_status: dict[str, str] | None = None,
    service_delays: dict[str, int] | None = None,
) -> pd.DataFrame:
    rows = flatten_services(services)
    df = pd.DataFrame(rows)
    df["station"] = df["station_id"].map(lambda station_id: stations_by_id[station_id].name)
    df["service_label"] = df["service_id"].str.replace("tpe-", "", regex=False)
    df["status"] = df["service_id"].map(service_status or {}).fillna("scheduled")
    df["delay_minutes"] = df["service_id"].map(service_delays or {}).fillna(0).astype(int)
    return df


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
    directions = sorted(df["direction"].unique())
    statuses = sorted(df["status"].unique())

    selected_day = st.sidebar.selectbox("Day", days)
    selected_direction = st.sidebar.selectbox("Direction", directions)
    selected_statuses = st.sidebar.multiselect("Status", statuses, default=statuses)

    return df[
        df["service_days"].str.contains(selected_day, regex=False)
        & (df["direction"] == selected_direction)
        & df["status"].isin(selected_statuses)
    ]


def render_metrics(df: pd.DataFrame, infrastructure) -> None:
    filtered_services = df["service_id"].nunique()
    cancelled_services = df.loc[df["status"] == "cancelled", "service_id"].nunique()
    delayed_services = df.loc[df["status"] == "delayed", "service_id"].nunique()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Services Shown", filtered_services)
    col2.metric("Delayed", delayed_services)
    col3.metric("Cancelled", cancelled_services)
    col4.metric("Timetable Rows", len(df))
    col5.metric("Stations", len(infrastructure.stations))
    col6.metric("Routes", len(infrastructure.routes))


def render_timetable(df: pd.DataFrame) -> None:
    st.subheader("Timetable")

    display_columns = [
        "service_label",
        "operator",
        "direction",
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


def main() -> None:
    st.set_page_config(page_title="Grimsby-London Rail Simulation", layout="wide")
    st.title("Grimsby-London Rail Simulation")

    st.sidebar.header("Data")
    if st.sidebar.button("Reload data"):
        st.cache_data.clear()
        st.rerun()

    infrastructure, services = load_app_data(data_file_signature())
    stations_by_id = station_lookup(infrastructure.stations)
    disruptions = render_disruption_controls(services, stations_by_id)
    disruption_result = apply_disruptions(services, disruptions)

    if disruption_result.warnings:
        for warning in disruption_result.warnings:
            st.warning(warning)

    simulated_services = [simulated.service for simulated in disruption_result.services]
    service_status = {
        simulated.service.id: simulated.status.value
        for simulated in disruption_result.services
    }
    service_delays = {
        simulated.service.id: simulated.delay_minutes
        for simulated in disruption_result.services
    }

    df = build_timetable_dataframe(
        simulated_services,
        stations_by_id,
        service_status=service_status,
        service_delays=service_delays,
    )
    filtered_df = render_filters(df)

    render_metrics(filtered_df, infrastructure)
    render_timetable(filtered_df)


if __name__ == "__main__":
    main()
