from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT_DIR / "data" / "events.csv"
MODELS_DIR = ROOT_DIR / "models"
REPORTS_DIR = ROOT_DIR / "reports"

MODEL_BUNDLE_PATH = MODELS_DIR / "eventgrid_model_bundle.joblib"
METRICS_PATH = REPORTS_DIR / "metrics.json"
EDA_SUMMARY_PATH = REPORTS_DIR / "eda_summary.md"
DB_PATH = ROOT_DIR / "data" / "eventgrid.db"
MODEL_DIAGNOSTICS_PATH = REPORTS_DIR / "model_diagnostics.json"
MODEL_CARD_PATH = ROOT_DIR / "MODEL_CARD.md"

LOCAL_TZ = "Asia/Kolkata"
