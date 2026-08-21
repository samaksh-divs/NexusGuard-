from app.demo.crypto_dataset import load_crypto_dataset
from app.demo.demo_profiles import DEMO_PROFILES


def test_demo_dataset_has_120_normalized_patterns():
    records = load_crypto_dataset()
    assert len(records) == 120
    assert {record["account_id"] for record in records} == {"DEMO-USER-A", "DEMO-USER-B"}
    assert all(record["amount"] == round(record["price"] * record["quantity"], 8) for record in records)


def test_demo_profiles_are_explicitly_simulated_accounts():
    assert DEMO_PROFILES["DEMO-USER-A"]["classification"] == "SAFE"
    assert DEMO_PROFILES["DEMO-USER-B"]["classification"] == "MONITORED"


def test_dataset_contains_both_rule_driven_transaction_shapes():
    records = load_crypto_dataset()
    normal = [record for record in records if record["account_id"] == "DEMO-USER-A"]
    suspicious = [record for record in records if record["account_id"] == "DEMO-USER-B"]
    assert len(normal) >= 5
    assert len(suspicious) >= 5
    assert any(record["symbol"] == "SCAM" for record in suspicious)
    assert any(record["quantity"] >= 10 for record in suspicious)
