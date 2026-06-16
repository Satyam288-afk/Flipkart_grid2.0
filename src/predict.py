from __future__ import annotations

import hashlib
import json
from datetime import datetime, UTC
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd

from .config import LOCAL_TZ, MODEL_BUNDLE_PATH
from .data_processing import normalize_category
from .recommend import recommend_plan, risk_level


def parse_event_datetime(value: str | None) -> pd.Timestamp:
    if value:
        parsed = pd.to_datetime(value, errors="coerce", utc=True, format="mixed")
    else:
        parsed = pd.Timestamp.now(tz="UTC")
    if pd.isna(parsed):
        parsed = pd.Timestamp.now(tz="UTC")
    return parsed.tz_convert(LOCAL_TZ)


@lru_cache(maxsize=1)
def load_model_bundle() -> dict:
    if not MODEL_BUNDLE_PATH.exists():
        from .train import train

        train()
    return joblib.load(MODEL_BUNDLE_PATH)


def predict_probability(model, features: pd.DataFrame) -> float:
    if hasattr(model, "predict_proba"):
        return float(model.predict_proba(features)[0][1])
    return float(np.clip(model.predict(features)[0], 0, 1))


def event_to_frame(payload: dict) -> pd.DataFrame:
    start = parse_event_datetime(payload.get("start_datetime"))
    return pd.DataFrame(
        [
            {
                "event_type": normalize_category(payload.get("event_type", "unplanned")),
                "event_cause": normalize_category(payload.get("event_cause", "unknown")),
                "latitude": payload.get("latitude"),
                "longitude": payload.get("longitude"),
                "start_datetime": start,
                "corridor": normalize_category(payload.get("corridor", "unknown")),
                "police_station": normalize_category(payload.get("police_station", "unknown")),
                "zone": normalize_category(payload.get("zone", "unknown")),
                "junction": normalize_category(payload.get("junction", "unknown")),
                "description": payload.get("description") or "",
                "veh_type": normalize_category(payload.get("veh_type", "unknown")),
                "direction": normalize_category(payload.get("direction", "unknown")),
            }
        ]
    )


def expected_duration_hours(bundle: dict, features: pd.DataFrame) -> float:
    model = bundle.get("duration_model")
    builder = bundle["feature_builder"]
    if model is None:
        return float(builder.median_duration_hours)
    return float(np.expm1(model.predict(features)[0]).clip(0, 168))


def similar_events(bundle: dict, payload: dict, limit: int = 5) -> list[dict]:
    history = bundle["history_df"].copy()
    if history.empty:
        return []

    lat = float(payload.get("latitude") or history["latitude"].median())
    lon = float(payload.get("longitude") or history["longitude"].median())
    cause = normalize_category(payload.get("event_cause", "unknown"))

    history["distance_score"] = np.sqrt((history["latitude"] - lat) ** 2 + (history["longitude"] - lon) ** 2)
    history["cause_match"] = history["event_cause"].eq(cause).astype(int)
    selected = history.sort_values(["cause_match", "distance_score"], ascending=[False, True]).head(limit)
    records = []
    for _, row in selected.iterrows():
        records.append(
            {
                "id": row.get("id"),
                "event_cause": row.get("event_cause"),
                "corridor": row.get("corridor"),
                "police_station": row.get("police_station"),
                "priority": row.get("priority"),
                "requires_road_closure": bool(row.get("requires_road_closure")),
                "duration_hours": None if pd.isna(row.get("duration_hours")) else round(float(row.get("duration_hours")), 2),
                "start_datetime": str(row.get("start_datetime")),
            }
        )
    return records


def similar_event_evidence(events: list[dict]) -> dict:
    if not events:
        return {
            "sample_size": 0,
            "closure_count": 0,
            "closure_rate": 0.0,
            "high_priority_count": 0,
            "average_duration_hours": None,
        }

    durations = [event["duration_hours"] for event in events if event.get("duration_hours") is not None]
    closure_count = sum(1 for event in events if event.get("requires_road_closure"))
    high_priority_count = sum(1 for event in events if str(event.get("priority")).lower() == "high")
    return {
        "sample_size": len(events),
        "closure_count": closure_count,
        "closure_rate": round(closure_count / len(events), 3),
        "high_priority_count": high_priority_count,
        "average_duration_hours": round(float(np.mean(durations)), 2) if durations else None,
    }


def impact_score_from_components(
    road_closure_probability: float,
    high_priority_probability: float,
    historical_hotspot_score: float,
    duration_hours: float,
) -> float:
    duration_score = min(max(duration_hours / 24.0, 0.0), 1.0)
    score = 100 * (
        0.45 * road_closure_probability
        + 0.25 * high_priority_probability
        + 0.20 * historical_hotspot_score
        + 0.10 * duration_score
    )
    return round(float(np.clip(score, 0, 100)), 2)


def impact_components(
    road_closure_probability: float,
    high_priority_probability: float,
    historical_hotspot_score: float,
    duration_hours: float,
) -> list[dict]:
    duration_score = min(max(duration_hours / 24.0, 0.0), 1.0)
    raw_components = [
        {
            "name": "Road closure risk",
            "weight": 0.45,
            "value": road_closure_probability,
            "reason": "Primary supervised target from historical operations records.",
        },
        {
            "name": "High priority risk",
            "weight": 0.25,
            "value": high_priority_probability,
            "reason": "Secondary severity signal from event priority labels.",
        },
        {
            "name": "Historical hotspot",
            "weight": 0.20,
            "value": historical_hotspot_score,
            "reason": "Past closure rates and event density for cause, corridor, police station, and geobin.",
        },
        {
            "name": "Expected duration",
            "weight": 0.10,
            "value": duration_score,
            "reason": "Duration estimate normalized to a 24-hour operational response window.",
        },
    ]
    return [
        {
            **component,
            "value": round(float(component["value"]), 4),
            "weighted_points": round(100 * component["weight"] * float(component["value"]), 2),
        }
        for component in raw_components
    ]


def action_timeline(
    risk: str,
    event_cause: str,
    barricading_required: bool,
    diversion_required: bool,
    response_team_type: str,
) -> list[dict]:
    cause = event_cause or "unknown"
    timeline = [
        {
            "offset_minutes": 0,
            "title": "Acknowledge and classify incident",
            "owner": "control_room",
            "action": f"Register {cause} event and publish the impact score to the duty officer.",
        },
        {
            "offset_minutes": 5,
            "title": "Dispatch field response",
            "owner": response_team_type,
            "action": "Send response team with location, corridor, police station, and similar-event evidence.",
        },
    ]
    if barricading_required:
        timeline.append(
            {
                "offset_minutes": 10,
                "title": "Prepare lane control",
                "owner": "traffic_police",
                "action": "Place temporary barricades and protect the response work area.",
            }
        )
    if diversion_required:
        timeline.append(
            {
                "offset_minutes": 15,
                "title": "Activate diversion plan",
                "owner": "junction_team",
                "action": "Move vehicles away from the affected corridor and monitor spillback at feeder junctions.",
            }
        )
    timeline.append(
        {
            "offset_minutes": 30 if risk in {"High", "Critical"} else 45,
            "title": "Reassess and update",
            "owner": "field_supervisor",
            "action": "Update closure status, manpower need, and estimated clearance time.",
        }
    )
    return timeline


def make_report_id(payload: dict, response: dict) -> str:
    stable_payload = {
        "event": payload,
        "impact_score": response["impact_score"],
        "risk_level": response["risk_level"],
        "generated_at": response["generated_at"],
    }
    digest = hashlib.sha256(json.dumps(stable_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"EGRID-{digest[:12].upper()}"


def predict_impact(payload: dict) -> dict:
    bundle = load_model_bundle()
    builder = bundle["feature_builder"]
    frame = event_to_frame(payload)
    features = builder.transform(frame)

    road_probability = predict_probability(bundle["closure_model"], features)
    priority_probability = predict_probability(bundle["priority_model"], features)
    duration = expected_duration_hours(bundle, features)
    hotspot = builder.hotspot_score_for_event(frame)
    score = impact_score_from_components(road_probability, priority_probability, hotspot, duration)
    level = risk_level(score)
    recommendation = recommend_plan(frame["event_cause"].iloc[0], score, road_probability, duration)
    components = impact_components(road_probability, priority_probability, hotspot, duration)
    past_events = similar_events(bundle, payload)
    evidence = similar_event_evidence(past_events)
    timeline = action_timeline(
        level,
        frame["event_cause"].iloc[0],
        recommendation.barricading_required,
        recommendation.diversion_required,
        recommendation.response_team_type,
    )

    explanation = [
        f"Road closure probability contributes 45 percent of score: {road_probability:.2f}.",
        f"High priority probability contributes 25 percent of score: {priority_probability:.2f}.",
        f"Historical hotspot score contributes 20 percent of score: {hotspot:.2f}.",
        f"Expected duration contributes 10 percent of score: {duration:.1f} hours.",
        *recommendation.explanation,
    ]

    response = {
        "generated_at": datetime.now(UTC).isoformat(),
        "impact_score": score,
        "risk_level": level,
        "road_closure_probability": round(road_probability, 4),
        "high_priority_probability": round(priority_probability, 4),
        "historical_hotspot_score": round(hotspot, 4),
        "score_components": components,
        "expected_duration_hours": round(duration, 2),
        "recommended_manpower": recommendation.recommended_manpower_count,
        "barricading_required": recommendation.barricading_required,
        "diversion_required": recommendation.diversion_required,
        "response_team_type": recommendation.response_team_type,
        "action_timeline": timeline,
        "explanation": explanation,
        "similar_past_events": past_events,
        "similar_event_evidence": evidence,
        "model_note": "Operational impact estimate based on event closure risk, priority risk, hotspot history, and duration. It is not an exact traffic speed forecast.",
    }
    response["incident_report"] = {
        "report_id": make_report_id(payload, response),
        "event": payload,
        "impact_score": response["impact_score"],
        "risk_level": response["risk_level"],
        "recommendation": {
            "recommended_manpower": response["recommended_manpower"],
            "barricading_required": response["barricading_required"],
            "diversion_required": response["diversion_required"],
            "response_team_type": response["response_team_type"],
        },
        "score_components": response["score_components"],
        "similar_event_evidence": response["similar_event_evidence"],
        "generated_at": response["generated_at"],
        "model_note": response["model_note"],
    }
    return response


def hotspots(limit: int = 20) -> list[dict]:
    bundle = load_model_bundle()
    history = bundle["history_df"].copy()
    if history.empty:
        return []
    grouped = (
        history.groupby(["event_cause", "corridor", "police_station"], dropna=False)
        .agg(
            event_count=("id", "count"),
            closure_rate=("requires_road_closure", "mean"),
            avg_latitude=("latitude", "mean"),
            avg_longitude=("longitude", "mean"),
        )
        .reset_index()
    )
    grouped["hotspot_score"] = (0.65 * grouped["closure_rate"] + 0.35 * (grouped["event_count"] / grouped["event_count"].max())).clip(0, 1)
    grouped = grouped.sort_values("hotspot_score", ascending=False).head(limit)
    return [
        {
            "event_cause": row.event_cause,
            "corridor": row.corridor,
            "police_station": row.police_station,
            "event_count": int(row.event_count),
            "closure_rate": round(float(row.closure_rate), 3),
            "latitude": round(float(row.avg_latitude), 6) if pd.notna(row.avg_latitude) else None,
            "longitude": round(float(row.avg_longitude), 6) if pd.notna(row.avg_longitude) else None,
            "hotspot_score": round(float(row.hotspot_score), 3),
        }
        for row in grouped.itertuples()
    ]
