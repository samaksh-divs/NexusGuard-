"""
Transaction repository — the only place that writes raw MongoDB
queries for the `transactions` collection.

Why a repository layer:
FastAPI routes should describe HTTP behavior (status codes, request/
response shape), not contain `db.transactions.find_one(...)` calls
directly. Keeping queries here means:

  1. Routes stay thin and readable.
  2. RabbitMQ workers (Phase 8+) and ML workers can reuse these exact
     same functions instead of duplicating query logic.
  3. If we ever change how a transaction is stored, there's one place
     to update instead of hunting through route handlers.
"""

import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.database.mongodb import get_database
from app.validation.schemas import TransactionCreate

logger = logging.getLogger(__name__)


class DuplicateTransactionError(Exception):
    """Raised when a transaction_id already exists in the collection."""


def insert_transaction(transaction: TransactionCreate, fraud_result: dict | None = None) -> dict:
    """
    Insert a new transaction document.

    Computes `transaction_value` (price * quantity) server-side rather
    than trusting a client-supplied value, since that's a derived
    field, not raw input.

    `fraud_result`, if provided (Phase 5), is a dict as produced by
    FraudResult.to_dict() — risk_score / risk_level / decision /
    fraud_reasons — and is merged directly into the same document
    rather than a separate collection, per the project's requirement
    to extend the existing transaction record. Callers that don't run
    fraud analysis (e.g. POST /transactions/test) simply omit it, and
    the document is stored exactly as it was in Phase 2.

    Raises DuplicateTransactionError if transaction_id already exists
    (enforced by the unique index created in mongodb.py).
    """
    db = get_database()

    document = {
        "transaction_id": transaction.transaction_id,
        "timestamp": transaction.timestamp,
        "symbol": transaction.symbol,
        "price": transaction.price,
        "quantity": transaction.quantity,
        "transaction_value": round(transaction.price * transaction.quantity, 8),
        "status": transaction.status,
        "account_id": transaction.account_id,
    }

    if fraud_result is not None:
        document.update(fraud_result)
        document["processed_at"] = datetime.now(timezone.utc)

    try:
        result = db["transactions"].insert_one(document)
    except DuplicateKeyError:
        logger.warning("Duplicate transaction_id rejected: %s", transaction.transaction_id)
        raise DuplicateTransactionError(transaction.transaction_id)

    document["_id"] = result.inserted_id
    logger.info("Transaction inserted: %s", transaction.transaction_id)
    return document


def get_account_history(account_id: str, exclude_transaction_id: str | None = None, limit: int = 100) -> list[dict]:
    """
    Return an account's most recent transactions, most recent first,
    for use by the behavioral fraud engine (app/fraud/behavior.py).

    `limit` bounds how much history is ever loaded into memory — we
    deliberately never load "all history" for an account, only the
    most recent `limit` transactions (see BEHAVIOR_HISTORY_LOOKBACK).
    `exclude_transaction_id` lets the worker exclude the
    transaction currently being processed if it was already inserted
    (not the normal Phase 6 order, but keeps this function safe to
    reuse regardless of call order).

    Only the fields behavioral analysis actually needs are projected
    back, keeping the query and the in-memory payload small.
    """
    db = get_database()
    query: dict = {"account_id": account_id}
    if exclude_transaction_id is not None:
        query["transaction_id"] = {"$ne": exclude_transaction_id}

    cursor = (
        db["transactions"]
        .find(query, {"_id": 0, "timestamp": 1, "transaction_value": 1, "symbol": 1})
        .sort("timestamp", -1)
        .limit(limit)
    )
    return list(cursor)


def get_transaction(transaction_id: str) -> dict | None:
    """Return a single transaction document, or None if it doesn't exist."""
    db = get_database()
    doc = db["transactions"].find_one({"transaction_id": transaction_id})
    if doc:
        logger.info("Transaction retrieved: %s", transaction_id)
    return doc


def get_transactions(limit: int = 50) -> list[dict]:
    """
    Return recent transactions, most recent first.

    `limit` is capped implicitly by the caller (route) — this function
    just applies whatever limit it's given.
    """
    db = get_database()
    cursor = db["transactions"].find().sort("timestamp", -1).limit(limit)
    return list(cursor)


def serialize_transaction(doc: dict) -> dict:
    """
    Convert a raw MongoDB document into a JSON-safe dict.

    MongoDB's `_id` is a BSON ObjectId, which FastAPI/Pydantic can't
    serialize to JSON directly. We convert it to a plain string field
    called `id` and drop the raw `_id` key.

    Fraud fields (risk_score, risk_level, decision, fraud_reasons,
    processed_at, individual_score, behavioral_score, combined_score,
    behavioral_signals) are included only when present on the
    document — transactions inserted via POST /transactions/test (no
    fraud analysis run) simply won't have them, and this stays
    backward compatible with Phase 1-4 response shapes.
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
        "account_id": doc.get("account_id", "UNKNOWN"),  # .get() for pre-Phase-6 documents
    }

    for field in (
        "risk_score",
        "risk_level",
        "decision",
        "fraud_reasons",
        "processed_at",
        "individual_score",
        "behavioral_score",
        "combined_score",
        "behavioral_signals",
    ):
        if field in doc:
            out[field] = doc[field]

    return out
