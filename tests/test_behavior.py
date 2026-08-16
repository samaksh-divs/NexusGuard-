"""
Behavioral engine tests.

Like tests/test_fraud_engine.py, these call app.fraud.behavior.analyze_behavior()
directly with hand-built history lists — no MongoDB or RabbitMQ
required, since the function is a pure function of its inputs. Run:

    pytest tests/test_behavior.py -v
    pytest -q          # full regression, all phases
"""

from datetime import datetime, timedelta, timezone

from app.fraud.behavior import analyze_behavior
from app.fraud.engine import Decision, RiskLevel, combine_scores

NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)

# Shared thresholds, matching .env.example defaults.
THRESHOLDS = dict(
    velocity_window_seconds=60,
    velocity_max_transactions=5,
    frequency_window_minutes=60,
    frequency_baseline_window_minutes=1440,
    frequency_multiplier=3.0,
    value_deviation_multiplier=3.0,
    value_unusual_multiplier=8.0,
    min_history_for_symbol_check=3,
)


def _hist(minutes_ago: float, value: float = 100.0, symbol: str = "BTCUSDT") -> dict:
    return {"timestamp": NOW - timedelta(minutes=minutes_ago), "transaction_value": value, "symbol": symbol}


def _analyze(**overrides):
    params = dict(
        current_timestamp=NOW,
        current_value=100.0,
        current_symbol="BTCUSDT",
        history=[],
        **THRESHOLDS,
    )
    params.update(overrides)
    return analyze_behavior(**params)


# TEST 1 — no historical transactions
def test_no_history_produces_no_signals():
    result = _analyze(history=[])
    assert result.score == 0
    assert result.signals == []


# TEST 2 — normal transaction, consistent with history
def test_normal_transaction_no_signals():
    history = [_hist(m) for m in (10, 20, 30, 40, 50)]  # spread out, similar value/symbol
    result = _analyze(current_value=100.0, current_symbol="BTCUSDT", history=history)
    assert result.score == 0
    assert result.signals == []


# TEST 3 — high transaction velocity
def test_high_velocity_triggers_signal():
    # 5 transactions within the last 60 seconds
    history = [_hist(m / 60) for m in (5, 10, 15, 20, 25)]  # minutes_ago in seconds via /60
    result = _analyze(history=history)
    types = [s.type for s in result.signals]
    assert "velocity_anomaly" in types
    assert result.score > 0


# TEST 4 — high transaction frequency vs baseline
def test_high_frequency_triggers_signal():
    # Baseline: a handful of transactions spread over 24h (low rate).
    baseline = [_hist(m) for m in (200, 400, 600, 800, 1000, 1200)]
    # Recent burst: several more within the last hour.
    recent = [_hist(m) for m in (5, 10, 15, 20, 25, 30, 35, 40)]
    result = _analyze(history=baseline + recent)
    types = [s.type for s in result.signals]
    assert "frequency_anomaly" in types


# TEST 5 — large value deviation
def test_value_deviation_triggers_signal():
    history = [_hist(m, value=100.0) for m in (10, 20, 30)]  # avg = 100
    result = _analyze(current_value=500.0, history=history)  # 5x average, > 3x deviation threshold
    types = [s.type for s in result.signals]
    assert "value_deviation" in types


# TEST 6 — unusual transaction value (extreme outlier)
def test_unusual_value_triggers_signal():
    history = [_hist(m, value=100.0) for m in (10, 20, 30)]  # avg = 100
    result = _analyze(current_value=1000.0, history=history)  # 10x average, > 8x unusual threshold
    types = [s.type for s in result.signals]
    assert "unusual_value" in types
    assert "value_deviation" in types  # 10x also clears the lower 3x deviation bar


# TEST 7 — symbol anomaly
def test_symbol_anomaly_triggers_signal():
    history = [_hist(m, symbol="BTCUSDT") for m in (10, 20, 30, 40)]
    result = _analyze(current_symbol="ETHUSDT", history=history)
    types = [s.type for s in result.signals]
    assert "symbol_anomaly" in types


def test_symbol_anomaly_not_triggered_with_insufficient_history():
    # Only 2 historical transactions, below min_history_for_symbol_check=3
    history = [_hist(m, symbol="BTCUSDT") for m in (10, 20)]
    result = _analyze(current_symbol="ETHUSDT", history=history)
    types = [s.type for s in result.signals]
    assert "symbol_anomaly" not in types


# TEST 8 — multiple simultaneous signals
def test_multiple_signals_accumulate():
    # Velocity burst + a huge value spike + an unfamiliar symbol.
    history = [_hist(m / 60, value=100.0, symbol="BTCUSDT") for m in (5, 10, 15, 20, 25)]
    result = _analyze(current_value=2000.0, current_symbol="ETHUSDT", history=history)
    types = {s.type for s in result.signals}
    assert {"velocity_anomaly", "value_deviation", "unusual_value", "symbol_anomaly"}.issubset(types)
    assert len(result.signals) >= 4


# TEST 9 — score capped at 100
def test_score_capped_at_100():
    history = [_hist(m / 60, value=100.0, symbol="BTCUSDT") for m in (5, 10, 15, 20, 25, 30, 35, 40)]
    result = _analyze(current_value=100000.0, current_symbol="DOGEUSDT", history=history)
    assert 0 <= result.score <= 100


# TEST 10 — zero historical average handled safely (no div-by-zero)
def test_zero_average_handled_safely():
    # Historical transactions all worth 0 (edge case) — average is 0.
    history = [_hist(m, value=0.0) for m in (10, 20, 30)]
    result = _analyze(current_value=500.0, history=history)
    types = [s.type for s in result.signals]
    assert "value_deviation" not in types
    assert "unusual_value" not in types


# TEST 11 — combined Phase 5 + Phase 6 score
def test_combine_scores_blends_and_bands_correctly():
    combined, level, decision = combine_scores(
        individual_score=80, behavioral_score=20, individual_weight=0.6, behavioral_weight=0.4
    )
    assert combined == round(80 * 0.6 + 20 * 0.4)  # 56
    assert level == RiskLevel.MEDIUM
    assert decision == Decision.REVIEW


def test_combine_scores_clamped_to_100():
    combined, level, decision = combine_scores(
        individual_score=100, behavioral_score=100, individual_weight=0.6, behavioral_weight=0.4
    )
    assert combined == 100
    assert level == RiskLevel.HIGH
    assert decision == Decision.BLOCKED


# TEST 12 — explainability: every triggered signal has a message and type
def test_every_signal_has_type_and_message():
    history = [_hist(m, value=100.0) for m in (10, 20, 30)]
    result = _analyze(current_value=500.0, history=history)
    assert len(result.signals) > 0
    for signal in result.signals:
        assert signal.type
        assert signal.message
        assert signal.severity in ("low", "medium", "high")
        d = signal.to_dict()
        assert set(d.keys()) == {"type", "severity", "message"}
