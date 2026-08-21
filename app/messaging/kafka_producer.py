"""Kafka producer for normalized NexusGuard transaction events."""

import json
import logging
from typing import Any

from app.config.settings import settings

logger = logging.getLogger(__name__)


def _kafka_config(client_id: str) -> dict[str, Any]:
    config: dict[str, Any] = {
        "bootstrap.servers": settings.kafka_bootstrap_servers,
        "client.id": client_id,
        "security.protocol": settings.kafka_security_protocol,
        "socket.timeout.ms": int(settings.kafka_connection_timeout_seconds * 1000),
    }

    optional_settings = {
        "sasl.mechanisms": settings.kafka_sasl_mechanism,
        "sasl.username": settings.kafka_sasl_username,
        "sasl.password": settings.kafka_sasl_password,
    }
    config.update({key: value for key, value in optional_settings.items() if value})
    return config


def _producer_class():
    try:
        from confluent_kafka import Producer
    except ImportError as exc:
        raise RuntimeError(
            "confluent-kafka is required for Kafka integration. "
            "Install dependencies with: pip install -r requirements.txt"
        ) from exc
    return Producer


class KafkaTransactionProducer:
    """Small synchronous wrapper with delivery confirmation."""

    def __init__(self, client_id: str | None = None) -> None:
        producer_class = _producer_class()
        self._producer = producer_class(
            _kafka_config(client_id or settings.kafka_client_id)
        )

    def publish(
        self,
        transaction: dict[str, Any],
        topic: str | None = None,
    ) -> None:
        transaction_id = str(transaction.get("transaction_id", "UNKNOWN"))
        delivery_error = None

        def delivery_callback(error, message) -> None:
            nonlocal delivery_error
            delivery_error = error

        self._producer.produce(
            topic or settings.kafka_transaction_topic,
            key=transaction_id,
            value=json.dumps(transaction, default=str),
            callback=delivery_callback,
        )
        self._producer.flush(settings.kafka_connection_timeout_seconds)

        if delivery_error is not None:
            raise RuntimeError(
                f"Kafka delivery failed for {transaction_id}: {delivery_error}"
            )

        logger.info("Kafka event published: topic=%s transaction_id=%s", topic or settings.kafka_transaction_topic, transaction_id)

    def check_health(self) -> bool:
        try:
            self._producer.list_topics(
                timeout=settings.kafka_connection_timeout_seconds
            )
            return True
        except Exception:
            logger.warning("Kafka health check failed", exc_info=True)
            return False

    def close(self) -> None:
        self._producer.flush(settings.kafka_connection_timeout_seconds)


_producer: KafkaTransactionProducer | None = None


def connect_kafka_producer() -> None:
    global _producer
    _producer = KafkaTransactionProducer()


def close_kafka_producer() -> None:
    global _producer
    if _producer is not None:
        try:
            _producer.close()
        finally:
            _producer = None


def publish_kafka_transaction(transaction: dict[str, Any]) -> None:
    global _producer
    if _producer is None:
        connect_kafka_producer()
    assert _producer is not None
    _producer.publish(transaction)


def check_kafka_health() -> bool:
    if not settings.kafka_enabled:
        return False

    try:
        global _producer
        if _producer is None:
            connect_kafka_producer()
        assert _producer is not None
        return _producer.check_health()
    except Exception:
        logger.warning("Kafka is configured but unavailable", exc_info=True)
        return False
