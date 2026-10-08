# NexusGuard

NexusGuard is a real-time transaction fraud detection system. The Phase 10 integration adds Apache Kafka and Apache NiFi around the existing application pipeline without replacing RabbitMQ, MongoDB, the fraud worker, the ML ensemble, alerts, or the DLQ.

## Architecture

```text
React -> FastAPI -> NiFi -> Kafka -> Kafka consumer -> RabbitMQ -> worker -> MongoDB/alerts
                         \\-> existing /transactions/publish -> RabbitMQ
```

- NiFi handles ingestion, validation, transformation, and routing.
- Kafka handles durable transaction event streaming.
- The Kafka consumer validates events and forwards them to RabbitMQ.
- RabbitMQ remains the asynchronous work queue and DLQ boundary.
- The existing worker performs fraud rules, behavioral analysis, Random Forest, XGBoost, LSTM, final risk decisions, persistence, and alert creation.
- React remains the monitoring surface.

Kafka and NiFi do not perform fraud detection.

## Prerequisites

Windows PowerShell, Python 3.11+, Node.js, MongoDB, RabbitMQ, and Docker Desktop are recommended. Docker is optional for Kafka and NiFi, but Docker Desktop must be running before Compose commands work.

```powershell
docker --version
docker compose version
python --version
```

## Installation

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a real local `NIFI_PASSWORD` in `.env` before starting Compose. Do not commit `.env`.

Run the dashboard commands from the repository's `dashboard` directory.

## Configuration

Kafka settings are in `.env.example`, including `KAFKA_ENABLED`, broker address, topics, group ID, and optional SASL settings. `NIFI_ENABLED` describes whether NiFi is configured for the application; NiFi itself is not treated as reachable by the FastAPI health endpoint because its flow is externally managed.

## Start Services

Start the existing MongoDB and RabbitMQ installations normally. Their application settings are `MONGODB_URI` and `RABBITMQ_HOST`/`RABBITMQ_PORT`.

Start Kafka and NiFi:

```powershell
docker compose up -d
docker compose ps
docker compose logs -f kafka
docker compose logs -f nifi
```

Kafka is exposed to Windows as `localhost:9092`. NiFi is exposed over HTTPS at `https://localhost:8443/nifi` using the credentials configured in `.env`.

Create topics:

```powershell
python scripts/create_kafka_topics.py
docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic nexusguard.transactions --partitions 3 --replication-factor 1
docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic nexusguard.transactions.invalid --partitions 3 --replication-factor 1
docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic nexusguard.transactions.processed --partitions 3 --replication-factor 1
```

Start the backend processes in separate PowerShell windows:

```powershell
# From the repository root; the dashboard defaults to this API port.
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python -m app.workers.transaction_worker
python -m app.messaging.kafka_consumer
```

Start the frontend:

```powershell
Set-Location .\dashboard
npm install
npm run dev -- --host 127.0.0.1
```

Stop Kafka and NiFi:

```powershell
docker compose down
```

## API Paths

`POST /transactions/publish` remains the traditional FastAPI to RabbitMQ path.

`POST /transactions/kafka/publish` sends directly to Kafka and requires `KAFKA_ENABLED=true`.

The Kafka consumer then forwards the event to RabbitMQ. Existing transaction, dashboard, risk, ML, behavior, alert, and DLQ APIs are unchanged.

## NiFi Flow

Configure the flow documented in [docs/nifi-flow.md](docs/nifi-flow.md): input, JSON validation, normalization, ingestion metadata, and `PublishKafkaRecord` to `nexusguard.transactions`. Invalid records go to `nexusguard.transactions.invalid`.

## Demo

Kafka is the default demonstration transport:

```powershell
python scripts/publish_demo_transactions.py --scenario normal
python scripts/publish_demo_transactions.py --scenario fraud
python scripts/publish_demo_transactions.py --scenario both
```

For comparison with the original application path:

```powershell
python scripts/publish_demo_transactions.py --scenario both --transport rabbitmq
```

Expected results:

- `ACC-NORMAL-001`: `LOW`, `APPROVE`.
- `ACC-FRAUD-002`: individual fraud score `100`, critical override triggered, `HIGH`, `BLOCK`, and an operational alert.

## Tests

```powershell
python -m pytest -q
python -m compileall -q app scripts
python -c "from app.main import app; print('FASTAPI OK')"
python -c "from app.messaging.consumer import start_consuming; print('RABBITMQ CONSUMER OK')"
python -c "from app.messaging.kafka_producer import KafkaTransactionProducer; print('KAFKA PRODUCER OK')"
python -c "from app.messaging.kafka_consumer import start_kafka_consumer; print('KAFKA CONSUMER OK')"
```

Unit tests do not require a live Kafka broker. Live verification requires Docker Desktop, MongoDB, RabbitMQ, and the NiFi flow to be running. Check `GET http://127.0.0.1:8000/health`; it reports actual MongoDB, RabbitMQ, and Kafka status, while NiFi reports `configured` or `not_configured`.

## Troubleshooting

- If Kafka publishing fails, check `docker compose ps`, `docker compose logs kafka`, and `localhost:9092`.
- If the consumer cannot forward, check RabbitMQ and leave the Kafka offset uncommitted so the event can be retried.
- Invalid events are routed to the invalid topic by the consumer; NiFi validation failures should use the same topic.
- MongoDB's unique `transaction_id` index and the alert uniqueness constraint preserve idempotency across retries.
- Docker Desktop is required for the Compose services. If it is unavailable, install Kafka and NiFi separately and use the same environment variables and documented flow.
