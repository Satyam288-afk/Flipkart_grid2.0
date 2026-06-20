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


def calibrated_probability(bundle: dict, raw_probability: float) -> float:
    if not bundle.get("use_closure_calibrator", False):
        return raw_probability
    calibrator = bundle.get("closure_calibrator")
    if calibrator is None:
        return raw_probability
    return float(calibrator.predict([raw_probability])[0])


def operating_threshold(bundle: dict, mode: str | None) -> tuple[str, float]:
    normalized = (mode or "balanced").lower()
    aliases = {
        "balanced_f1": "balanced",
        "balanced": "balanced",
        "high_recall_operations": "high_recall",
        "high_recall": "high_recall",
        "high_precision_operations": "high_precision",
        "high_precision": "high_precision",
    }
    selected = aliases.get(normalized, "balanced")
    points = bundle.get("metrics", {}).get("operating_points", {})
    fallback = {"balanced": 0.75, "high_recall": 0.35, "high_precision": 0.85}
    threshold = points.get(selected, {}).get("threshold", fallback[selected])
    return selected, float(threshold)


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


def prediction_confidence(
    bundle: dict,
    frame: pd.DataFrame,
    similar_evidence: dict,
    road_probability: float,
    threshold: float,
) -> dict:
    builder = bundle["feature_builder"]
    event = frame.iloc[0]
    score = 20
    reasons = []

    cause = event.get("event_cause", "unknown")
    corridor = event.get("corridor", "unknown")
    police_station = event.get("police_station", "unknown")

    if cause in builder.cause_rates:
        score += 20
        reasons.append("Event cause exists in historical training patterns.")
    else:
        reasons.append("Event cause is sparse or unseen in historical training patterns.")

    if corridor in builder.corridor_rates:
        score += 15
        reasons.append("Corridor has historical closure-rate coverage.")
    if police_station in builder.police_rates:
        score += 15
        reasons.append("Police station has historical closure-rate coverage.")

    sample_size = similar_evidence.get("sample_size", 0)
    if sample_size >= 5:
        score += 20
        reasons.append("At least five similar historical events were found.")
    elif sample_size > 0:
        score += 10
        reasons.append("Some similar historical events were found.")

    margin = abs(road_probability - threshold)
    if margin >= 0.25:
        score += 10
        reasons.append("Closure probability is far from the selected operating threshold.")
    elif margin < 0.08:
        score -= 5
        reasons.append("Closure probability is close to the selected operating threshold.")

    score = int(np.clip(score, 0, 100))
    if score >= 75:
        level = "High"
    elif score >= 50:
        level = "Medium"
    else:
        level = "Low"
    return {"confidence_score": score, "confidence_level": level, "reasons": reasons}


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


def top_prediction_factors(
    frame: pd.DataFrame,
    components: list[dict],
    similar_evidence: dict,
    duration_hours: float,
) -> list[dict]:
    event = frame.iloc[0]
    factors = []

    for component in sorted(components, key=lambda item: item["weighted_points"], reverse=True):
        factors.append(
            {
                "factor": component["name"],
                "direction": "increases impact" if component["weighted_points"] >= 8 else "moderate signal",
                "strength": component["weighted_points"],
                "evidence": component["reason"],
            }
        )

    cause = str(event.get("event_cause", "unknown"))
    description = str(event.get("description", "")).lower()
    keyword_hits = [word for word in ["vip", "procession", "blocked", "tree", "water", "breakdown", "accident", "construction"] if word in description]
    if keyword_hits:
        factors.append(
            {
                "factor": "Description keywords",
                "direction": "increases impact",
                "strength": min(12, 4 * len(keyword_hits)),
                "evidence": f"Matched operational keywords: {', '.join(keyword_hits)}.",
            }
        )

    if similar_evidence.get("sample_size", 0) > 0:
        factors.append(
            {
                "factor": "Similar historical cases",
                "direction": "context signal",
                "strength": round(10 * similar_evidence.get("closure_rate", 0), 2),
                "evidence": f"{similar_evidence['closure_count']} of {similar_evidence['sample_size']} nearest similar events required road closure.",
            }
        )

    if cause in {"vip_movement", "procession", "public_event", "protest"}:
        factors.append(
            {
                "factor": "Planned crowd movement",
                "direction": "increases response readiness",
                "strength": 9,
                "evidence": "Crowd-control event types usually need pre-positioned officers and diversion readiness.",
            }
        )

    if duration_hours >= 6:
        factors.append(
            {
                "factor": "Long expected duration",
                "direction": "increases impact",
                "strength": min(15, round(duration_hours / 2, 2)),
                "evidence": "Longer incident windows increase exposure to peak-hour congestion and require sustained deployment.",
            }
        )

    return sorted(factors, key=lambda item: item["strength"], reverse=True)[:5]


def diversion_plan(
    payload: dict,
    event_cause: str,
    impact_score: float,
    road_closure_probability: float,
    hotspot_score: float,
    duration_hours: float,
) -> dict:
    cause = event_cause or "unknown"
    corridor = payload.get("corridor") or "unknown corridor"
    junction = payload.get("junction") or "nearest affected junction"
    police_station = payload.get("police_station") or "local traffic police station"

    if impact_score >= 80 or road_closure_probability >= 0.75:
        diversion_type = "FULL_DIVERSION_REQUIRED"
        strategy = "Prepare corridor-level diversion and restrict through-traffic near the affected junction."
    elif impact_score >= 65 or cause in {"vip_movement", "procession", "public_event"}:
        diversion_type = "PARTIAL_DIVERSION"
        strategy = "Keep one diversion corridor ready and meter feeder-road inflow while field teams verify closure need."
    elif impact_score >= 40 or hotspot_score >= 0.35 or duration_hours >= 4:
        diversion_type = "LOCAL_TRAFFIC_CONTROL"
        strategy = "Use local traffic control at upstream and downstream junctions; activate diversion only if queues spill back."
    else:
        diversion_type = "NO_DIVERSION"
        strategy = "Monitor with patrol presence; no proactive diversion recommended from current operational evidence."

    control_points = [
        f"Upstream approach to {junction}",
        f"Downstream approach from {junction}",
        f"{police_station} field coordination point",
    ]

    return {
        "diversion_type": diversion_type,
        "affected_corridor": corridor,
        "primary_control_junction": junction,
        "control_points": control_points,
        "strategy": strategy,
        "operator_note": "This is a corridor-level operational suggestion, not live turn-by-turn navigation. Production routing needs a road graph or maps API.",
    }


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

    road_raw_probability = predict_probability(bundle["closure_model"], features)
    road_probability = calibrated_probability(bundle, road_raw_probability)
    priority_probability = predict_probability(bundle["priority_model"], features)
    duration = expected_duration_hours(bundle, features)
    hotspot = builder.hotspot_score_for_event(frame)
    score = impact_score_from_components(road_probability, priority_probability, hotspot, duration)
    level = risk_level(score)
    recommendation = recommend_plan(frame["event_cause"].iloc[0], score, road_probability, duration)
    components = impact_components(road_probability, priority_probability, hotspot, duration)
    past_events = similar_events(bundle, payload)
    evidence = similar_event_evidence(past_events)
    mode, threshold = operating_threshold(bundle, payload.get("operating_mode"))
    top_factors = top_prediction_factors(frame, components, evidence, duration)
    route_plan = diversion_plan(payload, frame["event_cause"].iloc[0], score, road_probability, hotspot, duration)
    confidence = prediction_confidence(bundle, frame, evidence, road_probability, threshold)
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
        "road_closure_probability_raw": round(road_raw_probability, 4),
        "high_priority_probability": round(priority_probability, 4),
        "historical_hotspot_score": round(hotspot, 4),
        "score_components": components,
        "top_prediction_factors": top_factors,
        "expected_duration_hours": round(duration, 2),
        "recommended_manpower": recommendation.recommended_manpower_count,
        "barricading_required": recommendation.barricading_required,
        "diversion_required": recommendation.diversion_required,
        "diversion_plan": route_plan,
        "closure_decision": {
            "operating_mode": mode,
            "threshold": round(threshold, 4),
            "closure_flag": bool(road_probability >= threshold),
            "margin": round(float(road_probability - threshold), 4),
        },
        "prediction_confidence": confidence,
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
            "diversion_plan": response["diversion_plan"],
            "response_team_type": response["response_team_type"],
        },
        "score_components": response["score_components"],
        "top_prediction_factors": response["top_prediction_factors"],
        "similar_event_evidence": response["similar_event_evidence"],
        "prediction_confidence": response["prediction_confidence"],
        "closure_decision": response["closure_decision"],
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
