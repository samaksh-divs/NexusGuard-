"""
NexusGuard — FastAPI entry point.

Phase 9C:
  - MongoDB lifecycle
  - RabbitMQ publisher lifecycle
  - Asynchronous transaction publishing
  - Phase 5 individual fraud analysis
  - Phase 6 behavioral analysis
  - Phase 7 ML ensemble
  - Final risk decision
  - DLQ-backed worker processing
  - Phase 8 dashboard API
  - Phase 8 frontend CORS support
  - Phase 9 alert management
  - Phase 9 alert REST API
  - Phase 9 alert dashboard API
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.alerts.service import ensure_alert_indexes
from app.api.alert_dashboard import (
    router as alert_dashboard_router,
)
from app.api.dashboard import router as dashboard_router
from app.api.demo import router as demo_router
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
    check_publisher_health,
    close_publisher,
    connect_publisher,
    publish_transaction,
)
from app.messaging.kafka_producer import (
    check_kafka_health,
    close_kafka_producer,
    publish_kafka_transaction,
)
from app.ml.model_status import get_model_availability
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

    logger.info("Starting NexusGuard Phase 9C...")

    try:

        # --------------------------------------------------------
        # MongoDB
        # --------------------------------------------------------

        connect_to_mongo()

        ensure_alert_indexes()

        logger.info(
            "MongoDB connection initialized"
        )

        # --------------------------------------------------------
        # RabbitMQ
        # --------------------------------------------------------

        connect_publisher()

        logger.info(
            "RabbitMQ publisher initialized"
        )

        logger.info(
            "NexusGuard Phase 9C startup complete"
        )

        yield

    finally:

        logger.info(
            "Shutting down NexusGuard..."
        )

        # --------------------------------------------------------
        # Close RabbitMQ
        # --------------------------------------------------------

        try:

            close_publisher()

        except Exception:

            logger.exception(
                "Error while closing RabbitMQ publisher"
            )

        try:
            close_kafka_producer()
        except Exception:
            logger.exception("Error while closing Kafka producer")

        # --------------------------------------------------------
        # Close MongoDB
        # --------------------------------------------------------

        try:

            close_mongo_connection()

        except Exception:

            logger.exception(
                "Error while closing MongoDB connection"
            )

        logger.info(
            "NexusGuard shutdown complete"
        )


# ================================================================
# FASTAPI APPLICATION
# ================================================================

app = FastAPI(
    title=settings.app_name,
    description=(
        "Real-time cryptocurrency transaction fraud detection "
        "platform using MongoDB, RabbitMQ, behavioral fraud "
        "detection, Random Forest, XGBoost, LSTM, a Phase 8 "
        "security dashboard, and Phase 9 alert management."
    ),
    version="0.9.0",
    lifespan=lifespan,
)


# ================================================================
# CORS — PHASE 8 FRONTEND
# ================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================================================
# PHASE 8 DASHBOARD ROUTER
# ================================================================

app.include_router(
    dashboard_router
)


# ================================================================
# PHASE 9C ALERT DASHBOARD ROUTER
# ================================================================

app.include_router(
    alert_dashboard_router
)

app.include_router(demo_router)


# ================================================================
# ROOT
# ================================================================

@app.get("/")
def read_root():
    """
    Basic endpoint confirming that the API is running.
    """

    return {
        "project": settings.app_name,
        "status": "running",
        "phase": (
            "9C - Dashboard + ML ensemble "
            "+ final risk decision + alerts"
        ),
        "dashboard": "enabled",
        "alerts": "enabled",
        "architecture": {
            "database": "MongoDB",
            "message_broker": "RabbitMQ",
            "dead_letter_queue": "transaction_dlq",
            "ml_models": [
                "Random Forest",
                "XGBoost",
                "LSTM",
            ],
            "dashboard": "Phase 8",
            "alert_management": "Phase 9",
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
    kafka_ok = check_kafka_health() if settings.kafka_enabled else False
    rabbitmq_ok = check_publisher_health()
    kafka_status = (
        "connected"
        if kafka_ok
        else "unavailable"
        if settings.kafka_enabled
        else "not_configured"
    )
    nifi_status = "configured" if settings.nifi_enabled else "not_configured"

    return {
        "status": (
            "healthy"
            if mongo_ok and rabbitmq_ok and (not settings.kafka_enabled or kafka_ok)
            else "degraded"
        ),

        "environment": settings.app_env,

        "mongodb": (
            "connected"
            if mongo_ok
            else "unavailable"
        ),

        "rabbitmq": "connected" if rabbitmq_ok else "unavailable",

        "kafka": kafka_status,

        "nifi": nifi_status,

        "dashboard": "enabled",

        "alerts": "enabled",

        "phase": "9/10",
    }


# ================================================================
# DIRECT TEST TRANSACTION
# ================================================================

@app.post(
    "/transactions/test",
    status_code=201,
)
def create_test_transaction(
    transaction: TransactionCreate,
):
    """
    Development-only synchronous MongoDB endpoint.

    This bypasses RabbitMQ and the fraud/ML worker.

    Use /transactions/publish for the real pipeline.
    """

    try:

        document = insert_transaction(
            transaction
        )

    except DuplicateTransactionError:

        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaction "
                f"'{transaction.transaction_id}' "
                f"already exists."
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

    return serialize_transaction(
        document
    )


# ================================================================
# ASYNCHRONOUS RABBITMQ PIPELINE
# ================================================================

@app.post(
    "/transactions/publish",
    status_code=202,
)
async def publish_test_transaction(
    transaction: TransactionCreate,
):
    """
    Publish a transaction to RabbitMQ.
    """

    payload = transaction.model_dump(
        mode="json"
    )

    payload["amount"] = payload.get("amount") or round(
        float(payload["price"]) * float(payload["quantity"]),
        8,
    )

    try:
        if get_transaction(transaction.transaction_id):
            return {
                "status": "already_processed",
                "transaction_id": transaction.transaction_id,
                "transport": "rabbitmq",
            }

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
            detail=(
                "Failed to publish transaction "
                "to RabbitMQ."
            ),
        )

    return {
        "status": "published",

        "transaction_id": (
            transaction.transaction_id
        ),

        "message": (
            "Transaction accepted for "
            "asynchronous processing."
        ),
        "transport": "rabbitmq",
    }


@app.post(
    "/transactions/kafka/publish",
    status_code=202,
)
async def publish_kafka_test_transaction(
    transaction: TransactionCreate,
):
    """Publish directly to Kafka for the streaming-path comparison."""
    if not settings.kafka_enabled:
        raise HTTPException(
            status_code=503,
            detail="Kafka publishing is not configured. Set KAFKA_ENABLED=true.",
        )

    payload = transaction.model_dump(mode="json")
    payload["amount"] = payload.get("amount") or round(
        float(payload["price"]) * float(payload["quantity"]),
        8,
    )

    try:
        publish_kafka_transaction(payload)
    except Exception:
        logger.exception(
            "Failed to publish Kafka transaction %s",
            transaction.transaction_id,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to publish transaction to Kafka.",
        )

    return {
        "status": "published",
        "transport": "kafka",
        "topic": settings.kafka_transaction_topic,
        "transaction_id": transaction.transaction_id,
    }


# ================================================================
# LIST TRANSACTIONS
# ================================================================

@app.get("/transactions")
def list_transactions(
    limit: int = 50,
):
    """
    Return recent transactions.
    """

    if limit < 1:

        raise HTTPException(
            status_code=400,
            detail=(
                "limit must be greater than 0."
            ),
        )

    if limit > 500:
        limit = 500

    docs = get_transactions(
        limit=limit
    )

    return [
        serialize_transaction(doc)
        for doc in docs
    ]


# ================================================================
# GET SINGLE TRANSACTION
# ================================================================

@app.get(
    "/transactions/{transaction_id}"
)
def read_transaction(
    transaction_id: str,
):
    """
    Return a single transaction.
    """

    doc = get_transaction(
        transaction_id
    )

    if doc is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' "
                f"not found."
            ),
        )

    return serialize_transaction(
        doc
    )


# ================================================================
# RISK ENDPOINT
# ================================================================

@app.get(
    "/transactions/{transaction_id}/risk"
)
def read_transaction_risk(
    transaction_id: str,
):
    """
    Return complete fraud analysis.

    Includes:

        Phase 5
        Phase 6
        Phase 7 ML
        Final decision

    Supports both old and current ML field names.
    """

    doc = get_transaction(
        transaction_id
    )

    if doc is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' "
                f"not found."
            ),
        )

    # ------------------------------------------------------------
    # CURRENT ML FIELD MAPPING
    # ------------------------------------------------------------

    ml_rf_probability = doc.get(
        "ml_rf_score",
        doc.get(
            "ml_rf_probability"
        ),
    )

    ml_xgb_probability = doc.get(
        "ml_xgb_score",
        doc.get(
            "ml_xgb_probability"
        ),
    )

    ml_lstm_probability = doc.get(
        "ml_lstm_score",
        doc.get(
            "ml_lstm_probability"
        ),
    )

    ml_probability = doc.get(
        "ml_final_probability",
        doc.get(
            "ml_probability"
        ),
    )

    ml_risk_score = doc.get(
        "ml_score",
        doc.get(
            "ml_risk_score"
        ),
    )

    # ------------------------------------------------------------
    # DETERMINE WHETHER ANY ANALYSIS EXISTS
    # ------------------------------------------------------------

    has_risk_analysis = any(
        field in doc
        for field in (
            "risk_score",
            "final_risk_score",
            "individual_fraud_score",
            "ml_final_probability",
            "ml_probability",
        )
    )

    if not has_risk_analysis:

        raise HTTPException(
            status_code=404,
            detail=(
                f"No risk analysis available "
                f"for transaction "
                f"'{transaction_id}'."
            ),
        )

    # ------------------------------------------------------------
    # BEHAVIORAL SIGNALS
    # ------------------------------------------------------------

    behavioral_signals = doc.get(
        "behavioral_signals",
        [],
    )

    # ------------------------------------------------------------
    # REASONS
    # ------------------------------------------------------------

    reasons = []

    stored_reasons = doc.get(
        "risk_reasons",
        doc.get(
            "fraud_reasons",
            [],
        ),
    )

    if isinstance(
        stored_reasons,
        list,
    ):

        reasons.extend(
            stored_reasons
        )

    for signal in behavioral_signals:

        if isinstance(
            signal,
            dict,
        ):

            message = signal.get(
                "message"
            )

            if message and message not in reasons:

                reasons.append(
                    message
                )

    # ------------------------------------------------------------
    # RETURN COMPLETE RISK ANALYSIS
    # ------------------------------------------------------------

    return {

        # --------------------------------------------------------
        # Transaction
        # --------------------------------------------------------

        "transaction_id": (
            doc["transaction_id"]
        ),

        "account_id": (
            doc.get(
                "account_id",
                "UNKNOWN",
            )
        ),

        # --------------------------------------------------------
        # Phase 5
        # --------------------------------------------------------

        "individual_score": (
            doc.get(
                "individual_fraud_score",
                doc.get(
                    "individual_score",
                    0,
                ),
            )
        ),

        "fraud_reasons": (
            doc.get(
                "fraud_reasons",
                doc.get(
                    "risk_reasons",
                    [],
                ),
            )
        ),

        # --------------------------------------------------------
        # Phase 6
        # --------------------------------------------------------

        "behavioral_score": (
            doc.get(
                "behavioral_score",
                0,
            )
        ),

        "combined_score": (
            doc.get(
                "rule_combined_score",
                doc.get(
                    "combined_score",
                    doc.get(
                        "risk_score",
                        0,
                    ),
                ),
            )
        ),

        "behavioral_signals": (
            behavioral_signals
        ),

        # --------------------------------------------------------
        # Phase 7 ML
        # --------------------------------------------------------

        "ml_rf_probability": (
            ml_rf_probability
        ),

        "ml_xgb_probability": (
            ml_xgb_probability
        ),

        "ml_lstm_probability": (
            ml_lstm_probability
        ),

        "ml_probability": (
            ml_probability
        ),

        "model_availability": get_model_availability(),

        "ml_risk_score": (
            ml_risk_score
        ),

        # The current worker does not store
        # separate ML-only risk_level/decision.
        # These are therefore exposed as the
        # final NexusGuard decision.

        "ml_risk_level": (
            doc.get(
                "ml_risk_level",
                doc.get(
                    "risk_level"
                ),
            )
        ),

        "ml_decision": (
            doc.get(
                "ml_decision",
                doc.get(
                    "decision"
                ),
            )
        ),

        # --------------------------------------------------------
        # Final Decision
        # --------------------------------------------------------

        "risk_score": (
            doc.get(
                "risk_score",
                doc.get(
                    "final_risk_score"
                ),
            )
        ),

        "risk_level": (
            doc.get(
                "risk_level"
            )
        ),

        "decision": (
            doc.get(
                "decision"
            )
        ),

        "final_risk_score": (
            doc.get(
                "final_risk_score",
                doc.get(
                    "risk_score"
                ),
            )
        ),

        "final_risk_level": (
            doc.get(
                "final_risk_level",
                doc.get(
                    "risk_level"
                ),
            )
        ),

        "final_decision": (
            doc.get(
                "final_decision",
                doc.get(
                    "decision"
                ),
            )
        ),

        # --------------------------------------------------------
        # Combined Reasons
        # --------------------------------------------------------

        "reasons": reasons,

        # --------------------------------------------------------
        # Processing Timestamp
        # --------------------------------------------------------

        "processed_at": (
            doc.get(
                "processed_at"
            )
        ),
    }


# ================================================================
# BEHAVIOR ENDPOINT
# ================================================================

@app.get(
    "/transactions/{transaction_id}/behavior"
)
def read_transaction_behavior(
    transaction_id: str,
):
    """
    Return behavioral fraud analysis only.
    """

    doc = get_transaction(
        transaction_id
    )

    if doc is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' "
                f"not found."
            ),
        )

    if "behavioral_score" not in doc:

        raise HTTPException(
            status_code=404,
            detail=(
                f"No behavioral analysis "
                f"available for transaction "
                f"'{transaction_id}'."
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

        "behavioral_score": (
            behavioral_score
        ),

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

@app.get(
    "/transactions/{transaction_id}/ml"
)
def read_transaction_ml(
    transaction_id: str,
):
    """
    Return Phase 7 ML analysis.

    Current worker fields:

        ml_rf_score
        ml_xgb_score
        ml_lstm_score
        ml_final_probability
        ml_score

    Backward-compatible fields:

        ml_rf_probability
        ml_xgb_probability
        ml_lstm_probability
        ml_probability
        ml_risk_score
    """

    doc = get_transaction(
        transaction_id
    )

    if doc is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' "
                f"not found."
            ),
        )

    # ------------------------------------------------------------
    # CURRENT FIELD NAMES
    # ------------------------------------------------------------

    rf_probability = doc.get(
        "ml_rf_score",
        doc.get(
            "ml_rf_probability"
        ),
    )

    xgb_probability = doc.get(
        "ml_xgb_score",
        doc.get(
            "ml_xgb_probability"
        ),
    )

    lstm_probability = doc.get(
        "ml_lstm_score",
        doc.get(
            "ml_lstm_probability"
        ),
    )

    ml_probability = doc.get(
        "ml_final_probability",
        doc.get(
            "ml_probability"
        ),
    )

    ml_risk_score = doc.get(
        "ml_score",
        doc.get(
            "ml_risk_score"
        ),
    )

    # ------------------------------------------------------------
    # CHECK ML ANALYSIS
    # ------------------------------------------------------------

    if ml_probability is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"No ML analysis available "
                f"for transaction "
                f"'{transaction_id}'."
            ),
        )

    # ------------------------------------------------------------
    # RETURN ML RESULTS
    # ------------------------------------------------------------

    return {

        "transaction_id": (
            doc["transaction_id"]
        ),

        # --------------------------------------------------------
        # Individual ML Models
        # --------------------------------------------------------

        "rf_probability": (
            rf_probability
        ),

        "xgb_probability": (
            xgb_probability
        ),

        "lstm_probability": (
            lstm_probability
        ),

        # --------------------------------------------------------
        # ML Ensemble
        # --------------------------------------------------------

        "ml_probability": (
            ml_probability
        ),

        "ml_risk_score": (
            ml_risk_score
        ),

        # --------------------------------------------------------
        # ML Decision
        # --------------------------------------------------------

        "ml_risk_level": (
            doc.get(
                "ml_risk_level",
                doc.get(
                    "risk_level"
                ),
            )
        ),

        "ml_decision": (
            doc.get(
                "ml_decision",
                doc.get(
                    "decision"
                ),
            )
        ),

        # --------------------------------------------------------
        # FINAL NEXUSGUARD DECISION
        # --------------------------------------------------------

        "final_risk_score": (
            doc.get(
                "final_risk_score",
                doc.get(
                    "risk_score"
                ),
            )
        ),

        "final_risk_level": (
            doc.get(
                "final_risk_level",
                doc.get(
                    "risk_level"
                ),
            )
        ),

        "final_decision": (
            doc.get(
                "final_decision",
                doc.get(
                    "decision"
                ),
            )
        ),
    }


# ================================================================
# EXPLANATION ENDPOINT
# ================================================================

@app.get(
    "/transactions/{transaction_id}/explanation"
)
def read_transaction_explanation(
    transaction_id: str,
):
    """
    Return a structured explanation of the risk decision
    suitable for the UI.
    """

    doc = get_transaction(
        transaction_id
    )

    if doc is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Transaction "
                f"'{transaction_id}' "
                f"not found."
            ),
        )

    # Reconstruct Signals from string reasons
    reasons = doc.get("fraud_reasons", doc.get("risk_reasons", []))
    signals = []
    critical_rule_triggered = False

    for reason in reasons:
        if "High transaction value" in reason and "Very high" not in reason and "Critical fraud rule" not in reason:
            signals.append({
                "type": "rule",
                "name": "High Transaction Value",
                "description": reason,
                "severity": "HIGH",
                "contribution": 25
            })
        elif "Very high transaction value" in reason and "Critical fraud rule" not in reason:
            signals.append({
                "type": "rule",
                "name": "Very High Transaction Value",
                "description": reason,
                "severity": "CRITICAL",
                "contribution": 25
            })
        elif "High transaction quantity" in reason:
            signals.append({
                "type": "rule",
                "name": "High Transaction Quantity",
                "description": reason,
                "severity": "HIGH",
                "contribution": 25
            })
        elif "Suspicious transaction symbol" in reason:
            signals.append({
                "type": "rule",
                "name": "Suspicious Asset",
                "description": reason,
                "severity": "HIGH",
                "contribution": 25
            })
        elif "Critical fraud rule triggered" in reason:
            critical_rule_triggered = True
        else:
            signals.append({
                "type": "rule",
                "name": "Risk Signal",
                "description": reason,
                "severity": "MEDIUM",
                "contribution": 0
            })

    # Recommendation and Final Decision
    final_decision = doc.get("final_decision", doc.get("decision", "APPROVE"))
    recommendation = "BLOCK TRANSACTION" if final_decision == "BLOCK" else ("REVIEW TRANSACTION" if final_decision == "REVIEW" else "APPROVE TRANSACTION")

    return {
        "transaction_id": doc["transaction_id"],
        "risk_score": doc.get("final_risk_score", doc.get("risk_score", 0.0)),
        "risk_level": doc.get("final_risk_level", doc.get("risk_level", "LOW")),
        "decision": final_decision,
        "critical_rule_triggered": critical_rule_triggered,
        "signals": signals,
        "behavior": {
            "score": doc.get("behavioral_score", 0.0),
            "signals": doc.get("behavioral_signals", [])
        },
        "ml": {
            "random_forest": doc.get("ml_rf_score", doc.get("ml_rf_probability", 0.0)),
            "xgboost": doc.get("ml_xgb_score", doc.get("ml_xgb_probability", 0.0)),
            "lstm": doc.get("ml_lstm_score", doc.get("ml_lstm_probability", 0.0)),
            "ensemble": doc.get("ml_final_probability", doc.get("ml_probability", 0.0))
        },
        "recommendation": recommendation
    }


# ================================================================
# END OF APPLICATION
# ================================================================