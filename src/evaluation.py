from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def safe_metric(fn, y_true, y_score, default: float | None = None):
    try:
        return float(fn(y_true, y_score))
    except Exception:
        return default


def classification_metrics(y_true, probabilities, threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true).astype(int)
    probabilities = np.asarray(probabilities, dtype=float)
    y_pred = (probabilities >= threshold).astype(int)

    high_risk_threshold = float(np.quantile(probabilities, 0.9)) if len(probabilities) else 1.0
    high_risk_mask = probabilities >= high_risk_threshold
    positives = max(int(y_true.sum()), 1)

    return {
        "roc_auc": safe_metric(roc_auc_score, y_true, probabilities),
        "average_precision": safe_metric(average_precision_score, y_true, probabilities),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "high_risk_threshold": high_risk_threshold,
        "recall_for_high_risk_events": float(y_true[high_risk_mask].sum() / positives),
        "top_10_percent_risk_capture_rate": float(y_true[high_risk_mask].sum() / positives),
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
