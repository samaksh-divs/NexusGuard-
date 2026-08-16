"""
NexusGuard — FastAPI entry point.

Phase 7:
  - MongoDB lifecycle
  - RabbitMQ publisher lifecycle
  - Asynchronous transaction publishing
  - Phase 5 individual fraud analysis
  - Phase 6 behavioral analysis
  - Phase 7 ML ensemble
  - Final risk decision
  - DLQ-backed worker processing
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.config.settings import settings
from app.database.mongodb import (
    check_mongo_health,
    close_mongo_connection,
    connect_to_mongo,
)
from app.database.repositories import (
    DuplicateTransactionError,
    get_transaction,
    get_transactions,
    insert_transaction,
    serialize_transaction,
)
from app.fraud.engine import risk_level_for_score
from app.messaging.publisher import (
    close_publisher,
    connect_publisher,
    publish_transaction,
)
from app.validation.schemas import TransactionCreate


# ================================================================
# LOGGING
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


# ================================================================
# APPLICATION LIFESPAN
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup/shutdown lifecycle.
    """

    logger.info("Starting NexusGuard Phase 7...")

    try:
        connect_to_mongo()
        logger.info("MongoDB connection initialized")

        connect_publisher()
        logger.info("RabbitMQ publisher initialized")

        logger.info("NexusGuard Phase 7 startup complete")

        yield

    finally:
        logger.info("Shutting down NexusGuard...")

        try:
            close_publisher()
        except Exception:
            logger.exception(
                "Error while closing RabbitMQ publisher"
            )

        try:
            close_mongo_connection()
        except Exception:
            logger.exception(
                "Error while closing MongoDB connection"
            )

        logger.info("NexusGuard shutdown complete")


# ================================================================
# FASTAPI APPLICATION
# ================================================================

app = FastAPI(
    title=settings.app_name,
    description=(
        "Real-time cryptocurrency transaction fraud detection "
        "platform using MongoDB, RabbitMQ, behavioral fraud "
        "detection, and a Random Forest + XGBoost + LSTM ML ensemble."
    ),
    version="0.7.0",
    lifespan=lifespan,
)


# ================================================================
# ROOT
# ================================================================

@app.get("/")
def read_root():
    """Basic endpoint confirming that the API is running."""

    return {
        "project": settings.app_name,
        "status": "running",
        "phase": "7 - ML ensemble + final risk decision",
        "architecture": {
            "database": "MongoDB",
            "message_broker": "RabbitMQ",
            "dead_letter_queue": "transaction_dlq",
            "ml_models": [
                "Random Forest",
                "XGBoost",
                "LSTM",
            ],
        },
    }


# ================================================================
# HEALTH
# ================================================================

@app.get("/health")
def health_check():
    """
    Check actual MongoDB connectivity.

    RabbitMQ is initialized through the application lifespan.
    """

    mongo_ok = check_mongo_health()

    return {
        "status": "healthy" if mongo_ok else "degraded",
        "environment": settings.app_env,
        "mongodb": (
            "connected"
            if mongo_ok
            else "unavailable"
        ),
        "rabbitmq": "initialized",
        "phase": "7",
    }


# ================================================================
# DIRECT TEST TRANSACTION
# ================================================================

@app.post("/transactions/test", status_code=201)
def create_test_transaction(
    transaction: TransactionCreate,
):
    """
    Development-only synchronous MongoDB endpoint.

    This bypasses RabbitMQ and the fraud/ML worker.

    Use /transactions/publish for the real Phase 7 pipeline.
    """

    try:
        document = insert_transaction(transaction)

    except DuplicateTransactionError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaction "
                f"'{transaction.transaction_id}' already exists."
            ),
        )

    except Exception:
        logger.exception(
            "Failed to insert transaction %s",
            transaction.transaction_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to store transaction.",
        )

    return serialize_transaction(document)


# ================================================================
# ASYNCHRONOUS RABBITMQ PIPELINE
# ================================================================

@app.post("/transactions/publish", status_code=202)
async def publish_test_transaction(transaction: TransactionCreate):

    """
    Publish a transaction to RabbitMQ.

    Pipeline:

        FastAPI
           ↓
        RabbitMQ Exchange
           ↓
        transaction_queue
           ↓
        Transaction Worker
           ↓
        Validation
           ↓
        Individual Fraud Rules
           ↓
        Behavioral Analysis
           ↓
        RF + XGBoost + LSTM
           ↓
        Final Risk Decision
           ↓
        MongoDB
           ↓
        ACK

    Failed processing:

        Worker
           ↓
        NACK (requeue=False)
           ↓
        Dead Letter Exchange
           ↓
        transaction_dlq
    """

    payload = transaction.model_dump(mode="json")

    try:
        publish_transaction(payload)

        logger.info(
            "Transaction published successfully: %s",
            transaction.transaction_id,
        )

    except Exception:
        logger.exception(
            "Failed to publish transaction %s",
            transaction.transaction_id,
        )

        raise HTTPException(
            status_code=502,
            detail="Failed to publish transaction to RabbitMQ.",
        )

    return {
        "status": "published",
        "transaction_id": transaction.transaction_id,
        "message": (
            "Transaction accepted for asynchronous processing."
        ),
    }


# ================================================================
# LIST TRANSACTIONS
# ================================================================

@app.get("/transactions")
def list_transactions(limit: int = 50):
    """Return recent transactions."""

    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="limit must be greater than 0.",
        )

    if limit > 500:
        limit = 500

    docs = get_transactions(limit=limit)

    return [
        serialize_transaction(doc)
        for doc in docs
    ]


# ================================================================
# GET SINGLE TRANSACTION
# ================================================================

@app.get("/transactions/{transaction_id}")
def read_transaction(
    transaction_id: str,
):
    """Return a single transaction."""

    doc = get_transaction(transaction_id)

    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' not found."
            ),
        )

    return serialize_transaction(doc)


# ================================================================
# RISK ENDPOINT — PHASE 7
# ================================================================

@app.get("/transactions/{transaction_id}/risk")
def read_transaction_risk(
    transaction_id: str,
):
    """
    Return complete fraud analysis.

    Includes Phase 5, Phase 6, Phase 7 ML results,
    and the final combined decision.
    """

    doc = get_transaction(transaction_id)

    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' not found."
            ),
        )

    if "risk_score" not in doc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No risk analysis available for "
                f"transaction '{transaction_id}'."
            ),
        )

    behavioral_signals = doc.get(
        "behavioral_signals",
        [],
    )

    reasons = list(
        doc.get(
            "fraud_reasons",
            [],
        )
    )

    for signal in behavioral_signals:
        if isinstance(signal, dict):
            message = signal.get("message")

            if message:
                reasons.append(message)

    return {
        # Transaction
        "transaction_id": doc["transaction_id"],
        "account_id": doc.get(
            "account_id",
            "UNKNOWN",
        ),

        # Phase 5
        "individual_score": doc.get(
            "individual_score",
            0,
        ),

        "fraud_reasons": doc.get(
            "fraud_reasons",
            [],
        ),

        # Phase 6
        "behavioral_score": doc.get(
            "behavioral_score",
            0,
        ),

        "combined_score": doc.get(
            "combined_score",
            doc.get("risk_score", 0),
        ),

        "behavioral_signals": behavioral_signals,

        # Phase 7 ML
        "ml_rf_probability": doc.get(
            "ml_rf_probability"
        ),

        "ml_xgb_probability": doc.get(
            "ml_xgb_probability"
        ),

        "ml_lstm_probability": doc.get(
            "ml_lstm_probability"
        ),

        "ml_probability": doc.get(
            "ml_probability"
        ),

        "ml_risk_score": doc.get(
            "ml_risk_score"
        ),

        "ml_risk_level": doc.get(
            "ml_risk_level"
        ),

        "ml_decision": doc.get(
            "ml_decision"
        ),

        # Final decision
        "risk_score": doc.get(
            "risk_score"
        ),

        "risk_level": doc.get(
            "risk_level"
        ),

        "decision": doc.get(
            "decision"
        ),

        "final_risk_score": doc.get(
            "final_risk_score",
            doc.get("risk_score"),
        ),

        "final_risk_level": doc.get(
            "final_risk_level",
            doc.get("risk_level"),
        ),

        "final_decision": doc.get(
            "final_decision",
            doc.get("decision"),
        ),

        # Combined reasons
        "reasons": reasons,

        # Processing timestamp
        "processed_at": doc.get(
            "processed_at"
        ),
    }


# ================================================================
# BEHAVIOR ENDPOINT
# ================================================================

@app.get("/transactions/{transaction_id}/behavior")
def read_transaction_behavior(
    transaction_id: str,
):
    """Return behavioral fraud analysis only."""

    doc = get_transaction(transaction_id)

    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' not found."
            ),
        )

    if "behavioral_score" not in doc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No behavioral analysis available "
                f"for transaction '{transaction_id}'."
            ),
        )

    behavioral_score = float(
        doc["behavioral_score"]
    )

    return {
        "transaction_id": (
            doc["transaction_id"]
        ),

        "account_id": (
            doc.get(
                "account_id",
                "UNKNOWN",
            )
        ),

        "behavioral_score": behavioral_score,

        "risk_level": (
            risk_level_for_score(
                behavioral_score
            ).value
        ),

        "signals": (
            doc.get(
                "behavioral_signals",
                [],
            )
        ),
    }


# ================================================================
# ML ENDPOINT
# ================================================================

@app.get("/transactions/{transaction_id}/ml")
def read_transaction_ml(
    transaction_id: str,
):
    """Return only Phase 7 ML results."""

    doc = get_transaction(transaction_id)

    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' not found."
            ),
        )

    if "ml_probability" not in doc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No ML analysis available "
                f"for transaction '{transaction_id}'."
            ),
        )

    return {
        "transaction_id": (
            doc["transaction_id"]
        ),

        "rf_probability": (
            doc.get(
                "ml_rf_probability"
            )
        ),

        "xgb_probability": (
            doc.get(
                "ml_xgb_probability"
            )
        ),

        "lstm_probability": (
            doc.get(
                "ml_lstm_probability"
            )
        ),

        "ml_probability": (
            doc.get(
                "ml_probability"
            )
        ),

        "ml_risk_score": (
            doc.get(
                "ml_risk_score"
            )
        ),

        "ml_risk_level": (
            doc.get(
                "ml_risk_level"
            )
        ),

        "ml_decision": (
            doc.get(
                "ml_decision"
            )
        ),

        "final_risk_score": (
            doc.get(
                "final_risk_score"
            )
        ),

        "final_risk_level": (
            doc.get(
                "final_risk_level"
            )
        ),

        "final_decision": (
            doc.get(
                "final_decision"
            )
        ),
    }