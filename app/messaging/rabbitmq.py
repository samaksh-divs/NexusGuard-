"""
RabbitMQ connection layer.

Why this file exists:
Both the FastAPI publisher (short-lived, one connection reused across
requests) and the standalone worker (long-lived, one connection for
its whole life) need to open a RabbitMQ connection the same way. This
module centralizes that so connection parameters, credentials, and
error handling live in exactly one place.

Unlike MongoDB, we do NOT keep a single module-level singleton
connection here — RabbitMQ connections are used differently by the
publisher (FastAPI process) and the consumer (separate worker
process), which run in different processes and must not share a
connection object. Instead, each caller gets its own connection via
`create_connection()` and is responsible for closing it.
"""

import logging

import pika
from pika.exceptions import AMQPConnectionError

from app.config.settings import settings

logger = logging.getLogger(__name__)


def create_connection() -> pika.BlockingConnection:
    """
    Open a new RabbitMQ connection using settings from the environment.

    Raises pika.exceptions.AMQPConnectionError if RabbitMQ is
    unreachable — callers should let this propagate (FastAPI startup)
    or handle/retry it (long-running worker), rather than silently
    swallowing it.
    """
    credentials = pika.PlainCredentials(settings.rabbitmq_user, settings.rabbitmq_password)
    parameters = pika.ConnectionParameters(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        credentials=credentials,
        # Fail fast instead of pika's long default retry/backoff when
        # RabbitMQ genuinely isn't there.
        connection_attempts=3,
        retry_delay=2,
    )

    try:
        connection = pika.BlockingConnection(parameters)
        logger.info("Connected to RabbitMQ at %s:%s", settings.rabbitmq_host, settings.rabbitmq_port)
        return connection
    except AMQPConnectionError:
        logger.exception(
            "Failed to connect to RabbitMQ at %s:%s", settings.rabbitmq_host, settings.rabbitmq_port
        )
        raise


def create_channel(connection: pika.BlockingConnection) -> "pika.adapters.blocking_connection.BlockingChannel":
    """Open a channel on an existing connection."""
    channel = connection.channel()
    return channel
