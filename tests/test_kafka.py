from datetime import datetime, timezone
import json

import pytest

from app.messaging import kafka_consumer
from app.messaging.kafka_consumer import validate_transaction_event
from app.messaging import kafka_producer


def _event(**overrides):
    event = {
        "transaction_id": "KAFKA-TEST-001",
        "account_id": "ACC-TEST-001",
        "amount": 500.0,
        "price": 100.0,
        "quantity": 5.0,
        "symbol": "BTC",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    event.update(overrides)
    return event


def test_kafka_event_is_normalized_for_rabbitmq():
    normalized = validate_transaction_event(_event())
    assert normalized["transaction_id"] == "KAFKA-TEST-001"
    assert normalized["amount"] == 500.0
    assert normalized["timestamp"].endswith("Z") or "+" in normalized["timestamp"]


@pytest.mark.parametrize("field", ["transaction_id", "account_id", "amount", "price", "quantity", "symbol", "timestamp"])
def test_kafka_event_requires_all_fields(field):
    event = _event()
    del event[field]
    with pytest.raises(ValueError):
        validate_transaction_event(event)


def test_kafka_event_rejects_non_positive_amount():
    with pytest.raises(ValueError):
        validate_transaction_event(_event(amount=0))


def test_kafka_producer_serializes_json_and_uses_transaction_key(monkeypatch):
    captured = {}

    class FakeProducer:
        def __init__(self, config):
            captured["config"] = config

        def produce(self, topic, key, value, callback):
            captured.update(topic=topic, key=key, value=value)
            callback(None, None)

        def flush(self, timeout):
            return 0

    monkeypatch.setattr(kafka_producer, "_producer_class", lambda: FakeProducer)
    producer = kafka_producer.KafkaTransactionProducer(client_id="test-client")
    producer.publish(_event())

    assert captured["key"] == "KAFKA-TEST-001"
    assert captured["topic"] == "nexusguard.transactions"
    assert json.loads(captured["value"])["account_id"] == "ACC-TEST-001"


def test_validated_transaction_is_forwarded_to_existing_rabbitmq_publisher(monkeypatch):
    forwarded = {}
    monkeypatch.setattr(
        kafka_consumer,
        "publish_transaction",
        lambda transaction: forwarded.update(transaction),
    )

    transaction = validate_transaction_event(_event())
    kafka_consumer.forward_transaction_to_rabbitmq(transaction)

    assert forwarded["transaction_id"] == "KAFKA-TEST-001"
