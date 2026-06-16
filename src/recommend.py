from __future__ import annotations

from dataclasses import dataclass


CRITICAL_CAUSES = {"vip_movement", "procession", "public_event", "protest"}
CLEARANCE_CAUSES = {"tree_fall", "water_logging", "accident", "road_conditions", "pot_holes", "debris"}


@dataclass(frozen=True)
class Recommendation:
    recommended_manpower_count: int
    barricading_required: bool
    diversion_required: bool
    response_team_type: str
    explanation: list[str]


def risk_level(impact_score: float) -> str:
    if impact_score <= 30:
        return "Low"
    if impact_score <= 60:
        return "Medium"
    if impact_score <= 80:
        return "High"
    return "Critical"


def recommend_plan(
    event_cause: str,
    impact_score: float,
    road_closure_probability: float,
    expected_duration_hours: float,
) -> Recommendation:
    cause = (event_cause or "unknown").lower()
    explanations: list[str] = []

    if cause in CRITICAL_CAUSES and impact_score > 70:
        explanations.append("Planned crowd or VIP movement with high predicted operational impact.")
        return Recommendation(34, True, True, "traffic_police_plus_event_control", explanations)

    if cause in CLEARANCE_CAUSES:
        manpower = 18 if impact_score > 60 else 10
        explanations.append("Clearance-sensitive incident type needs field response and temporary traffic control.")
        return Recommendation(
            manpower,
            road_closure_probability > 0.35 or impact_score > 55,
            impact_score > 65,
            "emergency_clearance_team",
            explanations,
        )

    if cause == "vehicle_breakdown":
        explanations.append("Breakdown events usually need quick clearance and queue management.")
        return Recommendation(
            8 if impact_score <= 60 else 14,
            impact_score > 60,
            impact_score > 75,
            "tow_vehicle_quick_response",
            explanations,
        )

    if cause == "construction":
        explanations.append("Construction impact depends heavily on duration and corridor history.")
        return Recommendation(
            16 if expected_duration_hours >= 6 or impact_score > 60 else 9,
            True,
            expected_duration_hours >= 6 or impact_score > 65,
            "planned_barricading_team",
            explanations,
        )

    if impact_score > 80:
        explanations.append("Critical composite impact score requires diversion-ready deployment.")
        return Recommendation(28, True, True, "senior_traffic_control_unit", explanations)

    if impact_score > 60:
        explanations.append("High impact score suggests proactive manpower and barricade readiness.")
        return Recommendation(16, True, True, "traffic_response_team", explanations)

    if impact_score > 30:
        explanations.append("Moderate event impact can be handled with quick response monitoring.")
        return Recommendation(8, False, False, "quick_response_patrol", explanations)

    explanations.append("Low operational impact predicted from closure risk and hotspot history.")
    return Recommendation(4, False, False, "monitoring_unit", explanations)
