from pathlib import Path
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix

from app.ml.preprocessing import (
    load_elliptic_dataset,
    time_based_train_test_split,
)


MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "random_forest.pkl"


def train_random_forest():

    print("[RF] Loading Elliptic dataset...")

    dataset = load_elliptic_dataset()

    X_train, X_test, y_train, y_test = time_based_train_test_split(
        dataset
    )

    print(f"[RF] Training samples: {len(X_train)}")
    print(f"[RF] Testing samples: {len(X_test)}")
    print(f"[RF] Features: {X_train.shape[1]}")

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=15,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    print("[RF] Training...")

    model.fit(X_train, y_train)

    print("[RF] Training complete.")

    predictions = model.predict(X_test)

    print("\n[RF] Classification Report:")
    print(
        classification_report(
            y_test,
            predictions,
            target_names=["Licit", "Illicit"],
            zero_division=0,
        )
    )

    print("[RF] Confusion Matrix:")
    print(confusion_matrix(y_test, predictions))

    joblib.dump(model, MODEL_PATH)

    print(f"\n[RF] Model saved to: {MODEL_PATH}")

    return model


if __name__ == "__main__":
    train_random_forest()