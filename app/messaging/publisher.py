"""
Transaction publisher.

Used by FastAPI (POST /transactions/publish) to hand a transaction
off to RabbitMQ. The publisher's ONLY responsibility is getting the
message onto transaction_queue — it must NOT touch MongoDB. Storage
is the worker's job (app/workers/transaction_worker.py), which keeps
the producer decoupled from the processor as required by the
architecture.

Connection lifecycle:
FastAPI is a single long-running process serving many requests, so —
same reasoning as the MongoDB client — we open ONE RabbitMQ
connection/channel at startup and reuse it for every publish, rather
than reconnecting per request. This is a module-level singleton,
initialized by connect_publisher() (called from main.py's lifespan)
and torn down by close_publisher().
"""

import json
import logging

import pika
from pika.exceptions import AMQPError

from app.config.settings import settings
from app.messaging.rabbitmq import create_channel, create_connection
from app.messaging.topology import declare_topology

logger = logging.getLogger(__name__)

_connection: pika.BlockingConnection | None = None
_channel: "pika.adapters.blocking_connection.BlockingChannel | None" = None


def connect_publisher() -> None:
    """Open the shared publisher connection/channel and declare topology."""
    global _connection, _channel
    _connection = create_connection()
    _channel = create_channel(_connection)
    declare_topology(_channel)
    logger.info("Publisher ready (exchange=%s)", settings.rabbitmq_exchange)


def close_publisher() -> None:
    """Close the shared publisher connection on application shutdown."""
    global _connection
    if _connection is not None and _connection.is_open:
        _connection.close()
        logger.info("Publisher connection closed")


def publish_transaction(transaction: dict) -> None:
    """
    Publish a transaction dict to transaction_exchange with routing
    key transaction.new.

    Raises RuntimeError if the publisher hasn't been initialized, and
    re-raises AMQPError on publish failure so the caller (the FastAPI
    route) can return a proper error response instead of pretending
    the publish succeeded.
    """
    if _channel is None:
        raise RuntimeError("RabbitMQ publisher has not been initialized. Was connect_publisher() called on startup?")

    body = json.dumps(transaction, default=str).encode("utf-8")

    try:
        _channel.basic_publish(
            exchange=settings.rabbitmq_exchange,
            routing_key=settings.rabbitmq_routing_key,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,  # persistent: survives a RabbitMQ restart, combined with the durable queue
            ),
        )
        logger.info("Transaction published: %s", transaction.get("transaction_id"))
    except AMQPError:
        logger.exception("Failed to publish transaction: %s", transaction.get("transaction_id"))
        raise
