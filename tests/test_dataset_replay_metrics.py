import csv
from types import SimpleNamespace

from app.demo.dataset_replay import DatasetReplayEngine
from app.demo.dataset_replay import DatasetAdapter
from app.database import repositories
from app.database.repositories import serialize_transaction
from app.messaging import consumer
from app.validation.schemas import TransactionCreate


def test_replay_metrics_compare_only_backend_decisions_to_labels():
    metrics = DatasetReplayEngine._classification_metrics(
        expected=[1, 1, 0, 0],
        predicted=[1, 0, 1, 0],
    )

    assert metrics == {
        "accuracy": 0.5,
        "precision": 0.5,
        "recall": 0.5,
        "f1_score": 0.5,
        "true_positives": 1,
        "false_positives": 1,
        "true_negatives": 1,
        "false_negatives": 1,
        "evaluation_samples": 4,
    }


def test_replay_metrics_leave_undefined_values_unavailable():
    metrics = DatasetReplayEngine._classification_metrics(
        expected=[],
        predicted=[],
    )

    assert metrics["accuracy"] is None
    assert metrics["precision"] is None
    assert metrics["recall"] is None
    assert metrics["f1_score"] is None
    assert metrics["evaluation_samples"] == 0


def test_replay_metrics_report_zero_when_no_positive_decisions_were_made():
    metrics = DatasetReplayEngine._classification_metrics(
        expected=[1, 0],
        predicted=[0, 0],
    )

    assert metrics["accuracy"] == 0.5
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["f1_score"] == 0.0


def test_transaction_serialization_preserves_batch_context_for_detail_view():
    transaction = serialize_transaction({
        "_id": "stored-id",
        "transaction_id": "REPLAY-1",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "symbol": "BTC",
        "price": 50000,
        "quantity": 0.01,
        "transaction_value": 500,
        "status": "processed",
        "account_id": "account-1",
        "source_transaction_id": "source-1",
        "source_dataset": "Elliptic Bitcoin Dataset",
        "sender": "sender-1",
        "receiver": "receiver-1",
        "amount": 500,
        "ground_truth_label": 1,
        "original_label": "illicit",
        "decision": "BLOCK",
        "risk_reasons": ["Critical fraud rule triggered"],
        "network": "Bitcoin Mainnet",
        "bitcoin_amount": 0.01,
        "fee_sats": 123,
        "vin": [{"prevout": {"scriptpubkey_address": "sender-1", "value": 1000000}}],
        "vout": [{"scriptpubkey_address": "receiver-1", "value": 999877}],
        "mempool_status": {"confirmed": False},
        "mempool_observed_at": "2026-01-01T00:01:00+00:00",
    })

    assert transaction["source_transaction_id"] == "source-1"
    assert transaction["amount"] == 500
    assert transaction["ground_truth_label"] == 1
    assert transaction["original_label"] == "illicit"
    assert transaction["risk_reasons"] == ["Critical fraud rule triggered"]
    assert transaction["network"] == "Bitcoin Mainnet"
    assert transaction["bitcoin_amount"] == 0.01
    assert transaction["fee_sats"] == 123
    assert transaction["vin"][0]["prevout"]["scriptpubkey_address"] == "sender-1"
    assert transaction["vout"][0]["scriptpubkey_address"] == "receiver-1"
    assert transaction["mempool_status"] == {"confirmed": False}
    assert transaction["mempool_observed_at"] == "2026-01-01T00:01:00+00:00"


def test_dataset_adapter_preserves_source_id_and_native_amount(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    dataset_file = data_dir / "elliptic_bitcoin_dataset.csv"
    with dataset_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "txId",
                "timestamp",
                "sender",
                "receiver",
                "amount",
                "fee",
                "original_label",
                "ground_truth_label",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "txId": "source-transaction-1",
            "timestamp": "2025-01-15T12:02:00+00:00",
            "sender": "source-sender",
            "receiver": "source-receiver",
            "amount": "1.0894",
            "fee": "0.0011",
            "original_label": "licit",
            "ground_truth_label": "0",
        })

    monkeypatch.setattr("app.demo.dataset_replay.PROJECT_ROOT", tmp_path)

    _, transactions = DatasetAdapter.load_dataset("elliptic_bitcoin", count=1)
    transaction = transactions[0]

    assert transaction["transaction_id"] == "source-transaction-1"
    assert transaction["source_transaction_id"] == "source-transaction-1"
    assert transaction["amount"] == 1.0894
    assert transaction["quantity"] == 1.0894
    assert transaction["price"] is None
    assert transaction["transaction_value"] == 1.0894


def test_insert_transaction_persists_native_amount_without_fabricated_price(monkeypatch):
    class FakeTransactions:
        document = None

        def insert_one(self, document):
            self.document = document
            return SimpleNamespace(inserted_id="mongo-id")

    class FakeDatabase:
        def __init__(self):
            self.transactions = FakeTransactions()

        def __getitem__(self, collection_name):
            assert collection_name == "transactions"
            return self.transactions

    database = FakeDatabase()
    monkeypatch.setattr(repositories, "get_database", lambda: database)

    inserted = repositories.insert_transaction({
        "transaction_id": "source-transaction-1",
        "timestamp": "2025-01-15T12:02:00+00:00",
        "symbol": "BTC",
        "price": None,
        "quantity": 1.0894,
        "amount": 1.0894,
        "transaction_value": 1.0894,
        "source_transaction_id": "source-transaction-1",
        "source_dataset": "Elliptic Bitcoin Dataset",
        "status": "processed",
        "account_id": "source-sender",
    })

    assert inserted["transaction_id"] == "source-transaction-1"
    assert inserted["price"] is None
    assert inserted["amount"] == 1.0894
    assert inserted["transaction_value"] == 1.0894
    assert serialize_transaction(inserted)["amount"] == 1.0894


def test_replay_does_not_republish_source_ids_already_in_mongodb(monkeypatch):
    engine = DatasetReplayEngine()
    engine._transactions = [{"transaction_id": "source-transaction-1"}]
    engine._replay_speed = 10.0
    engine._has_run = True
    monkeypatch.setattr(
        "app.demo.dataset_replay.get_transactions_by_ids",
        lambda transaction_ids: {
            transaction_id: {"transaction_id": transaction_id, "decision": "APPROVE"}
            for transaction_id in transaction_ids
        },
    )
    published = []
    monkeypatch.setattr(
        "app.demo.dataset_replay.publish_transaction",
        published.append,
    )

    engine._run()

    assert published == []
    assert engine._publication_complete is True


def test_replay_completes_only_after_backend_decisions_are_persisted(monkeypatch):
    engine = DatasetReplayEngine()
    engine._transactions = [{"transaction_id": "source-transaction-1"}]
    engine._dataset_config = {"id": "dataset", "name": "Dataset"}
    engine._has_run = True
    engine._publication_complete = True
    stored = {"source-transaction-1": {"transaction_id": "source-transaction-1"}}
    monkeypatch.setattr(
        "app.demo.dataset_replay.get_transactions_by_ids",
        lambda transaction_ids: stored,
    )
    monkeypatch.setattr(
        "app.demo.dataset_replay.get_model_availability",
        lambda: {
            name: {"available": False, "missing_artifacts": ["model.pkl"]}
            for name in ("Random Forest", "XGBoost", "LSTM", "Ensemble")
        },
    )

    status = engine.status()
    assert status["replay_state"] == "PROCESSING"
    assert status["processed"] == 0

    stored["source-transaction-1"]["decision"] = "APPROVE"
    status = engine.status()
    assert status["replay_state"] == "COMPLETED"
    assert status["processed"] == 1


def test_mempool_zero_value_transactions_are_valid_without_substituting_amounts():
    transaction = TransactionCreate(
        transaction_id="op-return-transaction",
        timestamp="2026-01-01T00:00:00Z",
        symbol="BTC",
        amount=0,
        price=50000,
        quantity=0,
        bitcoin_amount=0,
        account_id="op-return-transaction",
    )

    assert transaction.amount == 0
    assert transaction.quantity == 0
    assert transaction.bitcoin_amount == 0


def test_missing_ml_models_use_rule_score_instead_of_a_fake_zero_prediction():
    assert consumer.calculate_final_ml_risk(rule_score=60, ml_score=None) == (
        60.0,
        "MEDIUM",
        "REVIEW",
    )


def test_missing_ml_service_does_not_create_zero_probability_predictions(monkeypatch):
    monkeypatch.setattr(consumer, "predict_transaction_risk", None)

    assert consumer._run_ml_prediction({}) == (None, None, None, None)
