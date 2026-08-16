"""
Transaction repository — the only place that writes raw MongoDB
queries for the `transactions` collection.
"""

import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.database.mongodb import get_database
from app.validation.schemas import TransactionCreate

logger = logging.getLogger(__name__)


class DuplicateTransactionError(Exception):
    """Raised when a transaction_id already exists in the collection."""


def insert_transaction(
    transaction: TransactionCreate,
    fraud_result: dict | None = None,
) -> dict:
    """
    Insert a new transaction document.

    Fraud, behavioral, and ML results are stored directly inside
    the same transaction document.
    """

    db = get_database()

    document = {
        "transaction_id": transaction.transaction_id,
        "timestamp": transaction.timestamp,
        "symbol": transaction.symbol,
        "price": transaction.price,
        "quantity": transaction.quantity,
        "transaction_value": round(
            transaction.price * transaction.quantity,
            8,
        ),
        "status": transaction.status,
        "account_id": transaction.account_id,
    }

    # Add fraud + behavioral + ML results when available.
    if fraud_result is not None:
        document.update(fraud_result)
        document["processed_at"] = datetime.now(timezone.utc)

    try:
        result = db["transactions"].insert_one(document)

    except DuplicateKeyError:
        logger.warning(
            "Duplicate transaction_id rejected: %s",
            transaction.transaction_id,
        )
        raise DuplicateTransactionError(
            transaction.transaction_id
        )

    document["_id"] = result.inserted_id

    logger.info(
        "Transaction inserted: %s",
        transaction.transaction_id,
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


def get_transaction(transaction_id: str) -> dict | None:
    """Return a single transaction or None."""

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


def get_transactions(limit: int = 50) -> list[dict]:
    """Return recent transactions."""

    db = get_database()

    cursor = (
        db["transactions"]
        .find()
        .sort("timestamp", -1)
        .limit(limit)
    )

    return list(cursor)


def serialize_transaction(doc: dict) -> dict:
    """
    Convert MongoDB transaction document into a JSON-safe dict.

    Includes:

    Phase 5:
        risk_score
        risk_level
        decision
        fraud_reasons

    Phase 6:
        individual_score
        behavioral_score
        combined_score
        behavioral_signals

    ML ensemble:
        ml_rf_probability
        ml_xgb_probability
        ml_lstm_probability
        ml_probability
        ml_risk_score
        ml_risk_level
        ml_decision
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

    # Optional fraud, behavioral, and ML fields.
    optional_fields = (
        # Phase 5
        "risk_score",
        "risk_level",
        "decision",
        "fraud_reasons",
        "processed_at",

        # Phase 6
        "individual_score",
        "behavioral_score",
        "combined_score",
        "behavioral_signals",

        # ML Ensemble
        "ml_rf_probability",
        "ml_xgb_probability",
        "ml_lstm_probability",
        "ml_probability",
        "ml_risk_score",
        "ml_risk_level",
        "ml_decision",
    )

    for field in optional_fields:
        if field in doc:
            out[field] = doc[field]

    return out