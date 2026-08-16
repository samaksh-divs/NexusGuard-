"""
NexusGuard Transaction Publisher.

Publishes transactions from FastAPI to RabbitMQ.
MongoDB is handled only by the worker.
"""

import json
import logging

import pika
from pika.exceptions import AMQPError

from app.config.settings import settings
from app.messaging.rabbitmq import create_channel, create_connection
from app.messaging.topology import declare_topology

logger = logging.getLogger(__name__)

_connection = None
_channel = None


def connect_publisher() -> None:
    """Create and initialize the RabbitMQ publisher."""
    global _connection, _channel

    try:
        _connection = create_connection()
        _channel = create_channel(_connection)
        declare_topology(_channel)

        logger.info(
            "Publisher ready (exchange=%s)",
            settings.rabbitmq_exchange,
        )

    except Exception:
        logger.exception("Failed to initialize RabbitMQ publisher")
        _connection = None
        _channel = None
        raise


def close_publisher() -> None:
    """Close the RabbitMQ publisher connection."""
    global _connection, _channel

    try:
        if _connection is not None and _connection.is_open:
            _connection.close()
            logger.info("Publisher connection closed")
    except Exception:
        logger.exception("Error closing RabbitMQ publisher")
    finally:
        _connection = None
        _channel = None


def publish_transaction(transaction: dict) -> None:
    """
    Publish transaction to RabbitMQ.

    FastAPI -> transaction_exchange -> transaction_queue -> worker
    """

    global _connection, _channel

    if _connection is None or not _connection.is_open:
        logger.warning("RabbitMQ connection unavailable. Reconnecting...")
        connect_publisher()

    if _channel is None or not _channel.is_open:
        logger.warning("RabbitMQ channel unavailable. Recreating...")
        _channel = create_channel(_connection)
        declare_topology(_channel)

    body = json.dumps(
        transaction,
        default=str,
    ).encode("utf-8")

    try:
        _channel.basic_publish(
            exchange=settings.rabbitmq_exchange,
            routing_key=settings.rabbitmq_routing_key,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )

        logger.info(
            "Transaction published successfully: %s",
            transaction.get("transaction_id"),
        )

    except (AMQPError, OSError) as exc:
        logger.exception(
            "RabbitMQ publish failed for transaction %s",
            transaction.get("transaction_id"),
        )

        # Reset broken connection/channel so the next request
        # can reconnect cleanly.
        try:
            if _connection is not None and _connection.is_open:
                _connection.close()
        except Exception:
            pass

        _connection = None
        _channel = None

        raise RuntimeError(
            "RabbitMQ publish failed"
        ) from exc