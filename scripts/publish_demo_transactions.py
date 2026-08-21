"""Publish the two Kafka demonstration accounts."""

import argparse
from datetime import datetime, timezone
import json
from urllib.request import Request, urlopen

from app.messaging.kafka_producer import KafkaTransactionProducer


def demo_transactions() -> dict[str, dict]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "normal": {
            "transaction_id": "KAFKA-NORMAL-001",
            "account_id": "ACC-NORMAL-001",
            "amount": 500,
            "price": 100,
            "quantity": 5,
            "symbol": "BTC",
            "timestamp": timestamp,
        },
        "fraud": {
            "transaction_id": "KAFKA-FRAUD-001",
            "account_id": "ACC-FRAUD-002",
            "amount": 250000,
            "price": 250000,
            "quantity": 8,
            "symbol": "SCAM",
            "timestamp": timestamp,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=("normal", "fraud", "both"),
        default="both",
    )
    parser.add_argument(
        "--transport",
        choices=("kafka", "rabbitmq"),
        default="kafka",
        help="Use direct Kafka or the existing FastAPI/RabbitMQ path.",
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    transactions = demo_transactions()
    selected = ("normal", "fraud") if args.scenario == "both" else (args.scenario,)
    if args.transport == "kafka":
        producer = KafkaTransactionProducer(client_id="nexusguard-demo")
        for name in selected:
            producer.publish(transactions[name])
            print(f"Published {name} via Kafka: {transactions[name]['transaction_id']}")
        producer.close()
        return

    for name in selected:
        payload = json.dumps(transactions[name]).encode("utf-8")
        request = Request(
            f"{args.api_url.rstrip('/')}/transactions/publish",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            print(f"Published {name} via RabbitMQ: {response.read().decode('utf-8')}")


if __name__ == "__main__":
    main()
