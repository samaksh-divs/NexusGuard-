from typing import Any

import numpy as np

from app.ml.ensemble import MLEnsemble
from app.ml.feature_builder import build_transaction_features


class MLService:

    def __init__(self):
        self.model = MLEnsemble()

    def predict_transaction(
        self,
        transaction_value: float,
        quantity: float,
        symbol: str,
        risk_score: float,
        behavioral_score: float,
    ) -> dict[str, Any]:

        features = build_transaction_features(
            transaction_value=transaction_value,
            quantity=quantity,
            symbol=symbol,
            risk_score=risk_score,
            behavioral_score=behavioral_score,
        )

        features = features.reshape(1, -1)

        # Temporary sequence adapter.
        #
        # The production version will construct this from
        # actual account transaction history.
        sequence = np.repeat(
            features,
            10,
            axis=0,
        )

        return self.model.predict(
            features,
            sequence,
        )