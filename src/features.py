from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data_processing import normalize_category


CATEGORICAL_COLUMNS = [
    "event_type",
    "event_cause",
    "corridor",
    "police_station",
    "zone",
    "junction",
    "veh_type",
    "direction",
]

KEYWORDS = [
    "accident",
    "water",
    "heavy",
    "blocked",
    "breakdown",
    "tree",
    "vip",
    "procession",
    "construction",
]

NUMERIC_FEATURES = [
    "latitude",
    "longitude",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "month",
    "description_length",
    "cause_closure_rate",
    "corridor_closure_rate",
    "police_station_closure_rate",
    "geo_event_frequency",
    "historical_hotspot_score",
]


def add_base_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in CATEGORICAL_COLUMNS:
        if col not in out.columns:
            out[col] = "unknown"
        out[col] = out[col].map(normalize_category).fillna("unknown")

    out["latitude"] = pd.to_numeric(out.get("latitude"), errors="coerce")
    out["longitude"] = pd.to_numeric(out.get("longitude"), errors="coerce")
    out["description"] = out.get("description", "").fillna("").astype(str)

    start = out["start_datetime"]
    out["hour_of_day"] = start.dt.hour.fillna(0).astype(int)
    out["day_of_week"] = start.dt.dayofweek.fillna(0).astype(int)
    out["is_weekend"] = out["day_of_week"].isin([5, 6]).astype(int)
    out["month"] = start.dt.month.fillna(1).astype(int)

    out["geo_bin"] = (
        out["latitude"].round(3).fillna(0).astype(str)
        + "_"
        + out["longitude"].round(3).fillna(0).astype(str)
    )
    out["description_length"] = out["description"].str.len().clip(0, 1000)
    text = out["description"].str.lower()
    for keyword in KEYWORDS:
        out[f"kw_{keyword}"] = text.str.contains(keyword, regex=False).astype(int)

    return out


@dataclass
class FeatureBuilder:
    global_closure_rate: float = 0.0
    cause_rates: dict[str, float] = field(default_factory=dict)
    corridor_rates: dict[str, float] = field(default_factory=dict)
    police_rates: dict[str, float] = field(default_factory=dict)
    geo_freq: dict[str, float] = field(default_factory=dict)
    median_duration_hours: float = 2.0
    latitude_median: float = 12.9716
    longitude_median: float = 77.5946

    @property
    def feature_columns(self) -> list[str]:
        return (
            CATEGORICAL_COLUMNS
            + ["geo_bin"]
            + NUMERIC_FEATURES
            + [f"kw_{keyword}" for keyword in KEYWORDS]
        )

    @property
    def categorical_indices(self) -> list[int]:
        return [self.feature_columns.index(col) for col in CATEGORICAL_COLUMNS + ["geo_bin"]]

    def fit(self, df: pd.DataFrame) -> "FeatureBuilder":
        base = add_base_features(df)
        y = base["requires_road_closure"].astype(int)
        self.global_closure_rate = float(y.mean()) if len(y) else 0.0
        self.cause_rates = y.groupby(base["event_cause"]).mean().to_dict()
        self.corridor_rates = y.groupby(base["corridor"]).mean().to_dict()
        self.police_rates = y.groupby(base["police_station"]).mean().to_dict()

        counts = base["geo_bin"].value_counts()
        max_count = max(float(counts.max()), 1.0) if len(counts) else 1.0
        self.geo_freq = (counts / max_count).to_dict()

        if "duration_hours" in base.columns:
            valid_duration = pd.to_numeric(base["duration_hours"], errors="coerce").dropna()
            if not valid_duration.empty:
                self.median_duration_hours = float(valid_duration.median())

        self.latitude_median = float(base["latitude"].median()) if base["latitude"].notna().any() else 12.9716
        self.longitude_median = float(base["longitude"].median()) if base["longitude"].notna().any() else 77.5946
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        base = add_base_features(df)
        base["latitude"] = base["latitude"].fillna(self.latitude_median)
        base["longitude"] = base["longitude"].fillna(self.longitude_median)
        base["cause_closure_rate"] = base["event_cause"].map(self.cause_rates).fillna(self.global_closure_rate)
        base["corridor_closure_rate"] = base["corridor"].map(self.corridor_rates).fillna(self.global_closure_rate)
        base["police_station_closure_rate"] = base["police_station"].map(self.police_rates).fillna(self.global_closure_rate)
        base["geo_event_frequency"] = base["geo_bin"].map(self.geo_freq).fillna(0.0)
        base["historical_hotspot_score"] = (
            0.45 * base["cause_closure_rate"]
            + 0.25 * base["corridor_closure_rate"]
            + 0.15 * base["police_station_closure_rate"]
            + 0.15 * base["geo_event_frequency"]
        ).clip(0, 1)

        for col in self.feature_columns:
            if col not in base.columns:
                base[col] = 0 if col not in CATEGORICAL_COLUMNS else "unknown"

        return base[self.feature_columns].copy()

    def hotspot_score_for_event(self, event: pd.DataFrame) -> float:
        features = self.transform(event)
        return float(features["historical_hotspot_score"].iloc[0])


def train_test_time_split(df: pd.DataFrame, train_fraction: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = df.sort_values("start_datetime").reset_index(drop=True)
    split_at = max(1, int(len(ordered) * train_fraction))
    split_at = min(split_at, len(ordered) - 1)
    return ordered.iloc[:split_at].copy(), ordered.iloc[split_at:].copy()
