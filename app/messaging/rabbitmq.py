"""
NexusGuard RabbitMQ Connection Layer
"""

import logging

import pika
from pika.exceptions import AMQPConnectionError

from app.config.settings import settings

logger = logging.getLogger(__name__)


def create_connection() -> pika.BlockingConnection:
    """
    Create a RabbitMQ connection using application settings.
    """

    credentials = pika.PlainCredentials(
        settings.rabbitmq_user,
        settings.rabbitmq_password,
    )

    parameters = pika.ConnectionParameters(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        credentials=credentials,
        connection_attempts=3,
        retry_delay=2,
    )

    try:

        connection = pika.BlockingConnection(
            parameters
        )

        logger.info(
            "Connected to RabbitMQ at %s:%s",
            settings.rabbitmq_host,
            settings.rabbitmq_port,
        )

        return connection

    except AMQPConnectionError:

        logger.exception(
            "Failed to connect to RabbitMQ at %s:%s",
            settings.rabbitmq_host,
            settings.rabbitmq_port,
        )

        raise


def create_channel(connection: pika.BlockingConnection):
    """
    Create a channel from an existing RabbitMQ connection.
    """

    channel = connection.channel()

    return channel