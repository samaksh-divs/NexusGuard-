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
"""

import json
import logging

from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from pydantic import ValidationError

from app.config.settings import settings
from app.database.repositories import DuplicateTransactionError, get_transaction, insert_transaction
from app.fraud.engine import calculate_risk_score
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

    # --- Store in MongoDB (with fraud analysis) ---
    logger.info("[WORKER] Processing transaction: %s", transaction_id)
    try:
        # Read-only duplicate check for RULE 4 (explainability only —
        # the real uniqueness guarantee is still the unique index /
        # DuplicateTransactionError below, unchanged from Phase 2-4).
        is_duplicate = get_transaction(transaction_id) is not None

        fraud_result = calculate_risk_score(
            transaction_value=round(transaction.price * transaction.quantity, 8),
            quantity=transaction.quantity,
            symbol=transaction.symbol,
            is_duplicate=is_duplicate,
            high_value_threshold=settings.fraud_high_value_threshold,
            very_high_value_threshold=settings.fraud_very_high_value_threshold,
            high_quantity_threshold=settings.fraud_high_quantity_threshold,
            suspicious_symbols=settings.suspicious_symbols_set,
        )
        logger.info(
            "[WORKER] Fraud analysis complete: %s (score=%s, level=%s, decision=%s)",
            transaction_id,
            fraud_result.risk_score,
            fraud_result.risk_level.value,
            fraud_result.decision.value,
        )

        insert_transaction(transaction, fraud_result=fraud_result.to_dict())
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
