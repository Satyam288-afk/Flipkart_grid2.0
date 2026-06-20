from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


class ProbabilityCalibrator:
    min_brier_improvement = 1e-4

    def __init__(self) -> None:
        self.model = IsotonicRegression(out_of_bounds="clip")
        self.is_fitted = False
        self.brier_before: float | None = None
        self.brier_after: float | None = None
        self.average_precision_before: float | None = None
        self.average_precision_after: float | None = None
        self.roc_auc_before: float | None = None
        self.roc_auc_after: float | None = None
        self.status = "not_fitted"

    def fit(self, probabilities, y_true) -> "ProbabilityCalibrator":
        probs = np.asarray(probabilities, dtype=float)
        y = np.asarray(y_true, dtype=int)
        if len(np.unique(y)) < 2:
            self.status = "not_applied_single_class_calibration_slice"
            return self

        self.brier_before = float(brier_score_loss(y, probs))
        self.average_precision_before = float(average_precision_score(y, probs))
        self.roc_auc_before = float(roc_auc_score(y, probs))
        self.model.fit(probs, y)
        calibrated = np.clip(self.model.predict(probs), 0, 1)
        self.brier_after = float(brier_score_loss(y, calibrated))
        self.average_precision_after = float(average_precision_score(y, calibrated))
        self.roc_auc_after = float(roc_auc_score(y, calibrated))
        improvement = self.brier_before - self.brier_after
        if improvement >= self.min_brier_improvement:
            self.is_fitted = True
            self.status = "applied"
        else:
            self.is_fitted = False
            self.status = "not_applied_no_brier_improvement"
        return self

    def predict(self, probabilities):
        probs = np.asarray(probabilities, dtype=float)
        if not self.is_fitted:
            return np.clip(probs, 0, 1)
        return np.clip(self.model.predict(probs), 0, 1)

    def summary(self) -> dict:
        return {
            "method": "isotonic",
            "status": self.status,
            "applied": self.is_fitted,
            "brier_before": self.brier_before,
            "brier_after": self.brier_after,
            "average_precision_before": self.average_precision_before,
            "average_precision_after": self.average_precision_after,
            "roc_auc_before": self.roc_auc_before,
            "roc_auc_after": self.roc_auc_after,
            "min_brier_improvement": self.min_brier_improvement,
        }
