# Demo Mode

Demo Mode is a presentation-friendly replay of prepared, synthetic crypto transaction patterns. It is explicitly labeled as `DEMO / SIMULATED CRYPTO TRANSACTIONS`; it does not connect to an exchange, wallet, or real financial data source.

## Dataset and transformation

The local artifact is `data/crypto_demo_transactions.csv`. The repository also contains the public Elliptic dataset under `data/elliptic/`, but those feature/class tables do not match NexusGuard's price and quantity contract, so Demo Mode uses the small local pattern set instead of pretending to be live exchange data. `app/demo/crypto_dataset.py` expands those reviewed patterns deterministically to 120 records with timestamp, account, symbol, price, quantity, amount, frequency, wallet age, history count, and label fields.

The generator maps only the transaction fields required by the existing Kafka consumer: transaction ID, timestamp, symbol, amount, price, quantity, status, and account ID. A unique ID is created for every replay.

## Profiles

User A (`DEMO-USER-A`) is a normal crypto trader. Its records use BTCUSDT, ETHUSDT, BNBUSDT, and SOLUSDT with normal quantities and values.

User B (`DEMO-USER-B`) is a suspicious crypto trader. Its records include unusually high quantities, very large values, rapid-frequency metadata, and a `SCAM` symbol that the existing fraud rules recognize. There is no account-specific BLOCK branch. The final result is calculated by the existing fraud worker and its critical override.

## Processing path

```text
Demo generator -> Kafka -> Kafka consumer -> RabbitMQ -> transaction worker
  -> fraud rules + behavioral analysis -> RF/XGBoost/LSTM -> ML ensemble
  -> final decision -> MongoDB -> alerts -> dashboard
```

The generator never writes MongoDB directly, calls the worker directly, or bypasses Kafka. The consumer remains a thin validation and RabbitMQ forwarding layer.

## API

- `POST /demo/start` starts one cancellable 12-transaction replay.
- `POST /demo/stop` requests a stop between transactions.
- `GET /demo/status` returns running state and counters derived from persisted transaction results.
- `GET /demo/users` returns the two demo profiles.
- `GET /demo/transactions` returns generated payloads, which the UI joins with the latest backend results.

## Dashboard

The React dashboard's **Live Demo** page polls the demo endpoints and recent alerts every 1.5 to 3 seconds. Start and stop controls invoke the API. The stream displays actual risk level, decision, score-related fields, and alert presence returned by the backend; counters are not hard-coded.

## Run it

Start Kafka, the existing RabbitMQ worker, the Kafka consumer, and FastAPI first:

```powershell
Set-Location C:\Users\achar\Downloads\nexusguard-phase6
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python -m app.messaging.kafka_consumer
python -m app.workers.transaction_worker
```

Then open the frontend and visit `/demo`:

```powershell
Set-Location C:\Users\achar\Downloads\nexusguard_phase8_frontend\nexusguard_phase8_frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Or control it from PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/demo/start -Method POST
Invoke-RestMethod http://127.0.0.1:8000/demo/status
Invoke-RestMethod http://127.0.0.1:8000/demo/transactions
Invoke-RestMethod http://127.0.0.1:8000/demo/stop -Method POST
```

The expected presentation outcome is normal User A records becoming `LOW/APPROVE`, while User B records containing the high-value, high-quantity, and `SCAM` signals become `HIGH/BLOCK` and create alerts through the existing worker.
