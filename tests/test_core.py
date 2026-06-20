from fastapi.testclient import TestClient

from src.api.main import app
from src.predict import impact_score_from_components, parse_event_datetime
from src.recommend import recommend_plan, risk_level


def test_risk_level_boundaries():
    assert risk_level(0) == "Low"
    assert risk_level(30) == "Low"
    assert risk_level(31) == "Medium"
    assert risk_level(60) == "Medium"
    assert risk_level(61) == "High"
    assert risk_level(80) == "High"
    assert risk_level(81) == "Critical"


def test_impact_score_formula():
    score = impact_score_from_components(
        road_closure_probability=0.8,
        high_priority_probability=0.6,
        historical_hotspot_score=0.5,
        duration_hours=12,
    )
    assert score == 66.0


def test_recommendation_for_vip_high_impact():
    plan = recommend_plan("vip_movement", impact_score=78, road_closure_probability=0.7, expected_duration_hours=4)
    assert plan.barricading_required is True
    assert plan.diversion_required is True
    assert plan.recommended_manpower_count >= 30
    assert plan.response_team_type == "traffic_police_plus_event_control"


def test_datetime_parser_falls_back_for_invalid_input():
    parsed = parse_event_datetime("not-a-date")
    assert parsed.tzinfo is not None
    assert str(parsed.tzinfo) == "Asia/Kolkata"


def test_predict_impact_endpoint_contract():
    client = TestClient(app)
    response = client.post(
        "/predict-impact",
        json={
            "event_type": "unplanned",
            "event_cause": "tree_fall",
            "latitude": 13.0061,
            "longitude": 77.5794,
            "start_datetime": "2024-04-08T08:15:00+05:30",
            "corridor": "Non-corridor",
            "police_station": "Sadashivanagar",
            "zone": "Central Zone",
            "junction": "BashyamCircle",
            "description": "Tree fall blocking one lane after heavy rain",
            "operating_mode": "balanced",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert 0 <= payload["impact_score"] <= 100
    assert payload["risk_level"] in {"Low", "Medium", "High", "Critical"}
    assert "road_closure_probability" in payload
    assert len(payload["score_components"]) == 4
    assert payload["top_prediction_factors"]
    assert payload["diversion_plan"]["diversion_type"] in {
        "NO_DIVERSION",
        "LOCAL_TRAFFIC_CONTROL",
        "PARTIAL_DIVERSION",
        "FULL_DIVERSION_REQUIRED",
    }
    assert payload["closure_decision"]["operating_mode"] == "balanced"
    assert "prediction_confidence" in payload
    assert 0 <= payload["prediction_confidence"]["confidence_score"] <= 100
    assert payload["similar_event_evidence"]["sample_size"] == len(payload["similar_past_events"])
    assert payload["action_timeline"]
    assert payload["incident_report"]["report_id"].startswith("EGRID-")
    assert isinstance(payload["similar_past_events"], list)


def test_live_event_approval_flow():
    client = TestClient(app)
    response = client.post(
        "/live-events",
        json={
            "event_type": "unplanned",
            "event_cause": "water_logging",
            "latitude": 12.9219,
            "longitude": 77.6452,
            "start_datetime": "2024-04-08T09:15:00+05:30",
            "corridor": "ORR East 1",
            "police_station": "HSR Layout",
            "zone": "South East Zone",
            "junction": "AgaraJunction",
            "description": "Water logging reported after heavy rain",
            "operating_mode": "high_recall",
        },
    )
    assert response.status_code == 200
    live_event = response.json()
    assert live_event["approval_status"] == "pending"

    approval = client.post(
        f"/live-events/{live_event['id']}/approval",
        json={"status": "approved", "reviewer": "test_operator", "note": "validated in test"},
    )
    assert approval.status_code == 200
    assert approval.json()["approval_status"] == "approved"

    summary = client.get("/monitoring/summary")
    assert summary.status_code == 200
    assert summary.json()["operations"]["live_events_total"] >= 1
