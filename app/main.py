"""
NexusGuard — FastAPI entry point.

Phase 2 adds:
  - MongoDB connection lifecycle (connect on startup, close on shutdown)
  - /health now reports real MongoDB connectivity
  - POST /transactions/test, GET /transactions, GET /transactions/{id}

No RabbitMQ, ML, or SHAP yet — those come in later phases.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.config.settings import settings
from app.database.mongodb import check_mongo_health, close_mongo_connection, connect_to_mongo
from app.database.repositories import (
    DuplicateTransactionError,
    get_transaction,
    get_transactions,
    insert_transaction,
    serialize_transaction,
)
from app.fraud.engine import risk_level_for_score
from app.messaging.publisher import close_publisher, connect_publisher, publish_transaction
from app.validation.schemas import TransactionCreate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect once, shared for the app's whole lifetime.
    connect_to_mongo()
    connect_publisher()
    yield
    # Shutdown: release connections cleanly.
    close_publisher()
    close_mongo_connection()


app = FastAPI(
    title=settings.app_name,
    description="Real-time cryptocurrency transaction fraud detection platform.",
    version="0.6.0",
    lifespan=lifespan,
)


@app.get("/")
def read_root():
    """Basic root endpoint — confirms the API is reachable."""
    return {
        "project": settings.app_name,
        "status": "running",
        "phase": "6 - behavioral & historical fraud detection",
    }


@app.get("/health")
def health_check():
    """
    Health-check endpoint.

    Reports actual MongoDB connectivity rather than assuming it's fine
    just because the FastAPI process is up.
    """
    mongo_ok = check_mongo_health()
    return {
        "status": "healthy" if mongo_ok else "degraded",
        "environment": settings.app_env,
        "mongodb": "connected" if mongo_ok else "unavailable",
    }


@app.post("/transactions/test", status_code=201)
def create_test_transaction(transaction: TransactionCreate):
    """
    Development-only endpoint to test the MongoDB pipeline without
    RabbitMQ. In a later phase, this will instead publish to
    RabbitMQ, and the worker will do the actual insert.
    """
    try:
        document = insert_transaction(transaction)
    except DuplicateTransactionError:
        raise HTTPException(
            status_code=409,
            detail=f"Transaction '{transaction.transaction_id}' already exists.",
        )
    except Exception:
        logger.exception("Failed to insert transaction %s", transaction.transaction_id)
        raise HTTPException(status_code=500, detail="Failed to store transaction.")

    return serialize_transaction(document)


@app.post("/transactions/publish", status_code=202)
def publish_test_transaction(transaction: TransactionCreate):
    """
    Development endpoint for the ASYNCHRONOUS pipeline:

        FastAPI -> RabbitMQ (transaction_exchange / transaction.new)
                -> transaction_queue -> worker -> MongoDB

    Unlike POST /transactions/test (which inserts into MongoDB
    directly and synchronously), this endpoint only publishes the
    message to RabbitMQ and returns immediately. MongoDB storage is
    handled separately by the worker process
    (app/workers/transaction_worker.py), which must be running for
    the transaction to actually end up in the database.

    202 Accepted (not 201 Created) is used deliberately: nothing has
    been created yet at the point this response is sent, only queued.
    """
    payload = transaction.model_dump(mode="json")

    try:
        publish_transaction(payload)
    except Exception:
        logger.exception("Failed to publish transaction %s", transaction.transaction_id)
        raise HTTPException(status_code=502, detail="Failed to publish transaction to RabbitMQ.")

    return {"status": "published", "transaction_id": transaction.transaction_id}


@app.get("/transactions")
def list_transactions(limit: int = 50):
    """Return recent transactions, most recent first."""
    docs = get_transactions(limit=limit)
    return [serialize_transaction(doc) for doc in docs]


@app.get("/transactions/{transaction_id}")
def read_transaction(transaction_id: str):
    """Return a single transaction, or 404 if it doesn't exist."""
    doc = get_transaction(transaction_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")
    return serialize_transaction(doc)


@app.get("/transactions/{transaction_id}/risk")
def read_transaction_risk(transaction_id: str):
    """
    Return the fraud/risk analysis for a transaction.

    404 if the transaction doesn't exist at all, OR if it exists but
    was inserted via POST /transactions/test (which skips fraud
    analysis) — in either case there's no risk result to return.
    Only transactions processed through the asynchronous
    RabbitMQ -> worker pipeline (POST /transactions/publish) carry a
    risk_score.

    Phase 6: risk_score/risk_level/decision now reflect the COMBINED
    score (individual + behavioral), same field names as Phase 5 so
    existing callers of this endpoint keep working. individual_score/
    behavioral_score/combined_score are additive fields. For
    transactions processed before Phase 6 existed (which only have
    the flat Phase 5 fields), individual_score/combined_score fall
    back to the original risk_score and behavioral_score defaults to 0
    — there's no behavioral data to report for those older records.
    """
    doc = get_transaction(transaction_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")

    if "risk_score" not in doc:
        raise HTTPException(
            status_code=404,
            detail=f"No risk analysis available for transaction '{transaction_id}'.",
        )

    behavioral_signals = doc.get("behavioral_signals", [])
    reasons = list(doc.get("fraud_reasons", [])) + [s["message"] for s in behavioral_signals]

    return {
        "transaction_id": doc["transaction_id"],
        "individual_score": doc.get("individual_score", doc["risk_score"]),
        "behavioral_score": doc.get("behavioral_score", 0),
        "combined_score": doc.get("combined_score", doc["risk_score"]),
        "risk_score": doc["risk_score"],
        "risk_level": doc["risk_level"],
        "decision": doc["decision"],
        "reasons": reasons,
    }


@app.get("/transactions/{transaction_id}/behavior")
def read_transaction_behavior(transaction_id: str):
    """
    Return only the behavioral analysis for a transaction — how it
    compares to the account's own historical activity, independent of
    the Phase 5 individual-transaction score.

    404 if the transaction doesn't exist, or if it wasn't processed
    through the async pipeline (no behavioral_score stored).
    """
    doc = get_transaction(transaction_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")

    if "behavioral_score" not in doc:
        raise HTTPException(
            status_code=404,
            detail=f"No behavioral analysis available for transaction '{transaction_id}'.",
        )

    behavioral_score = doc["behavioral_score"]
    return {
        "transaction_id": doc["transaction_id"],
        "account_id": doc.get("account_id", "UNKNOWN"),
        "behavioral_score": behavioral_score,
        "risk_level": risk_level_for_score(behavioral_score).value,
        "signals": doc.get("behavioral_signals", []),
    }
