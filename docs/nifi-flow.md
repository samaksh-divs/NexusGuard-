# Apache NiFi flow

This flow is designed for a current NiFi 2.x installation. Processor names are stable across recent NiFi releases; verify the Kafka processor suffix in the installed UI before importing a template.

## Processor flow

```text
GenerateFlowFile or HTTP ListenHTTP
  -> EvaluateJsonPath / ValidateRecord
  -> JoltTransformJSON (normalize)
  -> UpdateAttribute (ingestion metadata)
  -> PublishKafkaRecord_2_6 (or the installed compatible PublishKafkaRecord)
  -> Kafka topic nexusguard.transactions
```

1. `GenerateFlowFile` is useful for a local demonstration. Production input can use `ListenHTTP` or an existing source processor.
2. `EvaluateJsonPath` extracts required fields for routing attributes. `ValidateRecord` uses an Avro/JSON schema requiring `transaction_id`, `account_id`, `amount`, `price`, `quantity`, `symbol`, and `timestamp`.
3. `JoltTransformJSON` maps aliases to the canonical names and preserves numeric types.
4. `UpdateAttribute` adds `nifi.ingested_at`, `nifi.source`, and an event version such as `nexusguard.event.version=1`.
5. `PublishKafkaRecord_2_6` uses a JSON record writer and the broker list from `KAFKA_BOOTSTRAP_SERVERS`. Set the topic property to `nexusguard.transactions`.

## Expected event

```json
{
  "transaction_id": "KAFKA-FRAUD-001",
  "account_id": "ACC-FRAUD-002",
  "amount": 250000,
  "price": 250000,
  "quantity": 8,
  "symbol": "SCAM",
  "timestamp": "2026-08-21T10:30:00+00:00",
  "nifi.ingested_at": "2026-08-21T10:30:01+00:00",
  "nifi.source": "demo"
}
```

## Error handling

- Route `ValidateRecord` failures to `nexusguard.transactions.invalid` with `PutKafka` or a second `PublishKafkaRecord` processor. Keep the original FlowFile and validation message as attributes.
- The application consumer commits a valid Kafka offset only after RabbitMQ accepts the message. A RabbitMQ failure is logged and the offset is left uncommitted for retry.
- The existing RabbitMQ worker ACK/NACK behavior and `transaction_dlq` remain unchanged.
- MongoDB's unique `transaction_id` index prevents duplicate persistence when upstream systems retry an event. Alerts also have a unique transaction index.

## Configuration checklist

Configure a controller service for the installed JSON reader/writer, set the Kafka broker to `localhost:9092` for local development, and use back pressure on the connection to Kafka. Do not put credentials in processor properties; use NiFi parameter contexts or secured controller services.
