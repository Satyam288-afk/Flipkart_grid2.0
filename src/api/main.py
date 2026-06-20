from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import FRONTEND_DIST_PATH
from src.predict import hotspots, load_model_bundle, predict_impact, similar_events
from src.recommend import recommend_plan
from src.security import auth_mode, require_api_key
from src.storage import audit_log, create_live_event, init_db, list_live_events, operational_summary, update_approval

logger = logging.getLogger(__name__)


class EventImpactRequest(BaseModel):
    event_type: str = "unplanned"
    event_cause: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    start_datetime: Optional[str] = None
    corridor: str = "unknown"
    police_station: str = "unknown"
    zone: str = "unknown"
    junction: str = "unknown"
    description: str = ""
    veh_type: str = "unknown"
    direction: str = "unknown"
    operating_mode: Literal["balanced", "high_recall", "high_precision"] = "balanced"


class RecommendPlanRequest(BaseModel):
    event_cause: str
    impact_score: float = Field(..., ge=0, le=100)
    road_closure_probability: float = Field(..., ge=0, le=1)
    expected_duration_hours: float = Field(2.0, ge=0)


class ApprovalRequest(BaseModel):
    status: Literal["approved", "rejected", "needs_review"]
    reviewer: str = Field("control_room_operator", min_length=1, max_length=80)
    note: str = Field("", max_length=500)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_model_bundle()
    yield


app = FastAPI(
    title="EventGrid AI",
    version="0.1.0",
    description="Operational traffic impact prediction for planned and unplanned events.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "eventgrid-ai", "auth_mode": auth_mode()}


@app.post("/predict-impact")
def predict_impact_endpoint(request: EventImpactRequest):
    try:
        return predict_impact(request.model_dump())
    except Exception as exc:
        logger.exception("Prediction failed")
        raise HTTPException(status_code=500, detail=f"Prediction failed: {type(exc).__name__}: {exc}") from exc


@app.post("/live-events", dependencies=[Depends(require_api_key)])
def create_live_event_endpoint(request: EventImpactRequest, source: str = "manual"):
    event_payload = request.model_dump()
    prediction = predict_impact(event_payload)
    return create_live_event(event_payload, prediction, source=source)


@app.get("/live-events")
def live_events_endpoint(limit: int = 20):
    return {"live_events": list_live_events(limit=limit)}


@app.post("/live-events/{live_event_id}/approval", dependencies=[Depends(require_api_key)])
def approve_live_event_endpoint(live_event_id: int, request: ApprovalRequest):
    updated = update_approval(live_event_id, request.status, request.reviewer, request.note)
    if updated is None:
        raise HTTPException(status_code=404, detail="Live event not found")
    return updated


@app.post("/simulate-live-feed", dependencies=[Depends(require_api_key)])
def simulate_live_feed_endpoint():
    scenarios = [
        {
            "event_type": "planned",
            "event_cause": "procession",
            "latitude": 12.9719,
            "longitude": 77.6412,
            "start_datetime": "2024-04-08T18:30:00+05:30",
            "corridor": "ORR East 1",
            "police_station": "Indiranagar",
            "zone": "East Zone",
            "junction": "IndiranagarJunction",
            "description": "Procession near junction with possible lane blocking",
        },
        {
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
        },
    ]
    created = []
    for scenario in scenarios:
        created.append(create_live_event(scenario, predict_impact(scenario), source="simulated_feed"))
    return {"created": created}


@app.get("/audit-log")
def audit_log_endpoint(limit: int = 50):
    return {"audit_log": audit_log(limit=limit)}


@app.get("/monitoring/summary")
def monitoring_summary_endpoint():
    bundle = load_model_bundle()
    return {
        "service": "eventgrid-ai",
        "auth_mode": auth_mode(),
        "model_type": bundle["metrics"].get("model_type"),
        "operations": operational_summary(),
    }


@app.get("/hotspots")
def hotspots_endpoint(limit: int = 20):
    return {"hotspots": hotspots(limit=limit)}


@app.get("/similar-events")
def similar_events_endpoint(
    event_cause: str,
    latitude: float,
    longitude: float,
    limit: int = 5,
):
    bundle = load_model_bundle()
    return {"similar_past_events": similar_events(bundle, {"event_cause": event_cause, "latitude": latitude, "longitude": longitude}, limit=limit)}


@app.get("/model-metrics")
def model_metrics_endpoint():
    bundle = load_model_bundle()
    return bundle["metrics"]


@app.post("/recommend-plan")
def recommend_plan_endpoint(request: RecommendPlanRequest):
    recommendation = recommend_plan(
        request.event_cause,
        request.impact_score,
        request.road_closure_probability,
        request.expected_duration_hours,
    )
    return {
        "recommended_manpower_count": recommendation.recommended_manpower_count,
        "barricading_required": recommendation.barricading_required,
        "diversion_required": recommendation.diversion_required,
        "response_team_type": recommendation.response_team_type,
        "explanation": recommendation.explanation,
    }


if FRONTEND_DIST_PATH.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST_PATH, html=True), name="frontend")
