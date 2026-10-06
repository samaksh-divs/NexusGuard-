"""Cancellable demo publisher using the real Kafka ingestion path."""

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.demo.crypto_dataset import load_crypto_dataset
from app.demo.demo_profiles import DEMO_PROFILES
from app.database.repositories import get_transaction
from app.messaging.publisher import publish_transaction

logger = logging.getLogger(__name__)


class DemoGenerator:
    def __init__(self, delay_seconds: float = 1.5) -> None:
        self.delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._transactions: list[dict[str, Any]] = []

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self._stop_event.clear()
            self._transactions = []
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            was_running = self.running
            self._stop_event.set()
            return was_running

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def transactions(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._transactions)

    def status(self) -> dict[str, Any]:
        transactions = self.transactions
        for transaction in transactions:
            try:
                result = get_transaction(transaction["transaction_id"])
            except Exception:
                result = None
            if result:
                transaction.update({
                    "risk_score": result.get("risk_score"),
                    "risk_level": result.get("risk_level"),
                    "decision": result.get("decision"),
                })
        processed = [item for item in transactions if item.get("decision")]
        return {
            "running": self.running,
            "mode": "crypto_demo",
            "current_user": transactions[-1]["account_id"] if transactions else None,
            "transactions_generated": len(transactions),
            "processed": len(processed),
            "approved": sum(item.get("decision") == "APPROVE" for item in processed),
            "blocked": sum(item.get("decision") == "BLOCK" for item in processed),
            "alerts": sum(
                item.get("decision") == "BLOCK"
                and item.get("risk_level") == "HIGH"
                for item in processed
            ),
        }

    def _run(self) -> None:
        records = load_crypto_dataset(12)
        for record in records:
            if self._stop_event.is_set():
                break
            transaction = {
                "transaction_id": f"DEMO-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}-{uuid.uuid4().hex[:6]}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": record["symbol"],
                "amount": record["amount"],
                "price": record["price"],
                "quantity": record["quantity"],
                "status": "received",
                "account_id": record["account_id"],
            }
            try:
                publish_transaction(transaction)
                with self._lock:
                    self._transactions.append(transaction)
            except Exception:
                logger.exception("Demo transaction publish failed")
                break
            self._stop_event.wait(self.delay_seconds)


demo_generator = DemoGenerator()
