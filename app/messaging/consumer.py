"""
NexusGuard Transaction Consumer

Consumes transactions from RabbitMQ, evaluates fraud/risk,
runs the ML ensemble, stores the transaction in MongoDB,
and creates operational alerts for HIGH/BLOCK decisions.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.alerts.service import create_alert_for_transaction
from app.config import settings
from app.database.repositories import insert_transaction


logger = logging.getLogger(__name__)


# ================================================================
# LOGGING
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ================================================================
# ML IMPORTS
# ================================================================

try:
    from app.ml.service import (
        load_models,
        predict_transaction_risk,
    )

except ImportError:
    load_models = None
    predict_transaction_risk = None


# ================================================================
# RISK SCORING
# ================================================================

def calculate_final_ml_risk(
    rule_score: float,
    ml_score: float,
    critical_rule_triggered: bool = False,
) -> tuple[float, str, str]:

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

    # ------------------------------------------------------------
    # CRITICAL FRAUD OVERRIDE
    # ------------------------------------------------------------

    if critical_rule_triggered:

        final_score = max(
            final_score,
            80.0,
        )

        return (
            float(round(final_score, 2)),
            "HIGH",
            "BLOCK",
        )

    # ------------------------------------------------------------
    # NORMAL THRESHOLDS
    # ------------------------------------------------------------

    if final_score >= 80.0:

        return (
            final_score,
            "HIGH",
            "BLOCK",
        )

    if final_score >= 50.0:

        return (
            final_score,
            "MEDIUM",
            "REVIEW",
        )

    return (
        final_score,
        "LOW",
        "APPROVE",
    )


# ================================================================
# HELPERS
# ================================================================

def _get_value(
    data: dict[str, Any],
    *names: str,
    default: Any = None,
) -> Any:

    for name in names:

        if name in data:

            return data[name]

    return default


# ================================================================
# RULE ENGINE
# ================================================================

def _calculate_rule_score(
    transaction: dict[str, Any],
) -> tuple[
    float,
    float,
    float,
    list[str],
]:

    reasons: list[str] = []

    # ------------------------------------------------------------
    # AMOUNT
    # ------------------------------------------------------------

    amount = float(
        _get_value(
            transaction,
            "amount",
            "transaction_amount",
            "value",
            "price",
            default=0.0,
        )
        or 0.0
    )

    # ------------------------------------------------------------
    # QUANTITY
    # ------------------------------------------------------------

    quantity = float(
        _get_value(
            transaction,
            "quantity",
            "qty",
            default=0.0,
        )
        or 0.0
    )

    # ------------------------------------------------------------
    # SYMBOL
    # ------------------------------------------------------------

    symbol = str(
        _get_value(
            transaction,
            "symbol",
            "description",
            default="",
        )
        or ""
    )

    # ------------------------------------------------------------
    # INDIVIDUAL FRAUD SCORE
    # ------------------------------------------------------------

    individual_score = 0.0

    if amount >= 50000:

        individual_score += 25.0

        reasons.append(
            "High transaction value"
        )

    if amount >= 100000:

        individual_score += 25.0

        reasons.append(
            "Very high transaction value"
        )

    if quantity >= 5:

        individual_score += 25.0

        reasons.append(
            "High transaction quantity"
        )

    suspicious_symbols = {
        "TEST_FRAUD",
        "FRAUD",
        "SCAM",
        "BLACKLIST",
    }

    if symbol.upper() in suspicious_symbols:

        individual_score += 25.0

        reasons.append(
            "Suspicious transaction symbol"
        )

    individual_score = min(
        individual_score,
        100.0,
    )

    # ------------------------------------------------------------
    # BEHAVIORAL SCORE
    # ------------------------------------------------------------

    behavioral_score = float(
        transaction.get(
            "behavioral_score",
            0.0,
        )
        or 0.0
    )

    behavioral_score = min(
        max(
            behavioral_score,
            0.0,
        ),
        100.0,
    )

    # ------------------------------------------------------------
    # COMBINED RULE SCORE
    # ------------------------------------------------------------

    combined_score = float(
        round(
            (
                0.60 * individual_score
                + 0.40 * behavioral_score
            ),
            2,
        )
    )

    return (
        individual_score,
        behavioral_score,
        combined_score,
        reasons,
    )


# ================================================================
# ML PREDICTION
# ================================================================

def _run_ml_prediction(
    transaction: dict[str, Any],
) -> tuple[
    float,
    float,
    float,
    float,
]:

    # ------------------------------------------------------------
    # ML SERVICE UNAVAILABLE
    # ------------------------------------------------------------

    if predict_transaction_risk is None:

        logger.warning(
            "[ML] Prediction service unavailable. "
            "Using ML score of 0."
        )

        return (
            0.0,
            0.0,
            0.0,
            0.0,
        )

    # ------------------------------------------------------------
    # CALL ML SERVICE
    # ------------------------------------------------------------

    result = predict_transaction_risk(
        transaction
    )

    # ------------------------------------------------------------
    # DICTIONARY RESULT
    # ------------------------------------------------------------

    if isinstance(result, dict):

        rf = float(
            result.get(
                "rf_probability",
                0.0,
            )
        )

        xgb = float(
            result.get(
                "xgb_probability",
                0.0,
            )
        )

        lstm = float(
            result.get(
                "lstm_probability",
                0.0,
            )
        )

        final = float(
            result.get(
                "final_probability",
                0.0,
            )
        )

        logger.info(
            "[ML] Prediction received: "
            "RF=%.4f XGB=%.4f LSTM=%.4f FINAL=%.4f",
            rf,
            xgb,
            lstm,
            final,
        )

        return (
            rf,
            xgb,
            lstm,
            final,
        )

    # ------------------------------------------------------------
    # TUPLE / LIST RESULT
    # ------------------------------------------------------------

    if (
        isinstance(
            result,
            (tuple, list),
        )
        and len(result) >= 4
    ):

        rf = float(result[0])
        xgb = float(result[1])
        lstm = float(result[2])
        final = float(result[3])

        logger.info(
            "[ML] Tuple/list prediction received: "
            "RF=%.4f XGB=%.4f LSTM=%.4f FINAL=%.4f",
            rf,
            xgb,
            lstm,
            final,
        )

        return (
            rf,
            xgb,
            lstm,
            final,
        )

    raise RuntimeError(
        "Unexpected ML prediction result format."
    )


# ================================================================
# TRANSACTION HANDLER
# ================================================================

def handle_message(
    transaction: dict[str, Any],
) -> None:

    start_time = time.time()
    started_iso = datetime.now(timezone.utc).isoformat()

    transaction_id = str(
        _get_value(
            transaction,
            "transaction_id",
            "id",
            default="UNKNOWN",
        )
    )

    account_id = str(
        _get_value(
            transaction,
            "account_id",
            "user_id",
            "customer_id",
            default="UNKNOWN",
        )
    )

    logger.info(
        "[WORKER] Received transaction: %s",
        transaction_id,
    )

    # ============================================================
    # RULE ENGINE
    # ============================================================

    t_rules_start = time.time()
    (
        individual_score,
        behavioral_score,
        combined_score,
        reasons,
    ) = _calculate_rule_score(
        transaction
    )
    feature_latency_ms = round((time.time() - t_rules_start) * 1000.0, 2)

    logger.info(
        "[WORKER] Individual fraud score=%.1f",
        individual_score,
    )

    logger.info(
        "[WORKER] Behavioral score=%.1f",
        behavioral_score,
    )

    logger.info(
        "[WORKER] Rule combined score=%.1f",
        combined_score,
    )

    # ============================================================
    # ML ENSEMBLE
    # ============================================================

    t_ml_start = time.time()
    (
        rf_score,
        xgb_score,
        lstm_score,
        ml_probability,
    ) = _run_ml_prediction(
        transaction
    )
    ml_latency_ms = round((time.time() - t_ml_start) * 1000.0, 2)

    logger.info(
        "[WORKER] ML Ensemble: "
        "RF=%.4f XGB=%.4f LSTM=%.4f FINAL=%.4f",
        rf_score,
        xgb_score,
        lstm_score,
        ml_probability,
    )

    ml_score = float(
        ml_probability * 100.0
    )

    logger.info(
        "[WORKER] ML Risk Score=%.2f",
        ml_score,
    )

    # ============================================================
    # CRITICAL RISK
    # ============================================================

    transaction_value = float(
        _get_value(
            transaction,
            "amount",
            "transaction_amount",
            "value",
            "price",
            default=0.0,
        )
        or 0.0
    )

    very_high_threshold = float(
        getattr(
            settings,
            "fraud_very_high_value_threshold",
            100000.0,
        )
    )

    critical_rule_triggered = (
        individual_score >= 75.0
        and transaction_value >= very_high_threshold
    )

    logger.info(
        "[WORKER] Critical rule check: "
        "triggered=%s amount=%.2f threshold=%.2f",
        critical_rule_triggered,
        transaction_value,
        very_high_threshold,
    )

    if critical_rule_triggered:

        reasons.append(
            "Critical fraud rule triggered: "
            "high fraud score with very high transaction value"
        )

    # ============================================================
    # FINAL RISK
    # ============================================================

    (
        final_score,
        final_level,
        final_decision,
    ) = calculate_final_ml_risk(
        rule_score=combined_score,
        ml_score=ml_score,
        critical_rule_triggered=critical_rule_triggered,
    )

    decision_iso = datetime.now(timezone.utc).isoformat()
    total_latency_ms = round((time.time() - start_time) * 1000.0, 2)

    logger.info(
        "[WORKER] FINAL RISK: "
        "score=%.2f level=%s decision=%s latency=%.2fms",
        final_score,
        final_level,
        final_decision,
        total_latency_ms,
    )

    # ============================================================
    # STORE TRANSACTION
    # ============================================================

    stored_transaction = dict(
        transaction
    )

    stored_transaction.update(
        {
            "transaction_id": transaction_id,
            "account_id": account_id,

            # Latency and Timestamps
            "processing_started_at": started_iso,
            "decision_generated_at": decision_iso,
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": total_latency_ms,
            "feature_latency_ms": feature_latency_ms,
            "ml_latency_ms": ml_latency_ms,

            # Rule-based fraud results
            "individual_fraud_score": individual_score,
            "behavioral_score": behavioral_score,
            "rule_combined_score": combined_score,

            # ML ensemble results
            "ml_rf_score": rf_score,
            "ml_xgb_score": xgb_score,
            "ml_lstm_score": lstm_score,
            "ml_final_probability": ml_probability,
            "ml_score": ml_score,

            # Final risk decision
            "final_risk_score": final_score,
            "risk_score": final_score,
            "risk_level": final_level,
            "decision": final_decision,
            "final_risk_level": final_level,
            "final_decision": final_decision,
            "risk_reasons": reasons,
            "fraud_reasons": reasons,

            # ML decision fields
            "ml_risk_score": ml_score,
            "ml_risk_level": (
                "HIGH"
                if ml_score >= 80
                else "MEDIUM"
                if ml_score >= 50
                else "LOW"
            ),
            "ml_decision": (
                "BLOCK"
                if ml_score >= 80
                else "REVIEW"
                if ml_score >= 50
                else "APPROVE"
            ),
        }
    )

    insert_transaction(
        stored_transaction
    )

    logger.info(
        "[WORKER] Transaction stored successfully: %s",
        transaction_id,
    )

    # ============================================================
    # OPERATIONAL ALERT
    # ============================================================

    if (
        final_level == "HIGH"
        or final_decision == "BLOCK"
    ):

        try:

            alert = create_alert_for_transaction(
                transaction_id=transaction_id,
                account_id=account_id,
                risk_score=final_score,
                risk_level=final_level,
                decision=final_decision,
                reasons=reasons,
            )

            logger.info(
                "[WORKER] Operational alert created: "
                "transaction_id=%s alert_id=%s",
                transaction_id,
                alert.get("alert_id"),
            )

        except Exception:

            logger.exception(
                "[WORKER] Failed to create operational alert: "
                "transaction_id=%s",
                transaction_id,
            )

    else:

        logger.info(
            "[WORKER] No operational alert required: "
            "transaction_id=%s risk_level=%s decision=%s",
            transaction_id,
            final_level,
            final_decision,
        )


# ================================================================
# RABBITMQ CALLBACK
# ================================================================

def _callback(
    ch,
    method,
    properties,
    body,
):

    transaction_id = "UNKNOWN"

    try:

        if isinstance(
            body,
            bytes,
        ):

            body = body.decode(
                "utf-8"
            )

        transaction = json.loads(
            body
        )

        if not isinstance(
            transaction,
            dict,
        ):

            raise ValueError(
                "RabbitMQ message payload must be a JSON object."
            )

        transaction_id = str(
            transaction.get(
                "transaction_id",
                "UNKNOWN",
            )
        )

        handle_message(
            transaction
        )

        # --------------------------------------------------------
        # SUCCESS → ACK
        # --------------------------------------------------------

        ch.basic_ack(
            delivery_tag=method.delivery_tag
        )

        logger.info(
            "[WORKER] ACK sent: %s",
            transaction_id,
        )

    except Exception:

        logger.exception(
            "[WORKER] Failed processing transaction: %s",
            transaction_id,
        )

        # --------------------------------------------------------
        # FAILURE → DLQ
        # --------------------------------------------------------

        try:

            ch.basic_nack(
                delivery_tag=method.delivery_tag,
                requeue=False,
            )

            logger.error(
                "[WORKER] Message rejected and routed to DLQ: %s",
                transaction_id,
            )

        except Exception:

            logger.exception(
                "[WORKER] Failed to NACK message: %s",
                transaction_id,
            )


# ================================================================
# CONSUMER STARTUP
# ================================================================

def start_consuming(
    channel,
) -> None:

    channel.basic_qos(
        prefetch_count=1
    )

    channel.basic_consume(
        queue="transaction_queue",
        on_message_callback=_callback,
        auto_ack=False,
    )

    logger.info(
        "Worker consuming from "
        "'transaction_queue' "
        "(prefetch_count=1). Waiting for messages..."
    )

    channel.start_consuming()


# ================================================================
# DIRECT WORKER STARTUP
# ================================================================

if __name__ == "__main__":

    from app.messaging.rabbitmq import (
        create_connection,
        create_channel,
    )

    logger.info(
        "Starting NexusGuard transaction worker..."
    )

    connection = None

    try:

        # --------------------------------------------------------
        # Create RabbitMQ connection
        # --------------------------------------------------------

        connection = create_connection()

        # --------------------------------------------------------
        # Create RabbitMQ channel
        # --------------------------------------------------------

        channel = create_channel(
            connection
        )

        # --------------------------------------------------------
        # Start consuming
        # --------------------------------------------------------

        start_consuming(
            channel
        )

    except KeyboardInterrupt:

        logger.info(
            "Worker stopped by user."
        )

    except Exception:

        logger.exception(
            "Worker failed."
        )

    finally:

        if (
            connection is not None
            and not connection.is_closed
        ):

            connection.close()

            logger.info(
                "RabbitMQ worker connection closed."
            )