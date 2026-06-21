# EventGrid AI Model Card

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
- Test rows: 1635.
- Test positive rate: 0.0869.

## Secondary Priority Signal

The high-priority model is retained only as a secondary operational signal. In this dataset, priority is strongly tied to location/corridor structure: average corridor priority purity is 0.984 and average junction priority purity is 0.976. The model is therefore learning a corridor/junction-level priority pattern, not solving a hard independent per-incident classification problem.

## Current Road-Closure Metrics

- ROC-AUC: 0.836
- PR-AUC: 0.397
- Precision at 0.5: 0.284
- Recall at 0.5: 0.662
- F1 at 0.5: 0.397
- Top 10% risk capture: 0.493

## Serving Operating Point

- Balanced threshold: 0.75
- Precision at balanced threshold: 0.451
- Recall at balanced threshold: 0.486
- F1 at balanced threshold: 0.468
- Serving probability mode: raw
- Calibration evaluator status: applied

## Suggested Operating Points

- Balanced F1 threshold: 0.75 with F1 0.4678.
- High-recall operations threshold: 0.4 with recall 0.7606.
- High-precision operations threshold: 0.85 with precision 0.4578.

## Safety and Limitations

- Closure events are imbalanced, so raw accuracy is not a useful headline metric.
- Duration labels are noisy because they depend on operational closure/resolution timestamps.
- Probability calibration should be reviewed before real deployment.
- Recommendations require human operator approval.
- Live road graph routing is not included in this prototype.
