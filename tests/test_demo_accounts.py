from scripts.publish_demo_transactions import demo_transactions


def test_demo_accounts_match_requested_scenarios():
    transactions = demo_transactions()
    assert transactions["normal"]["transaction_id"] == "KAFKA-NORMAL-001"
    assert transactions["normal"]["account_id"] == "ACC-NORMAL-001"
    assert transactions["normal"]["amount"] == 500
    assert transactions["normal"]["quantity"] == 5
    assert transactions["normal"]["symbol"] == "BTC"

    assert transactions["fraud"]["transaction_id"] == "KAFKA-FRAUD-001"
    assert transactions["fraud"]["account_id"] == "ACC-FRAUD-002"
    assert transactions["fraud"]["amount"] == 250000
    assert transactions["fraud"]["quantity"] == 8
    assert transactions["fraud"]["symbol"] == "SCAM"
