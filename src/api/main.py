from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.predict import hotspots, load_model_bundle, predict_impact, similar_events
from src.recommend import recommend_plan


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


class RecommendPlanRequest(BaseModel):
    event_cause: str
    impact_score: float = Field(..., ge=0, le=100)
    road_closure_probability: float = Field(..., ge=0, le=1)
    expected_duration_hours: float = Field(2.0, ge=0)


app = FastAPI(
    title="EventGrid AI",
    version="0.1.0",
    description="Operational traffic impact prediction for planned and unplanned events.",
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
    return {"status": "ok", "service": "eventgrid-ai"}


@app.post("/predict-impact")
def predict_impact_endpoint(request: EventImpactRequest):
    return predict_impact(request.model_dump())


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
