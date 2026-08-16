"""
Transaction consumer.

This module defines HOW a single message is handled once it's
delivered — validation, storage, and manual acknowledgement. The
actual process entry point that starts consuming lives in
app/workers/transaction_worker.py; keeping the callback logic here
(rather than inline in the worker script) makes it testable on its
own.

Critical rule enforced here: a message is only ACKed AFTER it has
been successfully stored in MongoDB.

Phase 4 change: on failure, instead of leaving the message
unacknowledged (Phase 3 behavior), we now call basic_nack with
requeue=False. Because transaction_queue is configured (in
topology.py) with x-dead-letter-exchange pointing at transaction_dlx,
RabbitMQ automatically republishes a nacked message to the DLX, which
routes it into transaction_dlq. This is what actually isolates bad
messages instead of leaving them stuck (or endlessly redelivered) in
the main queue.

Two distinct failure paths both dead-letter the same way:
  1. Malformed messages (bad JSON / fails Pydantic validation).
  2. A deliberate TEST-ONLY failure trigger (see
     _is_test_failure_trigger) that lets us verify the DLQ path
     without corrupting real validation/storage logic.

Phase 5 change: between validation and storage, the worker now runs
the transaction through the Fraud Detection Engine
(app/fraud/engine.py) and stores the resulting risk_score/risk_level/
decision/fraud_reasons alongside the transaction document. An
unexpected error during fraud analysis is treated the same as a
storage failure — nack to the DLQ, never a silent ack.

Phase 6 change: after the Phase 5 individual-transaction score is
computed, the worker also loads the account's recent history
(get_account_history) and runs the Behavioral Engine
(app/fraud/behavior.py), then blends both scores into one
combined_score (app.fraud.engine.combine_scores). All of this happens
inside the same try block as before, so any failure in history
lookup, behavioral analysis, or blending still nacks to the DLQ
exactly like a Phase 5 fraud-analysis or storage failure would.
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
from app.validation.schemas import TransactionCreate

logger = logging.getLogger(__name__)

# Testing convention: a transaction whose status is set to this value
# is intentionally valid JSON/schema-wise, but the worker deliberately
# refuses to process it, purely so we can prove the DLQ path works
# end-to-end without hand-crafting malformed JSON. This does not
# affect any real transaction — no real pipeline ever sets this
# status.
TEST_FAILURE_STATUS = "force_fail_test"


def _is_test_failure_trigger(transaction: TransactionCreate) -> bool:
    return transaction.status == TEST_FAILURE_STATUS


def handle_message(channel: BlockingChannel, method: Basic.Deliver, properties: BasicProperties, body: bytes) -> None:
    """
    Pika delivery callback: decode, validate, store, then ack —
    or nack (no requeue) to the DLQ on any failure.
    """
    transaction_id = None

    # --- Decode + validate ---
    try:
        raw = json.loads(body.decode("utf-8"))
        transaction = TransactionCreate(**raw)
        transaction_id = transaction.transaction_id
        logger.info("[WORKER] Received transaction: %s", transaction_id)

    except (json.JSONDecodeError, ValidationError):
        logger.exception("[WORKER] Processing failed: malformed message")
        logger.warning("[WORKER] Rejecting message: malformed message")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        logger.warning("[WORKER] Message routed to DLQ: malformed message")
        return

    # --- Deliberate test-only failure path (see TEST_FAILURE_STATUS) ---
    if _is_test_failure_trigger(transaction):
        logger.warning("[WORKER] Processing failed (intentional test trigger): %s", transaction_id)
        logger.warning("[WORKER] Rejecting message: %s", transaction_id)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        logger.warning("[WORKER] Message routed to DLQ: %s", transaction_id)
        return

    # --- Store in MongoDB (with fraud + behavioral analysis) ---
    logger.info("[WORKER] Processing transaction: %s", transaction_id)
    try:
        transaction_value = round(transaction.price * transaction.quantity, 8)

        # Read-only duplicate check for RULE 4 (explainability only —
        # the real uniqueness guarantee is still the unique index /
        # DuplicateTransactionError below, unchanged from Phase 2-4).
        is_duplicate = get_transaction(transaction_id) is not None

        # Phase 5: individual transaction risk.
        individual_result = calculate_risk_score(
            transaction_value=transaction_value,
            quantity=transaction.quantity,
            symbol=transaction.symbol,
            is_duplicate=is_duplicate,
            high_value_threshold=settings.fraud_high_value_threshold,
            very_high_value_threshold=settings.fraud_very_high_value_threshold,
            high_quantity_threshold=settings.fraud_high_quantity_threshold,
            suspicious_symbols=settings.suspicious_symbols_set,
        )
        logger.info(
            "[WORKER] Individual fraud analysis complete: %s (score=%s)",
            transaction_id,
            individual_result.risk_score,
        )

        # Phase 6: behavioral analysis against the account's history.
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
            velocity_window_seconds=settings.behavior_velocity_window_seconds,
            velocity_max_transactions=settings.behavior_velocity_max_transactions,
            frequency_window_minutes=settings.behavior_frequency_window_minutes,
            frequency_baseline_window_minutes=settings.behavior_frequency_baseline_window_minutes,
            frequency_multiplier=settings.behavior_frequency_multiplier,
            value_deviation_multiplier=settings.behavior_value_deviation_multiplier,
            value_unusual_multiplier=settings.behavior_value_unusual_multiplier,
            min_history_for_symbol_check=settings.behavior_min_history_for_symbol_check,
        )
        logger.info(
            "[WORKER] Behavioral analysis complete: %s (score=%s, history_size=%s)",
            transaction_id,
            behavioral_result.score,
            len(history),
        )

        combined_score, combined_level, combined_decision = combine_scores(
            individual_result.risk_score,
            behavioral_result.score,
            settings.fraud_individual_weight,
            settings.fraud_behavioral_weight,
        )
        logger.info(
            "[WORKER] Combined risk: %s (individual=%s, behavioral=%s, combined=%s, decision=%s)",
            transaction_id,
            individual_result.risk_score,
            behavioral_result.score,
            combined_score,
            combined_decision.value,
        )

        # risk_score/risk_level/decision/fraud_reasons keep their
        # Phase 5 names and now carry the COMBINED result, so existing
        # consumers of those fields (e.g. the original
        # GET /transactions/{id}/risk contract) keep working without
        # changes. individual_score/behavioral_score/combined_score/
        # behavioral_signals are additive, Phase 6-only fields.
        fraud_storage = {
            "risk_score": combined_score,
            "risk_level": combined_level.value,
            "decision": combined_decision.value,
            "fraud_reasons": individual_result.reasons,
            "individual_score": individual_result.risk_score,
            "behavioral_score": behavioral_result.score,
            "combined_score": combined_score,
            "behavioral_signals": [s.to_dict() for s in behavioral_result.signals],
        }

        insert_transaction(transaction, fraud_result=fraud_storage)
        logger.info("[WORKER] Transaction stored successfully: %s", transaction_id)

    except DuplicateTransactionError:
        # Already stored (e.g. redelivery after a crash between insert
        # and ack). The data is correctly in MongoDB either way, so we
        # ack rather than dead-lettering — this isn't a real failure.
        logger.warning("[WORKER] Transaction already exists, acknowledging as processed: %s", transaction_id)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    except Exception:
        logger.exception("[WORKER] Processing failed: %s", transaction_id)
        logger.warning("[WORKER] Rejecting message: %s", transaction_id)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        logger.warning("[WORKER] Message routed to DLQ: %s", transaction_id)
        return

    channel.basic_ack(delivery_tag=method.delivery_tag)
    logger.info("[WORKER] ACK sent: %s", transaction_id)


def start_consuming(channel: BlockingChannel) -> None:
    """
    Configure QoS and begin the blocking consume loop on
    transaction_queue. Runs until interrupted (Ctrl+C) or the
    connection drops.
    """
    channel.basic_qos(prefetch_count=settings.rabbitmq_prefetch_count)
    channel.basic_consume(
        queue=settings.rabbitmq_queue,
        on_message_callback=handle_message,
        auto_ack=False,  # manual ack only — see handle_message
    )
    logger.info(
        "Worker consuming from '%s' (prefetch_count=%s). Waiting for messages...",
        settings.rabbitmq_queue,
        settings.rabbitmq_prefetch_count,
    )
    channel.start_consuming()
