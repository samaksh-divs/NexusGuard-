from pathlib import Path
import joblib

from xgboost import XGBClassifier
from sklearn.metrics import classification_report, confusion_matrix

from app.ml.preprocessing import (
    load_elliptic_dataset,
    time_based_train_test_split,
)


MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "xgboost.pkl"


def train_xgboost():

    print("[XGB] Loading Elliptic dataset...")

    dataset = load_elliptic_dataset()

    X_train, X_test, y_train, y_test = time_based_train_test_split(
        dataset
    )

    print(f"[XGB] Training samples: {len(X_train)}")
    print(f"[XGB] Testing samples: {len(X_test)}")
    print(f"[XGB] Features: {X_train.shape[1]}")

    # Calculate imbalance ratio
    negative = (y_train == 0).sum()
    positive = (y_train == 1).sum()

    scale_pos_weight = negative / positive

    print(f"[XGB] Scale positive weight: {scale_pos_weight:.2f}")

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        objective="binary:logistic",
        eval_metric="aucpr",
        random_state=42,
        n_jobs=-1,
    )

    print("[XGB] Training...")

    model.fit(X_train, y_train)

    print("[XGB] Training complete.")

    predictions = model.predict(X_test)

    print("\n[XGB] Classification Report:")
    print(
        classification_report(
            y_test,
            predictions,
            target_names=["Licit", "Illicit"],
            zero_division=0,
        )
    )

    print("[XGB] Confusion Matrix:")
    print(confusion_matrix(y_test, predictions))

    joblib.dump(model, MODEL_PATH)

    print(f"\n[XGB] Model saved to: {MODEL_PATH}")

    return model


if __name__ == "__main__":
    train_xgboost()