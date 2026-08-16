"""
Individual fraud rules.

Each rule function takes whatever raw values it needs and returns a
RuleResult (points + human-readable reason) if the rule is
triggered, or None if it isn't. Keeping rules as small, independent
functions — rather than one large if/elif block — means each one is
independently testable and new rules can be added without touching
existing ones.

None of these rules mutate anything or talk to MongoDB/RabbitMQ
directly; they're pure functions of their inputs. That keeps the
engine (engine.py) easy to reason about and easy to unit test.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleResult:
    points: int
    reason: str


# Point values are fixed constants (not environment-configurable) —
# only the THRESHOLDS that decide whether a rule fires are
# configurable, per the project's requirement to avoid hard-coding
# thresholds while not over-engineering point weights into config too.
HIGH_VALUE_POINTS = 30
VERY_HIGH_VALUE_POINTS = 20
HIGH_QUANTITY_POINTS = 25
DUPLICATE_POINTS = 40
SUSPICIOUS_SYMBOL_POINTS = 35


def rule_high_value(transaction_value: float, threshold: float) -> RuleResult | None:
    """RULE 1 — transaction value above the configured threshold."""
    if transaction_value > threshold:
        return RuleResult(
            points=HIGH_VALUE_POINTS,
            reason=f"Transaction value ({transaction_value:.2f}) exceeds high-value threshold ({threshold:.2f}).",
        )
    return None


def rule_very_high_value(transaction_value: float, threshold: float) -> RuleResult | None:
    """RULE 2 — transaction value above a significantly higher threshold, adds on top of Rule 1."""
    if transaction_value > threshold:
        return RuleResult(
            points=VERY_HIGH_VALUE_POINTS,
            reason=f"Transaction value ({transaction_value:.2f}) exceeds very-high-value threshold ({threshold:.2f}).",
        )
    return None


def rule_high_quantity(quantity: float, threshold: float) -> RuleResult | None:
    """RULE 3 — unusually large quantity."""
    if quantity > threshold:
        return RuleResult(
            points=HIGH_QUANTITY_POINTS,
            reason=f"Transaction quantity ({quantity}) exceeds high-quantity threshold ({threshold}).",
        )
    return None


def rule_duplicate(is_duplicate: bool) -> RuleResult | None:
    """
    RULE 4 — duplicate transaction_id.

    This is a READ-ONLY signal used for scoring/explainability only.
    The actual duplicate-prevention guarantee still comes from
    MongoDB's unique index on transaction_id and
    DuplicateTransactionError (app/database/repositories.py) — this
    rule does not weaken or replace that. It exists so that if a
    duplicate somehow reaches this point, the risk explanation
    reflects it.
    """
    if is_duplicate:
        return RuleResult(
            points=DUPLICATE_POINTS,
            reason="A transaction with this transaction_id already exists.",
        )
    return None


def rule_suspicious_symbol(symbol: str, suspicious_symbols: set[str]) -> RuleResult | None:
    """
    RULE 5 — configurable suspicious-symbol list.

    Deliberately empty by default (see settings.py) — no symbol is
    inherently treated as fraudulent. This only demonstrates that the
    engine CAN flag configured symbols, for whoever operates the
    system to configure based on their own risk policy.
    """
    if symbol.upper() in suspicious_symbols:
        return RuleResult(
            points=SUSPICIOUS_SYMBOL_POINTS,
            reason=f"Symbol '{symbol}' is on the configured suspicious-symbol list.",
        )
    return None
