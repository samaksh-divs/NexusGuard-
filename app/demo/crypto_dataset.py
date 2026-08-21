"""Prepared local crypto transaction patterns for demonstrations.

These are synthetic historical-style patterns, not live exchange data.
The adapter expands a small, reviewable pattern set deterministically so
the demo remains repeatable without downloading external data.
"""

from datetime import datetime, timedelta, timezone
import csv
from pathlib import Path
from typing import Any

_PATTERNS = (
    ("BTCUSDT", 50000.0, 0.1, "normal", 0),
    ("BTCUSDT", 65000.0, 0.02, "normal", 0),
    ("ETHUSDT", 3200.0, 0.2, "normal", 0),
    ("BNBUSDT", 580.0, 1.5, "normal", 0),
    ("SOLUSDT", 140.0, 4.0, "normal", 0),
    ("BTCUSDT", 65000.0, 20.0, "suspicious", 1),
    ("BTCUSDT", 65000.0, 30.0, "suspicious", 1),
    ("ETHUSDT", 3200.0, 100.0, "suspicious", 1),
    ("SCAM", 250000.0, 8.0, "suspicious", 1),
    ("BTCUSDT", 1000000.0, 10.0, "suspicious", 1),
)


def load_crypto_dataset(size: int = 120) -> list[dict[str, Any]]:
    """Return deterministic synthetic crypto transaction records."""
    if size < 1:
        return []

    source_path = Path(__file__).parents[2] / "data" / "crypto_demo_transactions.csv"
    source_records = []
    if source_path.exists():
        with source_path.open(newline="", encoding="utf-8") as source_file:
            source_records = list(csv.DictReader(source_file))

    patterns = source_records or [
        {
            "timestamp": "2026-08-21T10:00:00Z",
            "account_id": "DEMO-USER-A",
            "symbol": symbol,
            "price": str(price),
            "quantity": str(quantity),
            "amount": str(price * quantity),
            "transaction_frequency": "1",
            "wallet_age": "720",
            "previous_transaction_count": "24",
            "label": str(label),
        }
        for symbol, price, quantity, _, label in _PATTERNS
    ]
    start = datetime.now(timezone.utc)
    records = []
    for index in range(size):
        source = patterns[index % len(patterns)]
        symbol = source["symbol"]
        price = float(source["price"])
        quantity = float(source["quantity"])
        label = int(source["label"])
        pattern = "suspicious" if label else "normal"
        records.append({
            "timestamp": (start + timedelta(seconds=index)).isoformat(),
            "account_id": source["account_id"],
            "symbol": symbol,
            "price": price,
            "quantity": quantity,
            "amount": round(price * quantity, 8),
            "transaction_frequency": int(source.get("transaction_frequency", 1)),
            "wallet_age": int(source.get("wallet_age", 720)),
            "previous_transaction_count": int(source.get("previous_transaction_count", 24)),
            "label": label,
            "pattern": pattern,
        })
    return records
