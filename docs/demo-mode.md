# Batch Evaluation and Live Streaming

The dashboard has two monitor modes: **Batch** and **Streaming**. They use different data sources and must not be conflated.

## Batch: historical labeled CSVs

Batch replay publishes selected historical CSV rows through the existing FastAPI and RabbitMQ transaction worker. The dashboard compares actual persisted NexusGuard decisions with CSV ground-truth labels only after processing. REVIEW and BLOCK count as positive fraud predictions. Accuracy, precision, recall, and F1 are pipeline-level evaluation metrics.

Per-model Random Forest, XGBoost, LSTM, and ensemble metrics require both available model artifacts and actual labeled predictions. Missing model artifacts or predictions are reported as unavailable; they are not replaced by fabricated probabilities.

## Streaming: Mempool.space Bitcoin mainnet

Selecting **Streaming** opens `wss://mempool.space/api/v1/ws` and subscribes with `{"track-mempool": true}`. For each actual transaction ID received, the dashboard fetches transaction details from `https://mempool.space/api/tx/{txid}` and the current BTC/USD price from `https://mempool.space/api/v1/prices`. It submits the source transaction and its inputs, outputs, fee, observed time, and source metadata to NexusGuard's `POST /transactions/publish` endpoint.

The transaction continues through the configured RabbitMQ worker and MongoDB persistence path. Only completed backend results appear in the live table. Transaction details show the source-provided Bitcoin data and the reasons returned by NexusGuard. Live transactions do not receive CSV labels or historical evaluation metrics.

The dashboard reports connection, reconnect, API, and processing errors rather than presenting an unprocessed transaction as approved. RabbitMQ and the transaction worker must be running for live transactions to be analyzed and stored.

## API and local development

- `POST /demo/dataset-replay/start` starts a historical CSV replay.
- `GET /demo/dataset-replay/status` returns processed replay results and evaluation metrics.
- `POST /demo/dataset-replay/stop` stops replay.
- `POST /demo/dataset-replay/reset` resets replay status.
- `POST /transactions/publish` publishes a transaction into the asynchronous processing pipeline.
- `GET /health` reports API dependency status.

Run FastAPI and the transaction worker using the project's configured environment, then start the dashboard from `dashboard/`. The development dashboard uses port 5173 by default; if that port is occupied, Vite selects the next available port.
