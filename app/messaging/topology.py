"""
NexusGuard RabbitMQ Topology

Defines:

transaction_exchange
        |
        | transaction.new
        v
transaction_queue
        |
        | failed messages
        v
transaction_dlx
        |
        | transaction.failed
        v
transaction_dlq
"""

import logging

import pika

logger = logging.getLogger(__name__)


# ================================================================
# NAMES
# ================================================================

TRANSACTION_EXCHANGE = "transaction_exchange"
TRANSACTION_QUEUE = "transaction_queue"
TRANSACTION_ROUTING_KEY = "transaction.new"

DEAD_LETTER_EXCHANGE = "transaction_dlx"
DEAD_LETTER_QUEUE = "transaction_dlq"
DEAD_LETTER_ROUTING_KEY = "transaction.failed"


# ================================================================
# TOPOLOGY
# ================================================================

def declare_topology(channel) -> None:
    """
    Declare the complete RabbitMQ topology.

    Safe to call repeatedly because all objects are durable and
    declarations are idempotent when their properties match.
    """

    # ------------------------------------------------------------
    # MAIN EXCHANGE
    # ------------------------------------------------------------

    channel.exchange_declare(
        exchange=TRANSACTION_EXCHANGE,
        exchange_type="direct",
        durable=True,
    )

    logger.info(
        "Exchange declared: %s",
        TRANSACTION_EXCHANGE,
    )

    # ------------------------------------------------------------
    # DEAD LETTER EXCHANGE
    # ------------------------------------------------------------

    channel.exchange_declare(
        exchange=DEAD_LETTER_EXCHANGE,
        exchange_type="direct",
        durable=True,
    )

    logger.info(
        "Dead letter exchange declared: %s",
        DEAD_LETTER_EXCHANGE,
    )

    # ------------------------------------------------------------
    # DEAD LETTER QUEUE
    # ------------------------------------------------------------

    channel.queue_declare(
        queue=DEAD_LETTER_QUEUE,
        durable=True,
    )

    logger.info(
        "Dead letter queue declared: %s",
        DEAD_LETTER_QUEUE,
    )

    # ------------------------------------------------------------
    # DEAD LETTER BINDING
    # ------------------------------------------------------------

    channel.queue_bind(
        exchange=DEAD_LETTER_EXCHANGE,
        queue=DEAD_LETTER_QUEUE,
        routing_key=DEAD_LETTER_ROUTING_KEY,
    )

    logger.info(
        "Dead letter queue bound: %s -> %s (routing_key=%s)",
        DEAD_LETTER_EXCHANGE,
        DEAD_LETTER_QUEUE,
        DEAD_LETTER_ROUTING_KEY,
    )

    # ------------------------------------------------------------
    # MAIN QUEUE
    # ------------------------------------------------------------

    channel.queue_declare(
        queue=TRANSACTION_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
            "x-dead-letter-routing-key": DEAD_LETTER_ROUTING_KEY,
        },
    )

    logger.info(
        "Queue declared: %s (durable, dead-letters to %s)",
        TRANSACTION_QUEUE,
        DEAD_LETTER_EXCHANGE,
    )

    # ------------------------------------------------------------
    # MAIN QUEUE BINDING
    # ------------------------------------------------------------

    channel.queue_bind(
        exchange=TRANSACTION_EXCHANGE,
        queue=TRANSACTION_QUEUE,
        routing_key=TRANSACTION_ROUTING_KEY,
    )

    logger.info(
        "Queue bound: %s -> %s (routing_key=%s)",
        TRANSACTION_EXCHANGE,
        TRANSACTION_QUEUE,
        TRANSACTION_ROUTING_KEY,
    )