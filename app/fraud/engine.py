"""
Fraud Detection & Risk Analysis Engine.

This is the single entry point the worker calls: calculate_risk_score().
It runs every rule in app/fraud/rules.py against the transaction,
accumulates their points into a 0-100 risk score, maps that score to
a risk level, and maps the level to a decision. Every triggered rule
contributes a human-readable reason — the engine never just returns a
bare boolean.

Deliberately rule-based (no ML) for Phase 5. This module is the
natural place a future ML-based scorer would plug in without
disturbing the worker or storage layer, since both speak the same
FraudResult shape.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.fraud.rules import (
    rule_duplicate,
    rule_high_quantity,
    rule_high_value,
    rule_suspicious_symbol,
    rule_very_high_value,
)


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"


# Risk level boundaries, inclusive on the upper end of each band.
_LOW_MAX = 30
_MEDIUM_MAX = 70

_LEVEL_TO_DECISION = {
    RiskLevel.LOW: Decision.APPROVED,
    RiskLevel.MEDIUM: Decision.REVIEW,
    RiskLevel.HIGH: Decision.BLOCKED,
}


@dataclass(frozen=True)
class FraudResult:
    risk_score: int
    risk_level: RiskLevel
    decision: Decision
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON/Mongo-safe representation (enums -> their string values)."""
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "decision": self.decision.value,
            "fraud_reasons": self.reasons,
        }


def _risk_level_for_score(score: int) -> RiskLevel:
    if score <= _LOW_MAX:
        return RiskLevel.LOW
    if score <= _MEDIUM_MAX:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def calculate_risk_score(
    *,
    transaction_value: float,
    quantity: float,
    symbol: str,
    is_duplicate: bool = False,
    high_value_threshold: float,
    very_high_value_threshold: float,
    high_quantity_threshold: float,
    suspicious_symbols: set[str],
) -> FraudResult:
    """
    Run every fraud rule and aggregate the result.

    All thresholds are passed in explicitly (rather than this module
    importing `settings` directly) so the engine stays a pure function
    of its inputs — easy to unit test with arbitrary threshold values
    without needing environment variables set up.
    """
    triggered = [
        rule_high_value(transaction_value, high_value_threshold),
        rule_very_high_value(transaction_value, very_high_value_threshold),
        rule_high_quantity(quantity, high_quantity_threshold),
        rule_duplicate(is_duplicate),
        rule_suspicious_symbol(symbol, suspicious_symbols),
    ]

    reasons: list[str] = []
    total_points = 0
    for result in triggered:
        if result is not None:
            total_points += result.points
            reasons.append(result.reason)

    # Clamp to the documented 0-100 range even if future rules push
    # the raw sum higher.
    risk_score = max(0, min(100, total_points))
    risk_level = _risk_level_for_score(risk_score)
    decision = _LEVEL_TO_DECISION[risk_level]

    return FraudResult(risk_score=risk_score, risk_level=risk_level, decision=decision, reasons=reasons)
