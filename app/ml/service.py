"""
NexusGuard ML Service.

Provides the interface used by the RabbitMQ transaction worker.

The worker supplies a transaction dictionary.
This module converts that transaction into the feature inputs
expected by MLEnsemble and returns the ensemble prediction.
"""

from typing import Any

import numpy as np

from app.ml.ensemble import MLEnsemble
from app.ml.feature_builder import build_transaction_features


# Singleton model service.
# Models are loaded once and reused for subsequent transactions.
_ml_service: "MLService | None" = None


class MLService:

    def __init__(self):
        print("[ML] Initializing ML Service...")
        self.model = MLEnsemble()
        print("[ML] ML Service ready.")

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

        # Ensure the model receives a 2D tabular matrix.
        features = np.asarray(
            features,
            dtype=float,
        ).reshape(1, -1)

        # Temporary sequence adapter.
        #
        # The production version can later construct this
        # from actual account transaction history.
        sequence = np.repeat(
            features,
            10,
            axis=0,
        )

        return self.model.predict(
            features,
            sequence,
        )


def load_models() -> MLService:
    """
    Load the ML ensemble once and return the service.

    The worker imports this function during startup or prediction.
    """

    global _ml_service

    if _ml_service is None:
        _ml_service = MLService()

    return _ml_service


def predict_transaction_risk(
    transaction: dict[str, Any],
) -> dict[str, Any]:
    """
    Predict ML risk for a transaction dictionary.

    This is the interface consumed by app.messaging.consumer.
    """

    service = load_models()

    # ------------------------------------------------------------
    # Transaction value
    # ------------------------------------------------------------

    transaction_value = transaction.get(
        "transaction_value"
    )

    if transaction_value is None:

        amount = float(
            transaction.get(
                "amount",
                0.0,
            )
            or 0.0
        )

        quantity = float(
            transaction.get(
                "quantity",
                1.0,
            )
            or 1.0
        )

        transaction_value = amount * quantity

    transaction_value = float(
        transaction_value
    )

    # ------------------------------------------------------------
    # Quantity
    # ------------------------------------------------------------

    quantity = float(
        transaction.get(
            "quantity",
            1.0,
        )
        or 1.0
    )

    # ------------------------------------------------------------
    # Symbol
    # ------------------------------------------------------------

    symbol = str(
        transaction.get(
            "symbol",
            "",
        )
    )

    # ------------------------------------------------------------
    # Rule-based fraud score
    # ------------------------------------------------------------

    risk_score = float(
        transaction.get(
            "individual_fraud_score",
            transaction.get(
                "risk_score",
                0.0,
            ),
        )
        or 0.0
    )

    # ------------------------------------------------------------
    # Behavioral score
    # ------------------------------------------------------------

    behavioral_score = float(
        transaction.get(
            "behavioral_score",
            0.0,
        )
        or 0.0
    )

    # ------------------------------------------------------------
    # Run ensemble
    # ------------------------------------------------------------

    result = service.predict_transaction(
        transaction_value=transaction_value,
        quantity=quantity,
        symbol=symbol,
        risk_score=risk_score,
        behavioral_score=behavioral_score,
    )

    return result


def close_models() -> None:
    """
    Release the ML service reference.

    Primarily useful for testing or controlled worker shutdown.
    """

    global _ml_service

    _ml_service = None