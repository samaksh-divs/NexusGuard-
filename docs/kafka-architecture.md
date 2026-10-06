# Kafka architecture

NexusGuard keeps the responsibilities of its messaging systems separate:

```text
NiFi -> nexusguard.transactions (Kafka) -> Kafka consumer -> RabbitMQ -> transaction worker -> MongoDB/alerts
```

- NiFi handles data flow: receipt, validation, normalization, metadata, and routing.
- Kafka handles durable event streaming and replayable ingestion.
- The Kafka consumer validates again at the application boundary and forwards to RabbitMQ.
- RabbitMQ handles asynchronous work distribution and keeps the existing DLQ behavior.
- The transaction worker remains the only fraud-intelligence component. It runs rules, behavioral analysis, and the RF/XGBoost/LSTM ensemble.
- MongoDB persists decisions, while the React dashboard provides human monitoring.

The API uses the Kafka path only when `KAFKA_ENABLED=true`. With the default `false`, existing `/transactions/publish` calls continue to publish directly to RabbitMQ.
