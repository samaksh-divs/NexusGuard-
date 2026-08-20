from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch

from app.ml.lstm_model import FraudLSTM


MODEL_DIR = Path("models")

RF_PATH = MODEL_DIR / "random_forest.pkl"
XGB_PATH = MODEL_DIR / "xgboost.pkl"
LSTM_PATH = MODEL_DIR / "lstm_fraud.pt"
SCALER_PATH = MODEL_DIR / "lstm_scaler.pkl"


class MLEnsemble:

    def __init__(self):

        print("[ML] Loading Random Forest...")
        self.random_forest = joblib.load(RF_PATH)

        print("[ML] Loading XGBoost...")
        self.xgboost = joblib.load(XGB_PATH)

        print("[ML] Loading LSTM scaler...")
        self.scaler = joblib.load(SCALER_PATH)

        print("[ML] Loading LSTM...")

        self.lstm = FraudLSTM(
            input_size=165
        )

        self.lstm.load_state_dict(
            torch.load(
                LSTM_PATH,
                map_location="cpu",
            )
        )

        self.lstm.eval()

        print("[ML] All models loaded successfully.")

    def predict_tabular(
        self,
        features,
    ):

        # Random Forest and XGBoost were trained
        # with feature_1 ... feature_165.

        feature_names = self.random_forest.feature_names_in_

        features_df = pd.DataFrame(
            features,
            columns=feature_names,
        )

        rf_probability = self.random_forest.predict_proba(
            features_df
        )[0][1]

        xgb_probability = self.xgboost.predict_proba(
            features_df
        )[0][1]

        return (
            float(rf_probability),
            float(xgb_probability),
        )

    def predict_lstm(
        self,
        sequence,
    ):

        sequence = np.asarray(
            sequence,
            dtype=float,
        )

        scaled = self.scaler.transform(
            sequence
        )

        tensor = torch.tensor(
            scaled,
            dtype=torch.float32,
        ).unsqueeze(0)

        with torch.no_grad():

            output = self.lstm(
                tensor
            )

            probability = torch.sigmoid(
                output
            ).item()

        return float(probability)

    def predict(
        self,
        features,
        sequence,
    ):

        rf_probability, xgb_probability = (
            self.predict_tabular(
                features
            )
        )

        lstm_probability = self.predict_lstm(
            sequence
        )

        # ------------------------------------------------
        # ML ENSEMBLE
        # ------------------------------------------------

        final_probability = (
            0.35 * rf_probability
            + 0.35 * xgb_probability
            + 0.30 * lstm_probability
        )

        final_probability = float(
            np.clip(
                final_probability,
                0.0,
                1.0,
            )
        )

        # ------------------------------------------------
        # ML-ONLY RISK DECISION
        #
        # < 0.50  -> LOW / APPROVE
        # < 0.80  -> MEDIUM / REVIEW
        # >= 0.80 -> HIGH / BLOCK
        #
        # This is ONLY the ML decision.
        # The transaction worker calculates
        # the final system decision separately.
        # ------------------------------------------------

        if final_probability >= 0.80:

            risk_level = "HIGH"
            decision = "BLOCK"

        elif final_probability >= 0.50:

            risk_level = "MEDIUM"
            decision = "REVIEW"

        else:

            risk_level = "LOW"
            decision = "APPROVE"

        return {
            "rf_probability": round(
                rf_probability,
                4,
            ),

            "xgb_probability": round(
                xgb_probability,
                4,
            ),

            "lstm_probability": round(
                lstm_probability,
                4,
            ),

            "final_probability": round(
                final_probability,
                4,
            ),

            "risk_score": round(
                final_probability * 100,
                2,
            ),

            "risk_level": risk_level,

            "decision": decision,
        }