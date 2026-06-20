from __future__ import annotations

import json
from datetime import UTC, datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score

from .config import DATA_PATH, MODEL_BUNDLE_PATH, MODEL_CARD_PATH, MODEL_DIAGNOSTICS_PATH
from .data_processing import clean_feature_table, compute_duration_hours, load_events
from .features import train_test_time_split
from .train import predict_probability


def threshold_table(y_true: pd.Series, probabilities: np.ndarray) -> list[dict]:
    rows = []
    for threshold in np.arange(0.1, 0.91, 0.05):
        predictions = (probabilities >= threshold).astype(int)
        rows.append(
            {
                "threshold": round(float(threshold), 2),
                "precision": round(float(precision_score(y_true, predictions, zero_division=0)), 4),
                "recall": round(float(recall_score(y_true, predictions, zero_division=0)), 4),
                "f1": round(float(f1_score(y_true, predictions, zero_division=0)), 4),
                "predicted_positive_rate": round(float(predictions.mean()), 4),
            }
        )
    return rows


def choose_operating_points(rows: list[dict]) -> dict:
    balanced = max(rows, key=lambda row: row["f1"])
    high_recall_candidates = [row for row in rows if row["recall"] >= 0.75]
    high_recall = max(high_recall_candidates, key=lambda row: row["precision"]) if high_recall_candidates else max(rows, key=lambda row: row["recall"])
    high_precision_candidates = [row for row in rows if row["recall"] >= 0.25]
    high_precision = max(high_precision_candidates, key=lambda row: row["precision"]) if high_precision_candidates else max(rows, key=lambda row: row["precision"])
    return {
        "balanced_f1": balanced,
        "high_recall_operations": high_recall,
        "high_precision_operations": high_precision,
    }


def calibration_bins(y_true: pd.Series, probabilities: np.ndarray, bins: int = 10) -> list[dict]:
    frame = pd.DataFrame({"actual": y_true.to_numpy(), "probability": probabilities})
    frame["bin"] = pd.cut(frame["probability"], bins=np.linspace(0, 1, bins + 1), include_lowest=True)
    grouped = (
        frame.groupby("bin", observed=False)
        .agg(count=("actual", "size"), mean_predicted_probability=("probability", "mean"), observed_closure_rate=("actual", "mean"))
        .reset_index()
    )
    rows = []
    for row in grouped.itertuples():
        if row.count == 0:
            continue
        rows.append(
            {
                "probability_bin": str(row.bin),
                "count": int(row.count),
                "mean_predicted_probability": round(float(row.mean_predicted_probability), 4),
                "observed_closure_rate": round(float(row.observed_closure_rate), 4),
            }
        )
    return rows


def segment_diagnostics(test_df: pd.DataFrame, probabilities: np.ndarray, min_count: int = 20) -> list[dict]:
    frame = test_df.copy()
    frame["predicted_closure_probability"] = probabilities
    grouped = (
        frame.groupby("event_cause", dropna=False)
        .agg(
            count=("requires_road_closure", "size"),
            observed_closure_rate=("requires_road_closure", "mean"),
            average_predicted_probability=("predicted_closure_probability", "mean"),
        )
        .reset_index()
    )
    grouped = grouped[grouped["count"] >= min_count].sort_values("count", ascending=False)
    return [
        {
            "event_cause": row.event_cause,
            "count": int(row.count),
            "observed_closure_rate": round(float(row.observed_closure_rate), 4),
            "average_predicted_probability": round(float(row.average_predicted_probability), 4),
            "calibration_gap": round(float(row.average_predicted_probability - row.observed_closure_rate), 4),
        }
        for row in grouped.itertuples()
    ]


def write_model_card(diagnostics: dict) -> None:
    metrics = diagnostics["metrics"]["road_closure_model"]
    operating_metrics = diagnostics["metrics"].get("road_closure_operating_metrics", metrics)
    calibration = diagnostics["metrics"].get("road_closure_calibration", {})
    serving_strategy = diagnostics["metrics"].get("road_closure_serving_strategy", {})
    operating = diagnostics["operating_points"]
    content = f"""# EventGrid AI Model Card

## Model Purpose

EventGrid AI predicts operational road-closure risk for planned and unplanned traffic events. The model supports traffic police and smart-city operators with triage, manpower, barricading, and diversion readiness decisions.

## Intended Use

- Rank incoming events by road-closure risk.
- Support command-center decision making.
- Provide explainable operational impact scoring.
- Run what-if simulations before planned events.

## Non-Goals

- Exact vehicle speed or traffic-flow prediction.
- Fully automated closure/diversion execution.
- Turn-by-turn navigation routing.
- Production public-safety deployment without operator review.

## Data

- Source: Topic 2 event operations CSV.
- Primary target: `requires_road_closure`.
- Secondary signal: `priority == High`.
- Split: time-based, older 80% train and newer 20% test.
- Test rows: {diagnostics['test_rows']}.
- Test positive rate: {diagnostics['test_positive_rate']}.

## Current Road-Closure Metrics

- ROC-AUC: {metrics['roc_auc']:.3f}
- PR-AUC: {metrics['average_precision']:.3f}
- Precision at 0.5: {metrics['precision']:.3f}
- Recall at 0.5: {metrics['recall']:.3f}
- F1 at 0.5: {metrics['f1']:.3f}
- Top 10% risk capture: {metrics['top_10_percent_risk_capture_rate']:.3f}

## Serving Operating Point

- Balanced threshold: {operating['balanced_f1']['threshold']}
- Precision at balanced threshold: {operating_metrics['precision']:.3f}
- Recall at balanced threshold: {operating_metrics['recall']:.3f}
- F1 at balanced threshold: {operating_metrics['f1']:.3f}
- Serving probability mode: {serving_strategy.get('probability_mode', 'unknown')}
- Calibration evaluator status: {calibration.get('status', 'unknown')}

## Suggested Operating Points

- Balanced F1 threshold: {operating['balanced_f1']['threshold']} with F1 {operating['balanced_f1']['f1']}.
- High-recall operations threshold: {operating['high_recall_operations']['threshold']} with recall {operating['high_recall_operations']['recall']}.
- High-precision operations threshold: {operating['high_precision_operations']['threshold']} with precision {operating['high_precision_operations']['precision']}.

## Safety and Limitations

- Closure events are imbalanced, so raw accuracy is not a useful headline metric.
- Duration labels are noisy because they depend on operational closure/resolution timestamps.
- Probability calibration should be reviewed before real deployment.
- Recommendations require human operator approval.
- Live road graph routing is not included in this prototype.
"""
    MODEL_CARD_PATH.write_text(content, encoding="utf-8")


def generate_diagnostics(data_path=DATA_PATH) -> dict:
    if not MODEL_BUNDLE_PATH.exists():
        from .train import train

        train(data_path)

    bundle = joblib.load(MODEL_BUNDLE_PATH)
    raw_df = load_events(data_path)
    raw_df["duration_hours"] = compute_duration_hours(raw_df)
    df = clean_feature_table(data_path)
    df["duration_hours"] = raw_df["duration_hours"]
    df = df[df["requires_road_closure"].notna()].copy()

    _, test_df = train_test_time_split(df)
    x_test = bundle["feature_builder"].transform(test_df)
    y_test = test_df["requires_road_closure"].astype(int)
    raw_probabilities = predict_probability(bundle["closure_model"], x_test)
    calibrator = bundle.get("closure_calibrator")
    if bundle.get("use_closure_calibrator", False) and calibrator is not None:
        probabilities = calibrator.predict(raw_probabilities)
    else:
        probabilities = raw_probabilities

    thresholds = threshold_table(y_test, probabilities)
    diagnostics = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model_artifact": str(MODEL_BUNDLE_PATH),
        "train_rows": bundle["metrics"]["train_rows"],
        "test_rows": bundle["metrics"]["test_rows"],
        "test_positive_rate": round(float(y_test.mean()), 4),
        "metrics": bundle["metrics"],
        "calibration": bundle["metrics"].get("road_closure_calibration"),
        "threshold_table": thresholds,
        "operating_points": choose_operating_points(thresholds),
        "calibration_bins": calibration_bins(y_test, probabilities),
        "segment_diagnostics": segment_diagnostics(test_df, probabilities),
        "recommendation": "Keep CatBoost as default. Use diagnostics to tune operating threshold by deployment mode; do not promote stacking unless PR-AUC and top-decile capture improve on time-based validation.",
    }

    MODEL_DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_DIAGNOSTICS_PATH.write_text(json.dumps(diagnostics, indent=2, default=str) + "\n", encoding="utf-8")
    write_model_card(diagnostics)
    return diagnostics


if __name__ == "__main__":
    result = generate_diagnostics()
    print(json.dumps({"diagnostics": str(MODEL_DIAGNOSTICS_PATH), "model_card": str(MODEL_CARD_PATH), "operating_points": result["operating_points"]}, indent=2))
