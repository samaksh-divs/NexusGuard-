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

from pymongo.errors import DuplicateKeyError

from app.database.mongodb import get_database
from app.validation.schemas import TransactionCreate

logger = logging.getLogger(__name__)


class DuplicateTransactionError(Exception):
    """Raised when a transaction_id already exists in the collection."""


def insert_transaction(transaction: TransactionCreate) -> dict:
    """
    Insert a new transaction document.

    Computes `transaction_value` (price * quantity) server-side rather
    than trusting a client-supplied value, since that's a derived
    field, not raw input.

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
    }

    try:
        result = db["transactions"].insert_one(document)
    except DuplicateKeyError:
        logger.warning("Duplicate transaction_id rejected: %s", transaction.transaction_id)
        raise DuplicateTransactionError(transaction.transaction_id)

    document["_id"] = result.inserted_id
    logger.info("Transaction inserted: %s", transaction.transaction_id)
    return document


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
    """
    return {
        "id": str(doc["_id"]),
        "transaction_id": doc["transaction_id"],
        "timestamp": doc["timestamp"],
        "symbol": doc["symbol"],
        "price": doc["price"],
        "quantity": doc["quantity"],
        "transaction_value": doc["transaction_value"],
        "status": doc["status"],
    }
