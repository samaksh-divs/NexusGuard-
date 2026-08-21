"""
NexusGuard Transaction Publisher

Publishes transactions from FastAPI to RabbitMQ.

The publisher uses the shared RabbitMQ connection layer so that
RabbitMQ connection settings remain centralized.
"""

import json
import logging

import pika

from app.config.settings import settings
from app.messaging.rabbitmq import create_channel, create_connection
from app.messaging.topology import declare_topology

logger = logging.getLogger(__name__)

_connection = None
_channel = None


def check_publisher_health() -> bool:
    """Return whether the shared RabbitMQ publisher is currently open."""
    return bool(
        _connection is not None
        and _connection.is_open
        and _channel is not None
        and _channel.is_open
    )


# ================================================================
# CONNECT
# ================================================================

def connect_publisher() -> None:
    """
    Create the RabbitMQ publisher connection and channel.
    """

    global _connection, _channel

    try:
        _connection = create_connection()
        _channel = create_channel(_connection)

        # Ensure exchange/queue/DLQ topology exists.
        declare_topology(_channel)

        logger.info(
            "RabbitMQ publisher ready (exchange=%s)",
            settings.rabbitmq_exchange,
        )

    except Exception:
        _connection = None
        _channel = None

        logger.exception(
            "Failed to initialize RabbitMQ publisher"
        )

        raise


# ================================================================
# CLOSE
# ================================================================

def close_publisher() -> None:
    """
    Close the RabbitMQ publisher connection.
    """

    global _connection, _channel

    try:
        if _channel is not None and _channel.is_open:
            _channel.close()

        if _connection is not None and _connection.is_open:
            _connection.close()

        logger.info(
            "RabbitMQ publisher connection closed"
        )

    except Exception:
        logger.exception(
            "Error closing RabbitMQ publisher"
        )

    finally:
        _channel = None
        _connection = None


# ================================================================
# PUBLISH
# ================================================================

def publish_transaction(transaction: dict) -> None:
    """
    Publish a transaction to RabbitMQ.

    The transaction is published to the configured exchange using
    the configured routing key.

    Raises:
        RuntimeError: if the publisher is not connected or the
        RabbitMQ publish operation fails.
    """

    global _connection, _channel

    transaction_id = str(
        transaction.get(
            "transaction_id",
            "UNKNOWN",
        )
    )

    try:

        # --------------------------------------------------------
        # Make sure publisher exists
        # --------------------------------------------------------

        if (
            _connection is None
            or not _connection.is_open
            or _channel is None
            or not _channel.is_open
        ):
            logger.warning(
                "RabbitMQ publisher connection unavailable. "
                "Reconnecting..."
            )

            connect_publisher()

        # --------------------------------------------------------
        # Publish message
        # --------------------------------------------------------

        message = json.dumps(
            transaction,
            default=str,
        )

        properties = pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
        )

        _channel.basic_publish(
            exchange=settings.rabbitmq_exchange,
            routing_key=settings.rabbitmq_routing_key,
            body=message,
            properties=properties,
        )

        logger.info(
            "Transaction published successfully: %s",
            transaction_id,
        )

    except Exception as exc:

        logger.exception(
            "RabbitMQ publish failed for transaction %s",
            transaction_id,
        )

        raise RuntimeError(
            "RabbitMQ publish failed"
        ) from exc