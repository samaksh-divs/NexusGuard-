"""
Fraud engine tests.

These tests call app.fraud.engine.calculate_risk_score() directly
with explicit threshold arguments — no MongoDB, RabbitMQ, or FastAPI
required, since the engine is a pure function of its inputs (see the
engine module's docstring). Run with:

    pytest tests/test_fraud_engine.py -v

The force_fail_test / DLQ path (TEST 7) is NOT unit-testable this way
since it requires a live RabbitMQ + worker; that one is verified via
the manual end-to-end procedure described in chat, not here.
"""

from app.fraud.engine import Decision, RiskLevel, calculate_risk_score

# Shared thresholds used across tests, matching the .env.example
# defaults so test expectations are easy to reason about.
HIGH_VALUE_THRESHOLD = 50000.0
VERY_HIGH_VALUE_THRESHOLD = 150000.0
HIGH_QUANTITY_THRESHOLD = 5.0
NO_SUSPICIOUS_SYMBOLS: set[str] = set()


def _score(**overrides):
    params = dict(
        transaction_value=100.0,
        quantity=0.01,
        symbol="BTCUSDT",
        is_duplicate=False,
        high_value_threshold=HIGH_VALUE_THRESHOLD,
        very_high_value_threshold=VERY_HIGH_VALUE_THRESHOLD,
        high_quantity_threshold=HIGH_QUANTITY_THRESHOLD,
        suspicious_symbols=NO_SUSPICIOUS_SYMBOLS,
    )
    params.update(overrides)
    return calculate_risk_score(**params)


# TEST 1 — normal transaction
def test_normal_transaction_is_low_and_approved():
    result = _score(transaction_value=100.0, quantity=0.01)
    assert result.risk_level == RiskLevel.LOW
    assert result.decision == Decision.APPROVED
    assert result.reasons == []


# TEST 2 — high value increases risk
def test_high_value_increases_risk():
    baseline = _score(transaction_value=100.0)
    high_value = _score(transaction_value=60000.0)
    assert high_value.risk_score > baseline.risk_score
    assert "high-value threshold" in high_value.reasons[0]


# TEST 3 — very high risk transaction is blocked
def test_very_high_risk_is_blocked():
    result = _score(transaction_value=200000.0, quantity=10.0)
    assert result.risk_level == RiskLevel.HIGH
    assert result.decision == Decision.BLOCKED


# TEST 4 — multiple triggered rules accumulate
def test_multiple_rules_accumulate_risk():
    single_rule = _score(transaction_value=60000.0)
    multiple_rules = _score(transaction_value=60000.0, quantity=10.0, is_duplicate=True)
    assert multiple_rules.risk_score > single_rule.risk_score
    assert len(multiple_rules.reasons) > len(single_rule.reasons)


# TEST 5 — score boundaries always hold, even for an extreme input
def test_score_is_always_within_0_to_100():
    result = _score(
        transaction_value=10_000_000.0,
        quantity=1000.0,
        is_duplicate=True,
        symbol="SCAMCOIN",
        suspicious_symbols={"SCAMCOIN"},
    )
    assert 0 <= result.risk_score <= 100


# TEST 6 — every triggered rule produces a reason
def test_every_triggered_rule_has_a_reason():
    result = _score(transaction_value=60000.0, quantity=10.0, is_duplicate=True)
    # 3 rules triggered: high value, high quantity, duplicate
    assert len(result.reasons) == 3
    assert all(isinstance(reason, str) and reason for reason in result.reasons)


def test_suspicious_symbol_rule():
    result = _score(symbol="RUGPULL", suspicious_symbols={"RUGPULL"})
    assert result.risk_score > 0
    assert "suspicious-symbol list" in result.reasons[0]


def test_medium_risk_maps_to_review():
    # A single high-value hit (30 points) lands in the 31-70 MEDIUM band... 
    # actually 30 is LOW boundary-inclusive, so combine two rules to land in MEDIUM.
    result = _score(transaction_value=60000.0, quantity=10.0)
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.decision == Decision.REVIEW
