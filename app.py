from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from simulation.infrastructure import load_infrastructure, station_lookup
from simulation.timetable import flatten_services, load_services


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


def build_timetable_dataframe(services, stations_by_id) -> pd.DataFrame:
    rows = flatten_services(services)
    df = pd.DataFrame(rows)
    df["station"] = df["station_id"].map(lambda station_id: stations_by_id[station_id].name)
    df["service_label"] = df["service_id"].str.replace("tpe-", "", regex=False)
    return df


def render_sidebar(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filters")

    days = sorted({day for value in df["service_days"] for day in value.split(", ")})
    directions = sorted(df["direction"].unique())

    selected_day = st.sidebar.selectbox("Day", days)
    selected_direction = st.sidebar.selectbox("Direction", directions)

    return df[
        df["service_days"].str.contains(selected_day, regex=False)
        & (df["direction"] == selected_direction)
    ]


def render_metrics(df: pd.DataFrame, infrastructure, services) -> None:
    filtered_services = df["service_id"].nunique()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Services Shown", filtered_services)
    col2.metric("Timetable Rows", len(df))
    col3.metric("Stations", len(infrastructure.stations))
    col4.metric("Routes", len(infrastructure.routes))


def render_timetable(df: pd.DataFrame) -> None:
    st.subheader("Timetable")

    display_columns = [
        "service_label",
        "operator",
        "direction",
        "station",
        "arrival",
        "departure",
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
    df = build_timetable_dataframe(services, stations_by_id)
    filtered_df = render_sidebar(df)

    render_metrics(filtered_df, infrastructure, services)
    render_timetable(filtered_df)


if __name__ == "__main__":
    main()
