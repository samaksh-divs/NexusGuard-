import numpy as np


def build_transaction_features(
    transaction_value: float,
    quantity: float,
    symbol: str,
    risk_score: float,
    behavioral_score: float,
) -> np.ndarray:
    """
    Convert NexusGuard transaction information into
    the 165-feature vector expected by the ML models.

    NOTE:
    The Elliptic dataset contains 165 engineered blockchain
    transaction features. Live transactions do not expose
    those exact dataset features, so we create a normalized
    inference vector from the information currently available
    to NexusGuard.

    This adapter will later be replaced/enhanced when live
    blockchain WebSocket transaction features are available.
    """

    features = np.zeros(165, dtype=np.float32)

    # Core transaction signals
    features[0] = transaction_value
    features[1] = quantity
    features[2] = risk_score
    features[3] = behavioral_score

    # Simple value transformations
    features[4] = np.log1p(max(transaction_value, 0))
    features[5] = np.sqrt(max(transaction_value, 0))
    features[6] = np.log1p(max(quantity, 0))

    # Symbol representation
    features[7] = float(
        sum(ord(c) for c in symbol) % 1000
    ) / 1000.0

    # Additional deterministic interaction features
    features[8] = transaction_value * quantity
    features[9] = risk_score * behavioral_score / 100.0

    # Keep remaining features zero-filled.
    return features