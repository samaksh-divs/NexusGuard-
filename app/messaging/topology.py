"""
RabbitMQ topology — exchange, queue, and binding declarations.

Why this is separate from rabbitmq.py:
`rabbitmq.py` only knows how to open a connection/channel. This module
knows the actual shape of NexusGuard's messaging setup (which
exchange, which queue, how they're bound). Keeping them apart means
the connection logic doesn't need to change as the topology grows.

Phase 4 adds the Dead Letter Exchange (transaction_dlx) and Dead
Letter Queue (transaction_dlq), and — importantly — attaches
dead-letter arguments to the EXISTING transaction_queue so that
rejected/nacked messages are automatically routed there by RabbitMQ
itself, rather than the worker having to manually re-publish them.

IMPORTANT — one-time manual step required:
transaction_queue was originally declared in Phase 3 WITHOUT any
dead-letter arguments. RabbitMQ does not allow redeclaring an existing
queue with different arguments (queue_declare is only idempotent when
the arguments match exactly) — it raises PRECONDITION_FAILED and
closes the channel. Since transaction_queue already exists from Phase
3, it must be deleted once (via the management UI or rabbitmqctl)
before running this Phase 4 code, so it can be redeclared with the
new arguments. This does not affect MongoDB data — it only affects
the RabbitMQ queue object itself. See the chat instructions for the
exact one-time command.
"""

import logging

from pika.adapters.blocking_connection import BlockingChannel

from app.config.settings import settings

logger = logging.getLogger(__name__)


def declare_topology(channel: BlockingChannel) -> None:
    """
    Declare exchanges, queues, and bindings for both the main
    transaction pipeline and the dead-letter pipeline. Safe to call
    every time the app/worker starts, PROVIDED transaction_queue's
    arguments haven't drifted from what's declared here (see the
    module docstring for the one-time migration this phase requires).
    """
    # --- Main pipeline (unchanged from Phase 3) ---
    channel.exchange_declare(
        exchange=settings.rabbitmq_exchange,
        exchange_type="direct",
        durable=True,
    )
    logger.info("Exchange declared: %s (direct, durable)", settings.rabbitmq_exchange)

    # --- Dead letter pipeline (new in Phase 4) ---
    # Declared BEFORE transaction_queue so the DLX already exists by
    # the time we point transaction_queue at it.
    channel.exchange_declare(
        exchange=settings.rabbitmq_dlx,
        exchange_type="direct",
        durable=True,
    )
    logger.info("Dead letter exchange declared: %s (direct, durable)", settings.rabbitmq_dlx)

    channel.queue_declare(
        queue=settings.rabbitmq_dlq,
        durable=True,
    )
    logger.info("Dead letter queue declared: %s (durable)", settings.rabbitmq_dlq)

    channel.queue_bind(
        exchange=settings.rabbitmq_dlx,
        queue=settings.rabbitmq_dlq,
        routing_key=settings.rabbitmq_dlq_routing_key,
    )
    logger.info(
        "Dead letter queue bound: %s -> %s (routing_key=%s)",
        settings.rabbitmq_dlx,
        settings.rabbitmq_dlq,
        settings.rabbitmq_dlq_routing_key,
    )

    # --- transaction_queue, now with dead-letter arguments ---
    # x-dead-letter-exchange: where RabbitMQ automatically republishes
    #   a message when it's nacked/rejected with requeue=False (or
    #   expires via TTL, though we don't use TTL here).
    # x-dead-letter-routing-key: the routing key used on that
    #   republish. Without this, RabbitMQ reuses the message's
    #   original routing key (transaction.new), which wouldn't match
    #   transaction_dlq's binding — so we set it explicitly.
    channel.queue_declare(
        queue=settings.rabbitmq_queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.rabbitmq_dlx,
            "x-dead-letter-routing-key": settings.rabbitmq_dlq_routing_key,
        },
    )
    logger.info(
        "Queue declared: %s (durable, dead-letters to %s)",
        settings.rabbitmq_queue,
        settings.rabbitmq_dlx,
    )

    channel.queue_bind(
        exchange=settings.rabbitmq_exchange,
        queue=settings.rabbitmq_queue,
        routing_key=settings.rabbitmq_routing_key,
    )
    logger.info(
        "Queue bound: %s -> %s (routing_key=%s)",
        settings.rabbitmq_exchange,
        settings.rabbitmq_queue,
        settings.rabbitmq_routing_key,
    )

