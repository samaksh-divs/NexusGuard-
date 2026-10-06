"""Real Historical Dataset Replay Engine for NexusGuard.

Replays real historical cryptocurrency transaction records one-by-one
through the EXISTING NexusGuard transaction-processing pipeline.
"""

import csv
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.repositories import get_transaction
from app.messaging.publisher import publish_transaction

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

        data_dir = Path("data")
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
        now = datetime.now(timezone.utc)
        
        for index, row in enumerate(records):
            source_id = str(row.get(config["id_field"]) or f"SRC-{index:04d}")
            amount = float(row.get("amount", 100.0))
            fee = float(row.get("fee", 0.001))
            price = 50000.0 if config["symbol"] == "BTC" else 3000.0
            quantity = round(amount / price, 6) if amount > price else round(amount, 6)

            orig_label = str(row.get(config["label_field"]) or "unknown")
            gt_label = int(row.get(config["ground_truth_field"], 0))

            nexus_tx_id = f"REPLAY-{now:%Y%m%d%H%M%S}-{index+1:04d}-{uuid.uuid4().hex[:4]}"

            item = {
                "transaction_id": nexus_tx_id,
                "source_transaction_id": source_id,
                "source_dataset": config["name"],
                "timestamp": row.get("timestamp") or (now).isoformat(),
                "account_id": row.get("sender") or row.get("account_id") or f"ACC-{source_id[:8]}",
                "sender": row.get("sender") or f"0x{source_id[:10]}",
                "receiver": row.get("receiver") or f"0x{source_id[-10:]}",
                "symbol": config["symbol"],
                "price": price,
                "quantity": quantity,
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


class DatasetReplayEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._transactions: list[dict[str, Any]] = []
        self._dataset_config: dict[str, Any] = {}
        self._replay_speed: float = 1.0  # tx / sec
        self._selected_count: int = 100

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

            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            was_running = self.running
            self._stop_event.set()
            return was_running

    def reset(self) -> bool:
        with self._lock:
            self._stop_event.set()
            self._transactions = []
            self._dataset_config = {}
            return True

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def transactions(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._transactions)

    def status(self) -> dict[str, Any]:
        with self._lock:
            txs = list(self._transactions)
            config = dict(self._dataset_config)
            speed = self._replay_speed
            running = self.running

        processed_list = []
        latencies = []

        for tx in txs:
            try:
                res = get_transaction(tx["transaction_id"])
            except Exception:
                res = None

            if res:
                tx.update({
                    "risk_score": res.get("risk_score"),
                    "risk_level": res.get("risk_level"),
                    "decision": res.get("decision"),
                    "latency_ms": res.get("latency_ms"),
                    "feature_latency_ms": res.get("feature_latency_ms"),
                    "ml_latency_ms": res.get("ml_latency_ms"),
                    "reasons": res.get("risk_reasons") or res.get("fraud_reasons"),
                })
                processed_list.append(tx)
                if res.get("latency_ms"):
                    latencies.append(float(res["latency_ms"]))

        approved = sum(1 for t in processed_list if t.get("decision") == "APPROVE")
        review = sum(1 for t in processed_list if t.get("decision") == "REVIEW")
        blocked = sum(1 for t in processed_list if t.get("decision") == "BLOCK")

        # Ground truth evaluation metrics (purely post-processing comparison)
        gt_illicit = sum(1 for t in processed_list if t.get("ground_truth_label") == 1)
        gt_licit = sum(1 for t in processed_list if t.get("ground_truth_label") == 0)

        # True Positives: GT=1 and NexusGuard=BLOCK or REVIEW
        tp = sum(1 for t in processed_list if t.get("ground_truth_label") == 1 and t.get("decision") in ("BLOCK", "REVIEW"))
        # False Positives: GT=0 and NexusGuard=BLOCK or REVIEW
        fp = sum(1 for t in processed_list if t.get("ground_truth_label") == 0 and t.get("decision") in ("BLOCK", "REVIEW"))
        # True Negatives: GT=0 and NexusGuard=APPROVE
        tn = sum(1 for t in processed_list if t.get("ground_truth_label") == 0 and t.get("decision") == "APPROVE")
        # False Negatives: GT=1 and NexusGuard=APPROVE
        fn = sum(1 for t in processed_list if t.get("ground_truth_label") == 1 and t.get("decision") == "APPROVE")

        precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
        recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
        f1_score = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
        accuracy = round((tp + tn) / len(processed_list), 4) if processed_list else 0.0
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

        return {
            "running": running,
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
            "performance_metrics": {
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1_score": f1_score,
                "true_positives": tp,
                "false_positives": fp,
                "true_negatives": tn,
                "false_negatives": fn,
            }
        }

    def _run(self) -> None:
        delay = 1.0 / self._replay_speed
        for tx in self.transactions:
            if self._stop_event.is_set():
                break

            try:
                publish_transaction(tx)
            except Exception:
                logger.exception("Dataset replay transaction publish failed for %s", tx.get("transaction_id"))
                break

            self._stop_event.wait(delay)


dataset_replay_engine = DatasetReplayEngine()
