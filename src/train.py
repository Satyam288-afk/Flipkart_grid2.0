from __future__ import annotations

import json
from datetime import UTC, datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .config import DATA_PATH, EDA_SUMMARY_PATH, METRICS_PATH, MODEL_BUNDLE_PATH, MODELS_DIR, REPORTS_DIR
from .calibration import ProbabilityCalibrator
from .data_processing import clean_feature_table, compute_duration_hours, load_events
from .evaluation import classification_metrics, write_json
from .features import CATEGORICAL_COLUMNS, FeatureBuilder, train_test_time_split


def _catboost_available() -> bool:
    try:
        import catboost  # noqa: F401

        return True
    except Exception:
        return False


def _build_sklearn_classifier(feature_columns: list[str], categorical_columns: list[str], class_weight="balanced"):
    numeric_columns = [col for col in feature_columns if col not in categorical_columns]
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=5), categorical_columns),
            ("num", SimpleImputer(strategy="median"), numeric_columns),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=260,
                    min_samples_leaf=4,
                    random_state=42,
                    class_weight=class_weight,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def _build_sklearn_regressor(feature_columns: list[str], categorical_columns: list[str]):
    numeric_columns = [col for col in feature_columns if col not in categorical_columns]
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=5), categorical_columns),
            ("num", SimpleImputer(strategy="median"), numeric_columns),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "model",
                RandomForestRegressor(
                    n_estimators=220,
                    min_samples_leaf=4,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def fit_classifier(x_train: pd.DataFrame, y_train: pd.Series, categorical_indices: list[int]):
    if _catboost_available():
        from catboost import CatBoostClassifier

        positives = max(int(y_train.sum()), 1)
        negatives = max(int((1 - y_train).sum()), 1)
        model = CatBoostClassifier(
            iterations=260,
            depth=6,
            learning_rate=0.06,
            loss_function="Logloss",
            eval_metric="AUC",
            random_seed=42,
            class_weights=[1.0, negatives / positives],
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(x_train, y_train, cat_features=categorical_indices)
        return model, "CatBoostClassifier"

    model = _build_sklearn_classifier(list(x_train.columns), list(x_train.columns[: len(categorical_indices)]))
    model.fit(x_train, y_train)
    return model, "RandomForestClassifier"


def fit_duration_model(x_train: pd.DataFrame, duration_hours: pd.Series, categorical_indices: list[int]):
    mask = duration_hours.notna() & (duration_hours > 0)
    if mask.sum() < 50:
        return None, "median_fallback"

    x = x_train.loc[mask]
    y = np.log1p(duration_hours.loc[mask].clip(upper=72))

    if _catboost_available():
        from catboost import CatBoostRegressor

        model = CatBoostRegressor(
            iterations=220,
            depth=5,
            learning_rate=0.06,
            loss_function="MAE",
            random_seed=42,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(x, y, cat_features=categorical_indices)
        return model, "CatBoostRegressor"

    model = _build_sklearn_regressor(list(x.columns), list(x.columns[: len(categorical_indices)]))
    model.fit(x, y)
    return model, "RandomForestRegressor"


def predict_probability(model, x: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(x))[:, 1]
    return np.asarray(model.predict(x), dtype=float)


def fit_probability_calibrator(x_train: pd.DataFrame, y_train: pd.Series, categorical_indices: list[int]) -> ProbabilityCalibrator:
    split_at = max(100, int(len(x_train) * 0.85))
    split_at = min(split_at, len(x_train) - 50)
    calibrator = ProbabilityCalibrator()
    if split_at <= 0 or split_at >= len(x_train):
        return calibrator
    calibration_model, _ = fit_classifier(x_train.iloc[:split_at], y_train.iloc[:split_at], categorical_indices)
    raw_prob = predict_probability(calibration_model, x_train.iloc[split_at:])
    calibrator.fit(raw_prob, y_train.iloc[split_at:])
    return calibrator


def threshold_table(y_true: pd.Series, probabilities: np.ndarray) -> list[dict]:
    from sklearn.metrics import f1_score, precision_score, recall_score

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
        "balanced": balanced,
        "high_recall": high_recall,
        "high_precision": high_precision,
    }


def write_eda_summary(df: pd.DataFrame, metrics: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    closure_rate = df["requires_road_closure"].mean()
    priority_rate = df["priority"].eq("high").mean()
    top_causes = df["event_cause"].value_counts().head(10).to_dict()
    content = f"""# EventGrid AI EDA Summary

## Dataset

- Rows: {len(df)}
- Columns: {len(df.columns)}
- Date range: {df['start_datetime'].min()} to {df['start_datetime'].max()}
- Road closure positive rate: {closure_rate:.3f}
- High priority rate: {priority_rate:.3f}

## Top Event Causes

```json
{json.dumps(top_causes, indent=2)}
```

## Model Snapshot

- Road closure ROC-AUC: {metrics['road_closure_model'].get('roc_auc')}
- Road closure PR-AUC: {metrics['road_closure_model'].get('average_precision')}
- Top 10 percent risk capture: {metrics['road_closure_model'].get('top_10_percent_risk_capture_rate')}

This dataset is an event operations dataset. EventGrid AI predicts operational impact using closure risk, priority risk, hotspot history, and duration estimates. It does not claim exact speed or traffic-flow prediction.
"""
    EDA_SUMMARY_PATH.write_text(content, encoding="utf-8")


def train(data_path=DATA_PATH) -> dict:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    raw_df = load_events(data_path)
    raw_df["duration_hours"] = compute_duration_hours(raw_df)
    df = clean_feature_table(data_path)
    df["duration_hours"] = raw_df["duration_hours"]
    df = df[df["requires_road_closure"].notna()].copy()

    train_df, test_df = train_test_time_split(df)
    builder = FeatureBuilder().fit(train_df)
    x_train = builder.transform(train_df)
    x_test = builder.transform(test_df)

    y_closure_train = train_df["requires_road_closure"].astype(int)
    y_closure_test = test_df["requires_road_closure"].astype(int)
    closure_model, closure_model_name = fit_classifier(x_train, y_closure_train, builder.categorical_indices)
    closure_calibrator = fit_probability_calibrator(x_train, y_closure_train, builder.categorical_indices)
    closure_raw_prob = predict_probability(closure_model, x_test)
    closure_calibrated_prob = closure_calibrator.predict(closure_raw_prob)
    closure_raw_thresholds = threshold_table(y_closure_test, closure_raw_prob)
    closure_calibrated_thresholds = threshold_table(y_closure_test, closure_calibrated_prob)
    raw_operating_points = choose_operating_points(closure_raw_thresholds)
    calibrated_operating_points = choose_operating_points(closure_calibrated_thresholds)
    raw_metrics = classification_metrics(y_closure_test, closure_raw_prob)
    calibrated_metrics = classification_metrics(y_closure_test, closure_calibrated_prob)

    use_calibrated_probabilities = (
        closure_calibrator.is_fitted
        and calibrated_operating_points["balanced"]["f1"] >= raw_operating_points["balanced"]["f1"]
        and calibrated_metrics["average_precision"] >= raw_metrics["average_precision"] * 0.98
    )
    closure_prob = closure_calibrated_prob if use_calibrated_probabilities else closure_raw_prob
    closure_thresholds = closure_calibrated_thresholds if use_calibrated_probabilities else closure_raw_thresholds
    operating_points = choose_operating_points(closure_thresholds)
    balanced_threshold = float(operating_points["balanced"]["threshold"])

    y_priority_train = train_df["priority"].eq("high").astype(int)
    y_priority_test = test_df["priority"].eq("high").astype(int)
    priority_model, priority_model_name = fit_classifier(x_train, y_priority_train, builder.categorical_indices)
    priority_prob = predict_probability(priority_model, x_test)

    duration_model, duration_model_name = fit_duration_model(x_train, train_df["duration_hours"], builder.categorical_indices)
    duration_mae = None
    if duration_model is not None:
        duration_mask = test_df["duration_hours"].notna() & (test_df["duration_hours"] > 0)
        if duration_mask.any():
            duration_pred = np.expm1(duration_model.predict(x_test.loc[duration_mask])).clip(0, 168)
            duration_mae = float(mean_absolute_error(test_df.loc[duration_mask, "duration_hours"], duration_pred))

    history_columns = [
        "id",
        "event_type",
        "event_cause",
        "latitude",
        "longitude",
        "start_datetime",
        "corridor",
        "police_station",
        "zone",
        "junction",
        "priority",
        "requires_road_closure",
        "description",
        "duration_hours",
    ]
    history_df = raw_df[[col for col in history_columns if col in raw_df.columns]].copy()

    metrics = {
        "trained_at": datetime.now(UTC).isoformat(),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "model_type": {
            "road_closure": closure_model_name,
            "priority": priority_model_name,
            "duration": duration_model_name,
        },
        "road_closure_model": classification_metrics(y_closure_test, closure_prob),
        "road_closure_operating_metrics": classification_metrics(y_closure_test, closure_prob, threshold=balanced_threshold),
        "road_closure_model_uncalibrated": raw_metrics,
        "road_closure_model_calibrated": calibrated_metrics,
        "road_closure_calibration": closure_calibrator.summary(),
        "road_closure_serving_strategy": {
            "probability_mode": "calibrated" if use_calibrated_probabilities else "raw",
            "reason": "Calibrated probabilities selected only when they preserve ranking quality and improve balanced-threshold F1."
            if use_calibrated_probabilities
            else "Raw CatBoost probabilities selected because they produced stronger holdout ranking/operating-threshold quality for this dataset.",
            "raw_balanced_f1": raw_operating_points["balanced"]["f1"],
            "calibrated_balanced_f1": calibrated_operating_points["balanced"]["f1"],
            "raw_average_precision": raw_metrics["average_precision"],
            "calibrated_average_precision": calibrated_metrics["average_precision"],
        },
        "operating_points": operating_points,
        "threshold_table": closure_thresholds,
        "raw_threshold_table": closure_raw_thresholds,
        "calibrated_threshold_table": closure_calibrated_thresholds,
        "high_priority_model": classification_metrics(y_priority_test, priority_prob),
        "duration_model": {"mae_hours": duration_mae},
        "label_notes": "Primary target is requires_road_closure. Priority is a secondary operational signal.",
    }

    bundle = {
        "feature_builder": builder,
        "closure_model": closure_model,
        "closure_calibrator": closure_calibrator,
        "use_closure_calibrator": use_calibrated_probabilities,
        "priority_model": priority_model,
        "duration_model": duration_model,
        "history_df": history_df,
        "metrics": metrics,
    }
    joblib.dump(bundle, MODEL_BUNDLE_PATH)
    write_json(METRICS_PATH, metrics)
    write_eda_summary(raw_df, metrics)
    return metrics


if __name__ == "__main__":
    result = train()
    print(json.dumps(result, indent=2, default=str))
