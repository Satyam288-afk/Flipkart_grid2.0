from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .config import DATA_PATH, LOCAL_TZ


DATETIME_COLUMNS = [
    "start_datetime",
    "end_datetime",
    "created_date",
    "modified_datetime",
    "closed_datetime",
    "resolved_datetime",
]

POST_OUTCOME_COLUMNS = {
    "status",
    "modified_datetime",
    "closed_datetime",
    "resolved_datetime",
    "resolved_by_id",
    "closed_by_id",
    "last_modified_by_id",
    "created_by_id",
    "veh_no",
    "vehicle_number",
    "vehicle number",
    "kgid",
    "client_id",
    "resolved_at_address",
    "resolved_at_latitude",
    "resolved_at_longitude",
    "comment",
    "assigned_to_police_id",
    "citizen_accident_id",
    "map_file",
    "route_path",
    "meta_data",
    "gba_identifier",
}


def normalize_column_name(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def normalize_category(value: object, default: str = "unknown") -> str:
    if pd.isna(value):
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return (
        text.replace("/", " ")
        .replace("-", " ")
        .replace("&", " and ")
        .replace("__", "_")
        .replace(" ", "_")
    )


def parse_datetime_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
    return parsed.dt.tz_convert(LOCAL_TZ)


def coerce_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    true_values = {"true", "1", "yes", "y", "t"}
    return series.astype(str).str.strip().str.lower().isin(true_values)


def load_events(path: Path | str = DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [normalize_column_name(c) for c in df.columns]

    for col in DATETIME_COLUMNS:
        if col in df.columns:
            df[col] = parse_datetime_series(df[col])

    for col in ["latitude", "longitude", "endlatitude", "endlongitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["endlatitude", "endlongitude"]:
        if col in df.columns:
            df.loc[df[col].eq(0.0), col] = np.nan

    if "requires_road_closure" in df.columns:
        df["requires_road_closure"] = coerce_bool(df["requires_road_closure"])

    for col in [
        "event_type",
        "event_cause",
        "corridor",
        "police_station",
        "zone",
        "junction",
        "priority",
        "direction",
        "veh_type",
    ]:
        if col in df.columns:
            df[col] = df[col].map(normalize_category)

    if "description" in df.columns:
        df["description"] = df["description"].fillna("").astype(str)
    else:
        df["description"] = ""

    if "start_datetime" in df.columns:
        df = df[df["start_datetime"].notna()].copy()
        df = df.sort_values("start_datetime").reset_index(drop=True)

    return df


def compute_duration_hours(df: pd.DataFrame) -> pd.Series:
    if "start_datetime" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    end = None
    for col in ["end_datetime", "closed_datetime", "resolved_datetime"]:
        if col in df.columns:
            end = df[col] if end is None else end.fillna(df[col])

    if end is None:
        return pd.Series(np.nan, index=df.index)

    duration = (end - df["start_datetime"]).dt.total_seconds() / 3600
    duration = duration.where((duration > 0) & (duration <= 168))
    return duration


def drop_leakage_columns(df: pd.DataFrame, extra: Iterable[str] | None = None) -> pd.DataFrame:
    drop_cols = set(POST_OUTCOME_COLUMNS)
    if extra:
        drop_cols.update(extra)
    existing = [col for col in drop_cols if col in df.columns]
    return df.drop(columns=existing)


def clean_feature_table(path: Path | str = DATA_PATH) -> pd.DataFrame:
    df = load_events(path)
    df["duration_hours"] = compute_duration_hours(df)
    return drop_leakage_columns(df)


if __name__ == "__main__":
    events = clean_feature_table()
    print(events.head().to_string())
    print(events.shape)
