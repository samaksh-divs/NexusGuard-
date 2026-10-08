"""Real Historical Dataset Replay Engine for NexusGuard.

Replays real historical cryptocurrency transaction records one-by-one
through the EXISTING NexusGuard transaction-processing pipeline.
"""

import csv
import logging
import threading
from typing import Any

from app.database.repositories import get_transactions_by_ids
from app.messaging.publisher import publish_transaction
from app.ml.model_status import PROJECT_ROOT, get_model_availability

logger = logging.getLogger(__name__)

DATASET_CONFIGS = {
    "elliptic_bitcoin": {
        "id": "elliptic_bitcoin",
        "name": "Elliptic Bitcoin Dataset",
        "file": "elliptic_bitcoin_dataset.csv",
        "chain": "Bitcoin",
        "symbol": "BTC",
        "description": "Historical Bitcoin transactions with ground-truth illicit/licit classifications.",
        "id_field": "txId",
        "label_field": "original_label",
        "ground_truth_field": "ground_truth_label"
    },
    "ethereum_fraud": {
        "id": "ethereum_fraud",
        "name": "Ethereum Fraud Dataset",
        "file": "ethereum_fraud_dataset.csv",
        "chain": "Ethereum",
        "symbol": "ETH",
        "description": "Historical Ethereum transaction records with verified fraud/legitimate labels.",
        "id_field": "txHash",
        "label_field": "original_label",
        "ground_truth_field": "ground_truth_label"
    }
}


class DatasetAdapter:
    """Normalizes real historical dataset records into NexusGuard schema."""

    @staticmethod
    def load_dataset(dataset_id: str, count: int = 100) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        config = DATASET_CONFIGS.get(dataset_id)
        if not config:
            raise ValueError(f"Unknown dataset_id: {dataset_id}")

        data_dir = PROJECT_ROOT / "data"
        file_path = data_dir / config["file"]
        if not file_path.exists():
            raise FileNotFoundError(f"Dataset file not found at {file_path}")

        records = []
        with file_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)
                if len(records) >= count:
                    break

        normalized = []
        seen_source_ids = set()
        
        for row in records:
            source_id = str(row.get(config["id_field"]) or "").strip()
            if not source_id:
                raise ValueError(
                    f"Dataset row is missing its {config['id_field']} transaction ID"
                )
            if source_id in seen_source_ids:
                raise ValueError(
                    f"Dataset contains duplicate transaction ID: {source_id}"
                )
            seen_source_ids.add(source_id)

            raw_amount = row.get("amount")
            if raw_amount is None or not raw_amount.strip():
                raise ValueError(
                    f"Dataset transaction {source_id} is missing its amount"
                )
            amount = float(raw_amount)

            raw_fee = row.get("fee")
            fee = float(raw_fee) if raw_fee and raw_fee.strip() else None
            timestamp = row.get("timestamp")
            if not timestamp:
                raise ValueError(
                    f"Dataset transaction {source_id} is missing its timestamp"
                )

            orig_label = str(row.get(config["label_field"]) or "unknown")
            try:
                gt_label = int(float(row.get(config["ground_truth_field"], "")))
            except (TypeError, ValueError):
                gt_label = None

            item = {
                "transaction_id": source_id,
                "source_transaction_id": source_id,
                "source_dataset": config["name"],
                "timestamp": timestamp,
                "account_id": row.get("sender") or row.get("account_id") or "UNKNOWN",
                "sender": row.get("sender") or None,
                "receiver": row.get("receiver") or None,
                "symbol": config["symbol"],
                # Historical CSVs contain native asset amounts but no price quote.
                "price": None,
                "quantity": amount,
                "amount": amount,
                "transaction_value": amount,
                "fee": fee,
                "chain": config["chain"],
                "original_label": orig_label,
                "ground_truth_label": gt_label,
                "ingestion_mode": "DATASET_REPLAY",
                "status": "received"
            }
            normalized.append(item)

        return config, normalized


def load_dataset_rows(dataset_id: str) -> list[dict[str, Any]]:
    config = DATASET_CONFIGS.get(dataset_id)
    if not config:
        raise ValueError(f"Unknown dataset_id: {dataset_id}")

    file_path = PROJECT_ROOT / "data" / config["file"]
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found at {file_path}")

    with file_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def dataset_analysis(dataset_id: str) -> dict[str, Any]:
    config = DATASET_CONFIGS.get(dataset_id)
    if not config:
        raise ValueError(f"Unknown dataset_id: {dataset_id}")

    rows = load_dataset_rows(dataset_id)
    ground_truth_field = config.get("ground_truth_field", "ground_truth_label")

    legitimate_records = 0
    fraudulent_records = 0
    unknown_records = 0

    for row in rows:
        raw_label = row.get(ground_truth_field, "")
        if raw_label in (None, ""):
            unknown_records += 1
            continue

        try:
            label = int(float(raw_label))
        except (TypeError, ValueError):
            unknown_records += 1
            continue

        if label == 0:
            legitimate_records += 1
        elif label == 1:
            fraudulent_records += 1
        else:
            unknown_records += 1

    columns = list(rows[0].keys()) if rows else []
    preview_rows = rows[:20]

    model_names = ["Random Forest", "XGBoost", "LSTM", "Ensemble"]
    model_evaluation = []
    availability = get_model_availability()

    for model_name in model_names:
        model_status = availability[model_name]
        missing = ", ".join(model_status["missing_artifacts"])

        model_evaluation.append({
            "model": model_name,
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1_score": None,
            "status": (
                f"Unavailable: missing {missing}"
                if not model_status["available"]
                else "Available; replay transactions to calculate metrics"
            ),
        })

    return {
        "dataset": config,
        "dataset_name": config.get("name"),
        "csv_filename": config.get("file"),
        "total_records": len(rows),
        "legitimate_records": legitimate_records,
        "fraudulent_records": fraudulent_records,
        "unknown_records": unknown_records,
        "ground_truth_available": bool(rows and any(row.get(ground_truth_field, "") not in (None, "") for row in rows)),
        "columns": columns,
        "feature_columns": [
            column for column in columns
            if column.lower() not in {"txid", "txhash", "timestamp", "sender", "receiver", "amount", "fee", "symbol", "chain", "class", "original_label", "ground_truth_label", "is_fraud"}
        ],
        "label_distribution": [
            {"name": "Legitimate", "value": legitimate_records},
            {"name": "Fraudulent", "value": fraudulent_records},
            {"name": "Unknown", "value": unknown_records},
        ],
        "preview_rows": preview_rows,
        "evaluation": model_evaluation,
    }


class DatasetReplayEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._transactions: list[dict[str, Any]] = []
        self._dataset_config: dict[str, Any] = {}
        self._replay_speed: float = 1.0  # tx / sec
        self._selected_count: int = 100
        self._has_run = False
        self._stopped = False
        self._publication_complete = False
        self._replay_error: str | None = None

    def start(self, dataset_id: str = "elliptic_bitcoin", count: int = 100, speed: float = 1.0) -> bool:
        with self._lock:
            if self.running:
                return False
            
            config, records = DatasetAdapter.load_dataset(dataset_id, count)
            self._dataset_config = config
            self._transactions = records
            self._selected_count = len(records)
            self._replay_speed = max(0.1, min(10.0, float(speed)))
            self._stop_event.clear()
            self._has_run = True
            self._stopped = False
            self._publication_complete = False
            self._replay_error = None

            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            was_running = self.running
            self._stop_event.set()
            self._stopped = was_running
            return was_running

    def reset(self) -> bool:
        with self._lock:
            self._stop_event.set()
            self._transactions = []
            self._dataset_config = {}
            self._has_run = False
            self._stopped = False
            self._publication_complete = False
            self._replay_error = None
            return True

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def transactions(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._transactions)

    def dataset_analysis(self, dataset_id: str) -> dict[str, Any]:
        return dataset_analysis(dataset_id)

    @staticmethod
    def _classification_metrics(
        expected: list[int],
        predicted: list[int],
    ) -> dict[str, Any]:
        true_positives = sum(y == 1 and p == 1 for y, p in zip(expected, predicted))
        false_positives = sum(y == 0 and p == 1 for y, p in zip(expected, predicted))
        true_negatives = sum(y == 0 and p == 0 for y, p in zip(expected, predicted))
        false_negatives = sum(y == 1 and p == 0 for y, p in zip(expected, predicted))
        count = len(expected)

        precision = (
            true_positives / (true_positives + false_positives)
            if true_positives + false_positives
            else 0.0
        ) if count else None
        recall = (
            true_positives / (true_positives + false_negatives)
            if true_positives + false_negatives
            else 0.0
        ) if count else None
        f1_score = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else 0.0 if count else None
        )

        return {
            "accuracy": round((true_positives + true_negatives) / count, 4) if count else None,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1_score": round(f1_score, 4) if f1_score is not None else None,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "true_negatives": true_negatives,
            "false_negatives": false_negatives,
            "evaluation_samples": count,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            txs = list(self._transactions)
            config = dict(self._dataset_config)
            speed = self._replay_speed
            running = self.running
            has_run = self._has_run
            stopped = self._stopped
            publication_complete = self._publication_complete
            replay_error = self._replay_error

        processed_list = []
        latencies = []

        stored_transactions = get_transactions_by_ids(
            [tx["transaction_id"] for tx in txs]
        )
        for tx in txs:
            res = stored_transactions.get(tx["transaction_id"])

            if res and (res.get("decision") or res.get("final_decision")):
                tx.update({
                    "risk_score": res.get("risk_score"),
                    "risk_level": res.get("risk_level"),
                    "decision": res.get("decision"),
                    "latency_ms": res.get("latency_ms"),
                    "feature_latency_ms": res.get("feature_latency_ms"),
                    "ml_latency_ms": res.get("ml_latency_ms"),
                    "reasons": res.get("risk_reasons") or res.get("fraud_reasons"),
                    "ml_rf_probability": res.get("ml_rf_score"),
                    "ml_xgb_probability": res.get("ml_xgb_score"),
                    "ml_lstm_probability": res.get("ml_lstm_score"),
                    "ml_probability": res.get("ml_final_probability"),
                })
                processed_list.append(tx)
                if res.get("latency_ms"):
                    latencies.append(float(res["latency_ms"]))

        if running:
            replay_state = "RUNNING"
        elif not has_run:
            replay_state = "IDLE"
        elif replay_error:
            replay_state = "FAILED"
        elif stopped:
            replay_state = "STOPPED"
        elif publication_complete and len(processed_list) == len(txs):
            replay_state = "COMPLETED"
        else:
            replay_state = "PROCESSING"

        approved = sum(1 for t in processed_list if t.get("decision") == "APPROVE")
        review = sum(1 for t in processed_list if t.get("decision") == "REVIEW")
        blocked = sum(1 for t in processed_list if t.get("decision") == "BLOCK")

        labeled_transactions = [
            tx for tx in processed_list
            if tx.get("ground_truth_label") in (0, 1)
            and tx.get("decision") in ("APPROVE", "REVIEW", "BLOCK")
        ]
        expected = [int(tx["ground_truth_label"]) for tx in labeled_transactions]
        predicted = [
            int(tx["decision"] in ("REVIEW", "BLOCK"))
            for tx in labeled_transactions
        ]
        performance_metrics = self._classification_metrics(expected, predicted)
        model_availability = get_model_availability()
        model_comparison = []
        model_probability_fields = {
            "Random Forest": "ml_rf_probability",
            "XGBoost": "ml_xgb_probability",
            "LSTM": "ml_lstm_probability",
            "Ensemble": "ml_probability",
        }
        for model_name, probability_field in model_probability_fields.items():
            availability = model_availability[model_name]
            model_samples = [
                tx for tx in labeled_transactions
                if tx.get(probability_field) is not None
            ] if availability["available"] else []
            model_metrics = self._classification_metrics(
                [int(tx["ground_truth_label"]) for tx in model_samples],
                [int(float(tx[probability_field]) >= 0.5) for tx in model_samples],
            )
            missing = ", ".join(availability["missing_artifacts"])
            model_comparison.append({
                "model": model_name,
                **model_metrics,
                "status": (
                    "Available; evaluated at probability threshold 0.5"
                    if availability["available"] and model_samples
                    else (
                        "No processed labeled predictions yet"
                        if availability["available"]
                        else f"Unavailable: missing {missing}"
                    )
                ),
            })

        gt_illicit = sum(1 for tx in labeled_transactions if tx.get("ground_truth_label") == 1)
        gt_licit = sum(1 for tx in labeled_transactions if tx.get("ground_truth_label") == 0)
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

        return {
            "running": running,
            "replay_state": replay_state,
            "replay_error": replay_error,
            "mode": "DATASET_REPLAY",
            "dataset_name": config.get("name", "None"),
            "dataset_id": config.get("id", "none"),
            "replay_speed_tx_per_sec": speed,
            "total_selected": len(txs),
            "processed": len(processed_list),
            "approved": approved,
            "review": review,
            "blocked": blocked,
            "average_latency_ms": avg_latency,
            "ground_truth_illicit": gt_illicit,
            "ground_truth_licit": gt_licit,
            "evaluation_samples": len(labeled_transactions),
            "evaluation_policy": (
                "REVIEW and BLOCK count as predicted fraud; ground truth is used only "
                "for post-processing evaluation."
            ),
            "performance_metrics": performance_metrics,
            "model_comparison": model_comparison,
            "processed_transactions": processed_list,
        }

    def _run(self) -> None:
        delay = 1.0 / self._replay_speed
        try:
            transactions = self.transactions
            transaction_ids = [tx["transaction_id"] for tx in transactions]
            existing_transactions = get_transactions_by_ids(transaction_ids)
            for tx in transactions:
                if self._stop_event.is_set():
                    break

                if tx["transaction_id"] not in existing_transactions:
                    publish_transaction(tx)
                    self._stop_event.wait(delay)

            while not self._stop_event.is_set():
                stored_transactions = get_transactions_by_ids(transaction_ids)
                if all(
                    (
                        stored_transactions.get(transaction_id, {}).get("decision")
                        or stored_transactions.get(transaction_id, {}).get("final_decision")
                    )
                    for transaction_id in transaction_ids
                ):
                    with self._lock:
                        self._publication_complete = True
                    return
                self._stop_event.wait(1.0)
        except Exception as exc:
            with self._lock:
                self._replay_error = str(exc)
            logger.exception("Dataset replay pipeline failed")
        finally:
            if self._stop_event.is_set():
                return



dataset_replay_engine = DatasetReplayEngine()
