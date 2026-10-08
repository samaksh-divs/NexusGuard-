from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_ARTIFACTS = {
    "Random Forest": (PROJECT_ROOT / "models" / "random_forest.pkl",),
    "XGBoost": (PROJECT_ROOT / "models" / "xgboost.pkl",),
    "LSTM": (
        PROJECT_ROOT / "models" / "lstm_fraud.pt",
        PROJECT_ROOT / "models" / "lstm_scaler.pkl",
    ),
}


def get_model_availability() -> dict[str, dict[str, object]]:
    availability = {}

    for name, artifacts in MODEL_ARTIFACTS.items():
        missing = [str(path.relative_to(PROJECT_ROOT)) for path in artifacts if not path.is_file()]
        availability[name] = {
            "available": not missing,
            "missing_artifacts": missing,
        }

    model_statuses = [availability[name]["available"] for name in MODEL_ARTIFACTS]
    availability["Ensemble"] = {
        "available": any(model_statuses),
        "missing_artifacts": [
            artifact
            for name in MODEL_ARTIFACTS
            for artifact in availability[name]["missing_artifacts"]
        ],
    }
    return availability
