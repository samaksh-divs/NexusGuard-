"""
NexusGuard transaction consumer.

Pipeline:
    RabbitMQ
        ↓
    Validation
        ↓
    Duplicate Guard
        ↓
    Phase 5: Individual Fraud Rules
        ↓
    Phase 6: Behavioral Fraud Analysis
        ↓
    Phase 6: Combined Rule Score
        ↓
    Phase 7: ML Ensemble
        ├── Random Forest
        ├── XGBoost
        └── LSTM
        ↓
    Final Risk Decision
        ↓
    MongoDB
        ↓
    ACK

Any processing failure is rejected with requeue=False and
automatically routed to the RabbitMQ Dead Letter Queue (DLQ).
"""

import json
import logging

from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from pydantic import ValidationError

from app.config.settings import settings
from app.database.repositories import (
    DuplicateTransactionError,
    get_account_history,
    get_transaction,
    insert_transaction,
)
from app.fraud.behavior import analyze_behavior
from app.fraud.engine import calculate_risk_score, combine_scores
from app.ml.service import MLService
from app.validation.schemas import TransactionCreate


logger = logging.getLogger(__name__)


# ================================================================
# PHASE 7 — ML SERVICE
# ================================================================

# Load RF + XGBoost + LSTM only once when the worker starts.
ml_service = MLService()


# ================================================================
# TEST-ONLY DLQ TRIGGER
# ================================================================

TEST_FAILURE_STATUS = "force_fail_test"


def _is_test_failure_trigger(
    transaction: TransactionCreate,
) -> bool:
    return transaction.status == TEST_FAILURE_STATUS


# ================================================================
# FINAL RISK CALCULATION
# ================================================================

def calculate_final_ml_risk(
    rule_score: float,
    ml_score: float,
) -> tuple[float, str, str]:
    """
    Combine Phase 6 rule/behavior score with Phase 7 ML score.

    Rule/behavior score = 40%
    ML ensemble = 60%
    """

    final_score = (
        0.40 * float(rule_score)
        + 0.60 * float(ml_score)
    )

    final_score = float(
        round(
            max(
                0.0,
                min(
                    100.0,
                    final_score,
                ),
            ),
            2,
        )
    )

    if final_score >= 80:

        risk_level = "HIGH"
        decision = "BLOCK"

    elif final_score >= 50:

        risk_level = "MEDIUM"
        decision = "REVIEW"

    else:

        risk_level = "LOW"
        decision = "APPROVE"

    return final_score, risk_level, decision


# ================================================================
# RABBITMQ MESSAGE HANDLER
# ================================================================

def handle_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
) -> None:

    transaction_id = None

    # ============================================================
    # STEP 1 — DECODE + VALIDATE
    # ============================================================

    try:

        raw = json.loads(
            body.decode("utf-8")
        )

        transaction = TransactionCreate(
            **raw
        )

        transaction_id = transaction.transaction_id

        logger.info(
            "[WORKER] Received transaction: %s",
            transaction_id,
        )

    except (
        json.JSONDecodeError,
        ValidationError,
    ):

        logger.exception(
            "[WORKER] Processing failed: malformed message"
        )

        channel.basic_nack(
            delivery_tag=method.delivery_tag,
            requeue=False,
        )

        logger.warning(
            "[WORKER] Message routed to DLQ"
        )

        return

    # ============================================================
    # STEP 2 — TEST DLQ
    # ============================================================

    if _is_test_failure_trigger(transaction):

        logger.warning(
            "[WORKER] Intentional DLQ test: %s",
            transaction_id,
        )

        channel.basic_nack(
            delivery_tag=method.delivery_tag,
            requeue=False,
        )

        logger.warning(
            "[WORKER] Message routed to DLQ: %s",
            transaction_id,
        )

        return

    # ============================================================
    # STEP 3 — DUPLICATE TRANSACTION GUARD
    # ============================================================

    try:

        existing_transaction = get_transaction(
            transaction_id
        )

        if existing_transaction is not None:

            logger.warning(
                "[WORKER] Transaction already processed: %s. "
                "Skipping duplicate.",
                transaction_id,
            )

            channel.basic_ack(
                delivery_tag=method.delivery_tag,
            )

            logger.info(
                "[WORKER] Duplicate ACK sent: %s",
                transaction_id,
            )

            return

    except Exception:

        logger.exception(
            "[WORKER] Failed duplicate check: %s",
            transaction_id,
        )

        channel.basic_nack(
            delivery_tag=method.delivery_tag,
            requeue=False,
        )

        logger.warning(
            "[WORKER] Duplicate-check failure routed to DLQ: %s",
            transaction_id,
        )

        return

    # ============================================================
    # STEP 4 — FRAUD + BEHAVIORAL + ML ANALYSIS
    # ============================================================

    try:

        # --------------------------------------------------------
        # Transaction value
        # --------------------------------------------------------

        transaction_value = float(
            round(
                transaction.price
                * transaction.quantity,
                8,
            )
        )

        # --------------------------------------------------------
        # Phase 5 — Individual Fraud Engine
        # --------------------------------------------------------

        # Transaction has already passed the duplicate guard.
        is_duplicate = False

        individual_result = calculate_risk_score(

            transaction_value=transaction_value,

            quantity=transaction.quantity,

            symbol=transaction.symbol,

            is_duplicate=is_duplicate,

            high_value_threshold=(
                settings.fraud_high_value_threshold
            ),

            very_high_value_threshold=(
                settings.fraud_very_high_value_threshold
            ),

            high_quantity_threshold=(
                settings.fraud_high_quantity_threshold
            ),

            suspicious_symbols=(
                settings.suspicious_symbols_set
            ),
        )

        individual_score = float(
            individual_result.risk_score
        )

        logger.info(
            "[WORKER] Individual fraud score=%s",
            individual_score,
        )

        # --------------------------------------------------------
        # Phase 6 — Behavioral Analysis
        # --------------------------------------------------------

        history = get_account_history(

            transaction.account_id,

            exclude_transaction_id=transaction_id,

            limit=settings.behavior_history_lookback,
        )

        behavioral_result = analyze_behavior(

            current_timestamp=transaction.timestamp,

            current_value=transaction_value,

            current_symbol=transaction.symbol,

            history=history,

            velocity_window_seconds=(
                settings.behavior_velocity_window_seconds
            ),

            velocity_max_transactions=(
                settings.behavior_velocity_max_transactions
            ),

            frequency_window_minutes=(
                settings.behavior_frequency_window_minutes
            ),

            frequency_baseline_window_minutes=(
                settings.behavior_frequency_baseline_window_minutes
            ),

            frequency_multiplier=(
                settings.behavior_frequency_multiplier
            ),

            value_deviation_multiplier=(
                settings.behavior_value_deviation_multiplier
            ),

            value_unusual_multiplier=(
                settings.behavior_value_unusual_multiplier
            ),

            min_history_for_symbol_check=(
                settings.behavior_min_history_for_symbol_check
            ),
        )

        behavioral_score = float(
            behavioral_result.score
        )

        logger.info(
            "[WORKER] Behavioral score=%s",
            behavioral_score,
        )

        # --------------------------------------------------------
        # Phase 6 — Combine rule + behavioral scores
        # --------------------------------------------------------

        (
            combined_score,
            combined_level,
            combined_decision,
        ) = combine_scores(

            individual_score,

            behavioral_score,

            settings.fraud_individual_weight,

            settings.fraud_behavioral_weight,
        )

        combined_score = float(
            combined_score
        )

        logger.info(
            "[WORKER] Rule combined score=%s",
            combined_score,
        )

        # ========================================================
        # PHASE 7 — ML ENSEMBLE
        # ========================================================

        ml_result = ml_service.predict_transaction(

            transaction_value=transaction_value,

            quantity=transaction.quantity,

            symbol=transaction.symbol,

            risk_score=combined_score,

            behavioral_score=behavioral_score,
        )

        # ========================================================
        # Convert ML values to native Python types
        # ========================================================

        ml_rf_probability = float(
            ml_result["rf_probability"]
        )

        ml_xgb_probability = float(
            ml_result["xgb_probability"]
        )

        ml_lstm_probability = float(
            ml_result["lstm_probability"]
        )

        ml_probability = float(
            ml_result["final_probability"]
        )

        ml_risk_score = float(
            ml_result["risk_score"]
        )

        logger.info(
            "[WORKER] ML Ensemble: "
            "RF=%s XGB=%s LSTM=%s FINAL=%s",
            ml_rf_probability,
            ml_xgb_probability,
            ml_lstm_probability,
            ml_probability,
        )

        # --------------------------------------------------------
        # Convert ML probability into 0-100 score
        # --------------------------------------------------------

        ml_score = float(
            ml_probability * 100.0
        )

        # ========================================================
        # PHASE 7 — FINAL DECISION
        # ========================================================

        (
            final_score,
            final_level,
            final_decision,
        ) = calculate_final_ml_risk(

            rule_score=combined_score,

            ml_score=ml_score,
        )

        logger.info(
            "[WORKER] FINAL RISK: "
            "score=%s level=%s decision=%s",
            final_score,
            final_level,
            final_decision,
        )

        # ========================================================
        # STEP 5 — MONGODB STORAGE
        # ========================================================

        fraud_storage = {

            # ----------------------------------------------------
            # Final decision
            # ----------------------------------------------------

            "risk_score": float(
                final_score
            ),

            "risk_level": final_level,

            "decision": final_decision,

            # ----------------------------------------------------
            # Phase 5
            # ----------------------------------------------------

            "fraud_reasons": (
                individual_result.reasons
            ),

            "individual_score": (
                float(individual_score)
            ),

            # ----------------------------------------------------
            # Phase 6
            # ----------------------------------------------------

            "behavioral_score": (
                float(behavioral_score)
            ),

            "combined_score": (
                float(combined_score)
            ),

            "behavioral_signals": [
                signal.to_dict()
                for signal in behavioral_result.signals
            ],

            # ----------------------------------------------------
            # Phase 7 — Individual ML outputs
            # ----------------------------------------------------

            "ml_rf_probability": (
                ml_rf_probability
            ),

            "ml_xgb_probability": (
                ml_xgb_probability
            ),

            "ml_lstm_probability": (
                ml_lstm_probability
            ),

            # ----------------------------------------------------
            # Phase 7 — ML ensemble
            # ----------------------------------------------------

            "ml_probability": (
                ml_probability
            ),

            "ml_risk_score": (
                ml_risk_score
            ),

            "ml_risk_level": (
                ml_result["risk_level"]
            ),

            "ml_decision": (
                ml_result["decision"]
            ),

            # ----------------------------------------------------
            # Phase 7 — Final combined decision
            # ----------------------------------------------------

            "final_risk_score": (
                float(final_score)
            ),

            "final_risk_level": (
                final_level
            ),

            "final_decision": (
                final_decision
            ),
        }

        # --------------------------------------------------------
        # Store everything in ONE transaction document
        # --------------------------------------------------------

        insert_transaction(
            transaction,
            fraud_result=fraud_storage,
        )

        logger.info(
            "[WORKER] Transaction stored successfully: %s",
            transaction_id,
        )

    # ============================================================
    # STEP 6 — DUPLICATE RACE CONDITION
    # ============================================================

    except DuplicateTransactionError:

        logger.warning(
            "[WORKER] Transaction already processed "
            "by another worker: %s",
            transaction_id,
        )

        channel.basic_ack(
            delivery_tag=method.delivery_tag,
        )

        logger.info(
            "[WORKER] Duplicate ACK sent: %s",
            transaction_id,
        )

        return

    # ============================================================
    # STEP 7 — UNEXPECTED FAILURE → DLQ
    # ============================================================

    except Exception:

        logger.exception(
            "[WORKER] Processing failed: %s",
            transaction_id,
        )

        channel.basic_nack(
            delivery_tag=method.delivery_tag,
            requeue=False,
        )

        logger.warning(
            "[WORKER] Message routed to DLQ: %s",
            transaction_id,
        )

        return

    # ============================================================
    # STEP 8 — SUCCESSFUL ACK
    # ============================================================

    channel.basic_ack(
        delivery_tag=method.delivery_tag,
    )

    logger.info(
        "[WORKER] ACK sent: %s",
        transaction_id,
    )


# ================================================================
# START CONSUMER
# ================================================================

def start_consuming(
    channel: BlockingChannel,
) -> None:

    channel.basic_qos(
        prefetch_count=(
            settings.rabbitmq_prefetch_count
        ),
    )

    channel.basic_consume(

        queue=settings.rabbitmq_queue,

        on_message_callback=handle_message,

        auto_ack=False,
    )

    logger.info(
        "Worker consuming from '%s' "
        "(prefetch_count=%s). Waiting for messages...",

        settings.rabbitmq_queue,

        settings.rabbitmq_prefetch_count,
    )

    channel.start_consuming()