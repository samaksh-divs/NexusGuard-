"""Create NexusGuard Kafka topics using the configured broker."""

from confluent_kafka.admin import AdminClient, NewTopic

from app.config.settings import settings
from app.messaging.kafka_producer import _kafka_config


def main() -> None:
    admin = AdminClient(_kafka_config("nexusguard-topic-admin"))
    topics = [
        settings.kafka_transaction_topic,
        settings.kafka_invalid_topic,
        settings.kafka_processed_topic,
    ]
    futures = admin.create_topics(
        [NewTopic(topic, num_partitions=3, replication_factor=1) for topic in topics]
    )
    for topic, future in futures.items():
        try:
            future.result()
            print(f"Created {topic}")
        except Exception as exc:
            if "already exists" in str(exc).lower():
                print(f"Already exists: {topic}")
            else:
                raise


if __name__ == "__main__":
    main()
