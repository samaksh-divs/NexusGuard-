"""
Behavioral & Historical Fraud Detection.

Answers a different question than app/fraud/engine.py (Phase 5):
Phase 5 asks "does THIS transaction look risky on its own?" — this
module asks "does this transaction look unusual compared to THIS
ACCOUNT'S own history?"

Deliberately deterministic and explainable, same philosophy as
Phase 5 — no ML, every triggered signal produces a plain-language
message. `analyze_behavior()` is a pure function: it takes the
current transaction's details plus a list of historical transaction
dicts (as returned by
app.database.repositories.get_account_history()) and returns a
BehavioralResult. It never touches MongoDB itself, which keeps it
independently unit-testable (see tests/test_behavior.py) without a
live database.

Each historical entry in `history` is expected to look like:
    {"timestamp": datetime, "transaction_value": float, "symbol": str}
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Point values are fixed constants — only the thresholds that decide
# whether a signal fires are configurable (passed in as arguments),
# matching the same convention as app/fraud/rules.py.
VELOCITY_POINTS = 25
FREQUENCY_POINTS = 20
VALUE_DEVIATION_POINTS = 25
UNUSUAL_VALUE_POINTS = 20
SYMBOL_ANOMALY_POINTS = 10


@dataclass(frozen=True)
class BehaviorSignal:
    type: str
    severity: str  # "low" | "medium" | "high"
    message: str
    points: int

    def to_dict(self) -> dict:
        return {"type": self.type, "severity": self.severity, "message": self.message}


@dataclass(frozen=True)
class BehavioralResult:
    score: int
    signals: list[BehaviorSignal] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "behavioral_score": self.score,
            "signals": [s.to_dict() for s in self.signals],
        }


def _severity_for_points(points: int) -> str:
    if points >= 25:
        return "high"
    if points >= 15:
        return "medium"
    return "low"


def _check_velocity(
    current_timestamp: datetime, history: list[dict], window_seconds: int, max_transactions: int
) -> BehaviorSignal | None:
    """A. Transaction velocity — too many prior transactions in a short window."""
    window_start = current_timestamp - timedelta(seconds=window_seconds)
    recent_count = sum(1 for h in history if window_start <= h["timestamp"] <= current_timestamp)

    if recent_count >= max_transactions:
        return BehaviorSignal(
            type="velocity_anomaly",
            severity=_severity_for_points(VELOCITY_POINTS),
            message=(
                f"Account made {recent_count} prior transaction(s) within the last "
                f"{window_seconds} seconds (threshold: {max_transactions})."
            ),
            points=VELOCITY_POINTS,
        )
    return None


def _check_frequency(
    current_timestamp: datetime,
    history: list[dict],
    recent_window_minutes: int,
    baseline_window_minutes: int,
    multiplier: float,
) -> BehaviorSignal | None:
    """
    B. High transaction frequency — recent rate vs. the account's own
    longer-term baseline rate.

    IMPORTANT: the baseline window is the older period BEFORE the
    recent window, not the recent window plus older history. If the
    baseline included the recent activity itself, any burst would
    trivially inflate its own baseline and this signal would almost
    never fire correctly (or would fire on completely normal usage,
    since a short recent window's rate is naturally higher than a
    24h-average rate even with no anomaly at all).
    """
    recent_start = current_timestamp - timedelta(minutes=recent_window_minutes)
    baseline_start = current_timestamp - timedelta(minutes=baseline_window_minutes)

    recent_count = sum(1 for h in history if recent_start <= h["timestamp"] <= current_timestamp)
    older_count = sum(1 for h in history if baseline_start <= h["timestamp"] < recent_start)

    older_window_minutes = baseline_window_minutes - recent_window_minutes
    if older_window_minutes <= 0:
        return None  # misconfigured thresholds; nothing meaningful to compare

    baseline_rate = older_count / older_window_minutes  # transactions/minute, BEFORE the recent window
    recent_rate = recent_count / recent_window_minutes

    # Avoid division-by-zero / meaningless comparisons: without any
    # baseline activity, "N times the normal rate" isn't defined, so
    # we simply don't fire this signal rather than guessing.
    if baseline_rate <= 0:
        return None

    if recent_rate > baseline_rate * multiplier:
        return BehaviorSignal(
            type="frequency_anomaly",
            severity=_severity_for_points(FREQUENCY_POINTS),
            message=(
                f"Recent activity ({recent_count} txns / {recent_window_minutes}m) is "
                f"{recent_rate / baseline_rate:.1f}x the account's baseline rate."
            ),
            points=FREQUENCY_POINTS,
        )
    return None


def _historical_average_value(history: list[dict]) -> float:
    if not history:
        return 0.0
    return sum(h["transaction_value"] for h in history) / len(history)


def _check_value_deviation(
    current_value: float, average_value: float, multiplier: float
) -> BehaviorSignal | None:
    """C. Transaction value deviation — current value notably above the account's historical average."""
    if average_value <= 0:
        return None
    if current_value > average_value * multiplier:
        return BehaviorSignal(
            type="value_deviation",
            severity=_severity_for_points(VALUE_DEVIATION_POINTS),
            message=(
                f"Transaction value ({current_value:.2f}) is "
                f"{current_value / average_value:.1f}x the account's historical average ({average_value:.2f})."
            ),
            points=VALUE_DEVIATION_POINTS,
        )
    return None


def _check_unusual_value(
    current_value: float, average_value: float, multiplier: float
) -> BehaviorSignal | None:
    """D. Unusual transaction value — an even more extreme multiple of the historical average than Rule C."""
    if average_value <= 0:
        return None
    if current_value > average_value * multiplier:
        return BehaviorSignal(
            type="unusual_value",
            severity=_severity_for_points(UNUSUAL_VALUE_POINTS),
            message=(
                f"Transaction value ({current_value:.2f}) is an extreme outlier at "
                f"{current_value / average_value:.1f}x the account's historical average ({average_value:.2f})."
            ),
            points=UNUSUAL_VALUE_POINTS,
        )
    return None


def _check_symbol_anomaly(current_symbol: str, history: list[dict], min_history: int) -> BehaviorSignal | None:
    """E. Symbol behavior — trading a symbol the account has no history with."""
    if len(history) < min_history:
        # Not enough history to say what's "normal" for this account yet.
        return None

    historical_symbols = {h["symbol"] for h in history}
    if current_symbol not in historical_symbols:
        return BehaviorSignal(
            type="symbol_anomaly",
            severity=_severity_for_points(SYMBOL_ANOMALY_POINTS),
            message=(
                f"Account has no prior history trading '{current_symbol}' "
                f"(usual symbols: {', '.join(sorted(historical_symbols)) or 'none'})."
            ),
            points=SYMBOL_ANOMALY_POINTS,
        )
    return None


def analyze_behavior(
    *,
    current_timestamp: datetime,
    current_value: float,
    current_symbol: str,
    history: list[dict],
    velocity_window_seconds: int,
    velocity_max_transactions: int,
    frequency_window_minutes: int,
    frequency_baseline_window_minutes: int,
    frequency_multiplier: float,
    value_deviation_multiplier: float,
    value_unusual_multiplier: float,
    min_history_for_symbol_check: int,
) -> BehavioralResult:
    """
    Run every behavioral signal and aggregate the result.

    All thresholds are passed in explicitly (mirroring
    app.fraud.engine.calculate_risk_score) so this stays a pure
    function, easy to unit test with arbitrary values without
    environment setup. `history` should already be limited to a
    reasonable lookback (see BEHAVIOR_HISTORY_LOOKBACK) by the caller
    — this function makes no further limiting decisions itself.
    """
    average_value = _historical_average_value(history)

    checks = [
        _check_velocity(current_timestamp, history, velocity_window_seconds, velocity_max_transactions),
        _check_frequency(
            current_timestamp,
            history,
            frequency_window_minutes,
            frequency_baseline_window_minutes,
            frequency_multiplier,
        ),
        _check_value_deviation(current_value, average_value, value_deviation_multiplier),
        _check_unusual_value(current_value, average_value, value_unusual_multiplier),
        _check_symbol_anomaly(current_symbol, history, min_history_for_symbol_check),
    ]

    signals = [c for c in checks if c is not None]
    total_points = sum(s.points for s in signals)
    score = max(0, min(100, total_points))

    return BehavioralResult(score=score, signals=signals)
