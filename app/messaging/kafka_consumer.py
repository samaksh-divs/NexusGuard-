"""Kafka-to-RabbitMQ bridge for NexusGuard transaction events.

This process deliberately contains no fraud logic. RabbitMQ remains the
single processing queue and the existing transaction worker remains the
single fraud-processing point.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.config.settings import settings
from app.messaging.publisher import publish_transaction
from app.messaging.kafka_producer import _kafka_config, _producer_class

logger = logging.getLogger(__name__)


class KafkaTransaction(BaseModel):
    transaction_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    symbol: str = Field(min_length=1)
    timestamp: datetime


def validate_transaction_event(payload: Any) -> dict[str, Any]:
    """Validate and return a JSON-ready normalized transaction."""
    if not isinstance(payload, dict):
        raise ValueError("Kafka transaction event must be a JSON object")
    return KafkaTransaction.model_validate(payload).model_dump(mode="json")


def _publish_invalid(producer, payload: Any, error: Exception) -> None:
    try:
        producer.produce(
            settings.kafka_invalid_topic,
            value=json.dumps(
                {"payload": payload, "error": str(error)},
                default=str,
            ),
        )
        producer.flush(settings.kafka_connection_timeout_seconds)
    except Exception:
        logger.exception("Failed to route invalid Kafka event to %s", settings.kafka_invalid_topic)


def forward_transaction_to_rabbitmq(transaction: dict[str, Any]) -> None:
    """Forward one validated event through the existing RabbitMQ publisher."""
    publish_transaction(transaction)


def start_kafka_consumer() -> None:
    """Consume Kafka events and forward valid events to RabbitMQ."""
    consumer_class = _consumer_class()
    producer_class = _producer_class()
    consumer = consumer_class(
        {
            **_kafka_config(settings.kafka_group_id),
            "group.id": settings.kafka_group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    invalid_producer = producer_class(_kafka_config(f"{settings.kafka_client_id}-invalid"))
    consumer.subscribe([settings.kafka_transaction_topic])
    logger.info("Kafka consumer listening on %s", settings.kafka_transaction_topic)

    try:
        while True:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                logger.error("Kafka consumer error: %s", message.error())
                continue

            try:
                raw_payload = json.loads(
                    message.value().decode("utf-8", errors="replace")
                )
                transaction = validate_transaction_event(raw_payload)
            except (TypeError, ValueError, ValidationError) as exc:
                logger.error("Invalid Kafka transaction at offset %s: %s", message.offset(), exc)
                _publish_invalid(
                    invalid_producer,
                    locals().get("raw_payload", message.value().decode("utf-8", errors="replace")),
                    exc,
                )
                consumer.commit(message=message, asynchronous=False)
                continue

            while True:
                try:
                    forward_transaction_to_rabbitmq(transaction)
                    consumer.commit(message=message, asynchronous=False)
                    logger.info("Forwarded Kafka event to RabbitMQ: %s", transaction["transaction_id"])
                    break
                except Exception:
                    logger.exception(
                        "RabbitMQ publish failed; retrying without committing Kafka offset: %s",
                        transaction["transaction_id"],
                    )
                    time.sleep(1)
    finally:
        consumer.close()
        invalid_producer.flush(settings.kafka_connection_timeout_seconds)


def _consumer_class():
    try:
        from confluent_kafka import Consumer
    except ImportError as exc:
        raise RuntimeError(
            "confluent-kafka is required for Kafka integration. "
            "Install dependencies with: pip install -r requirements.txt"
        ) from exc
    return Consumer


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    start_kafka_consumer()
