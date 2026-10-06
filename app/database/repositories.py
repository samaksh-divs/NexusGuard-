"""
Transaction repository — the only place that writes raw MongoDB
queries for the `transactions` collection.

Supports both:

1. TransactionCreate Pydantic models from FastAPI
2. dict transactions produced by the RabbitMQ worker
"""

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.database.mongodb import get_database
from app.validation.schemas import TransactionCreate


logger = logging.getLogger(__name__)


class DuplicateTransactionError(Exception):
    """Raised when a transaction_id already exists in the collection."""


def _normalize_transaction(
    transaction: TransactionCreate | dict[str, Any],
) -> dict[str, Any]:
    """
    Convert either a Pydantic TransactionCreate object or a dictionary
    into a normal Python dictionary.
    """

    if isinstance(transaction, dict):
        return dict(transaction)

    # Pydantic v2
    if hasattr(transaction, "model_dump"):
        return transaction.model_dump()

    # Pydantic v1 fallback
    if hasattr(transaction, "dict"):
        return transaction.dict()

    raise TypeError(
        f"Unsupported transaction type: {type(transaction).__name__}"
    )


def insert_transaction(
    transaction: TransactionCreate | dict[str, Any],
    fraud_result: dict | None = None,
) -> dict:
    """
    Insert a transaction document into MongoDB.

    Supports both FastAPI TransactionCreate objects and dictionaries
    produced by the RabbitMQ worker.

    Fraud, behavioral, and ML results are stored in the same document.
    """

    db = get_database()

    # ============================================================
    # NORMALIZE INPUT
    # ============================================================

    data = _normalize_transaction(transaction)

    # ============================================================
    # EXTRACT COMMON FIELDS
    # ============================================================

    transaction_id = str(
        data.get("transaction_id", "UNKNOWN")
    )

    account_id = data.get(
        "account_id",
        "UNKNOWN",
    )

    symbol = data.get(
        "symbol",
        "",
    )

    # Worker payloads may contain amount.
    # The transaction model normally contains price.
    price = data.get(
        "price",
        data.get("amount", 0.0),
    )

    quantity = data.get(
        "quantity",
        1,
    )

    try:
        price = float(price or 0.0)
    except (TypeError, ValueError):
        price = 0.0

    try:
        quantity = float(quantity or 0.0)
    except (TypeError, ValueError):
        quantity = 0.0

    transaction_value = round(
        price * quantity,
        8,
    )

    timestamp = data.get("timestamp")

    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    status = data.get(
        "status",
        "pending",
    )

    # ============================================================
    # BUILD MONGODB DOCUMENT
    # ============================================================

    document = {
        "transaction_id": transaction_id,
        "timestamp": timestamp,
        "symbol": symbol,
        "price": price,
        "quantity": quantity,
        "transaction_value": transaction_value,
        "status": status,
        "account_id": account_id,
    }

    # ============================================================
    # PRESERVE ADDITIONAL TRANSACTION DATA
    # ============================================================

    ignored_fields = {
        "_id",
        "transaction_id",
        "timestamp",
        "symbol",
        "price",
        "quantity",
        "status",
        "account_id",
        "amount",
    }

    for key, value in data.items():
        if key not in ignored_fields:
            document[key] = value

    # ============================================================
    # ADD FRAUD / BEHAVIORAL / ML RESULTS
    # ============================================================

    if fraud_result is not None:
        document.update(fraud_result)

        document["processed_at"] = datetime.now(
            timezone.utc
        )

    # ============================================================
    # INSERT INTO MONGODB
    # ============================================================

    try:
        result = db["transactions"].insert_one(
            document
        )

    except DuplicateKeyError:
        logger.warning(
            "Duplicate transaction_id rejected: %s",
            transaction_id,
        )

        raise DuplicateTransactionError(
            transaction_id
        )

    document["_id"] = result.inserted_id

    logger.info(
        "Transaction inserted successfully: %s",
        transaction_id,
    )

    return document


def get_account_history(
    account_id: str,
    exclude_transaction_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Return recent transactions for an account.

    Used by the Phase 6 behavioral fraud engine.
    """

    db = get_database()

    query: dict = {
        "account_id": account_id
    }

    if exclude_transaction_id is not None:
        query["transaction_id"] = {
            "$ne": exclude_transaction_id
        }

    cursor = (
        db["transactions"]
        .find(
            query,
            {
                "_id": 0,
                "timestamp": 1,
                "transaction_value": 1,
                "symbol": 1,
            },
        )
        .sort("timestamp", -1)
        .limit(limit)
    )

    return list(cursor)


def get_transaction(
    transaction_id: str,
) -> dict | None:
    """
    Return a single transaction or None.
    """

    db = get_database()

    doc = db["transactions"].find_one(
        {
            "transaction_id": transaction_id
        }
    )

    if doc:
        logger.info(
            "Transaction retrieved: %s",
            transaction_id,
        )

    return doc


def get_transactions(
    limit: int = 50,
) -> list[dict]:
    """
    Return recent transactions.
    """

    db = get_database()

    cursor = (
        db["transactions"]
        .find()
        .sort("timestamp", -1)
        .limit(limit)
    )

    return list(cursor)


def serialize_transaction(
    doc: dict,
) -> dict:
    """
    Convert MongoDB transaction document into a JSON-safe dict.

    Includes:

    Phase 5:
        risk_score
        risk_level
        decision
        fraud_reasons

    Phase 6:
        individual_fraud_score
        behavioral_score
        rule_combined_score
        behavioral_signals

    Phase 7 / ML:
        ml_rf_score
        ml_xgb_score
        ml_lstm_score
        ml_final_probability
        ml_score

    Final decision:
        final_risk_score
        risk_level
        decision
        risk_reasons
    """

    out = {
        "id": str(doc["_id"]),
        "transaction_id": doc["transaction_id"],
        "timestamp": doc["timestamp"],
        "symbol": doc["symbol"],
        "price": doc["price"],
        "quantity": doc["quantity"],
        "transaction_value": doc["transaction_value"],
        "status": doc["status"],
        "account_id": doc.get(
            "account_id",
            "UNKNOWN",
        ),
    }

    # ============================================================
    # OPTIONAL FIELDS
    # ============================================================

    optional_fields = (

        # --------------------------------------------------------
        # Phase 5 — Rule/Fraud Engine
        # --------------------------------------------------------

        "risk_score",
        "risk_level",
        "decision",
        "fraud_reasons",

        # --------------------------------------------------------
        # Phase 6 — Behavioral Analysis
        # --------------------------------------------------------

        "individual_fraud_score",
        "behavioral_score",
        "rule_combined_score",
        "behavioral_signals",

        # --------------------------------------------------------
        # Phase 7 — ML Ensemble
        # --------------------------------------------------------

        "ml_rf_score",
        "ml_xgb_score",
        "ml_lstm_score",
        "ml_final_probability",
        "ml_score",

        # --------------------------------------------------------
        # Final Risk Decision
        # --------------------------------------------------------

        "final_risk_score",
        "risk_reasons",

        # --------------------------------------------------------
        # Processing Metadata
        # --------------------------------------------------------

        "processed_at",
    )

    for field in optional_fields:

        if field in doc:
            out[field] = doc[field]

    return out