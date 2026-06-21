# EventGrid AI EDA Summary

## Dataset

- Rows: 8173
- Columns: 47
- Date range: 2023-11-10 00:54:48.154000+05:30 to 2024-04-08 22:41:42.780000+05:30
- Road closure positive rate: 0.083
- High priority rate: 0.615

## Top Event Causes

```json
{
  "vehicle_breakdown": 4896,
  "others": 638,
  "pot_holes": 537,
  "construction": 480,
  "water_logging": 458,
  "accident": 365,
  "tree_fall": 284,
  "road_conditions": 170,
  "congestion": 136,
  "public_event": 84
}
```

## Model Snapshot

- Road closure ROC-AUC: 0.8364716092940765
- Road closure PR-AUC: 0.3967675866091295
- Top 10 percent risk capture: 0.49295774647887325

This dataset is an event operations dataset. EventGrid AI predicts operational impact using closure risk, priority risk, hotspot history, and duration estimates. It does not claim exact speed or traffic-flow prediction.
