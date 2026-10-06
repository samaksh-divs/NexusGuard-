import argparse
import json
import time
import uuid
import random
from datetime import datetime, timezone
from urllib.request import Request, urlopen

SCENARIOS = {
    "NORMAL": {"amount": (100, 1000), "velocity": 1, "pattern": "normal"},
    "LARGE_TRANSACTION": {"amount": (50000, 150000), "velocity": 1, "pattern": "large"},
    "BEHAVIORAL_ANOMALY": {"amount": (5000, 10000), "velocity": 1, "pattern": "behavioral"},
    "HIGH_VELOCITY": {"amount": (100, 500), "velocity": 5, "pattern": "velocity"},
    "FAN_OUT": {"amount": (10000, 50000), "velocity": 1, "pattern": "fan_out"},
    "FAN_IN": {"amount": (100, 500), "velocity": 1, "pattern": "fan_in"},
    "RAPID_MULTI_HOP": {"amount": (20000, 80000), "velocity": 1, "pattern": "multi_hop"},
    "STRUCTURING": {"amount": (9900, 9999), "velocity": 4, "pattern": "structuring"},
    "CYBER_FRAUD_INDICATOR": {"amount": (100000, 500000), "velocity": 3, "pattern": "cyber_fraud"},
    "MIXED_SUSPICIOUS": {"amount": (50000, 100000), "velocity": 2, "pattern": "mixed"}
}

def generate_transaction(scenario_name: str, index: int = 0):
    scenario = SCENARIOS[scenario_name]
    amount = round(random.uniform(*scenario["amount"]), 2)
    
    sender = f"0x{random.randint(0, 0xFFFFFF):06x}"
    receiver = f"0x{random.randint(0, 0xFFFFFF):06x}"
    
    if scenario["pattern"] == "fan_out":
        sender = "0xFAN00T"
    elif scenario["pattern"] == "fan_in":
        receiver = "0xFAN1NN"
    elif scenario["pattern"] == "cyber_fraud":
        sender = f"0xCYB3R{index}"
        receiver = f"0xCYB3R{index+1}"

    # To ensure it hits backend logic, we map it to known demo users if needed, 
    # but we can also just let the model score the amounts and velocity.
    account_id = "DEMO-USER-A" if scenario_name == "NORMAL" else "DEMO-USER-B"

    return {
        "transaction_id": f"TX-{datetime.now(timezone.utc):%H%M%S}-{uuid.uuid4().hex[:4]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "fee": round(amount * 0.001, 2),
        "chain": "Ethereum",
        "scenario_hint": scenario_name
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scenario", default="ALL", help="Specific scenario or ALL")
    args = parser.parse_args()
    
    scenarios_to_run = list(SCENARIOS.keys()) if args.scenario == "ALL" else [args.scenario]
    
    print(f"Starting NexusGuard Transaction Simulator...")
    
    for scenario_name in scenarios_to_run:
        velocity = SCENARIOS[scenario_name]["velocity"]
        print(f"\n--- Scenario: {scenario_name} ---")
        
        for i in range(velocity):
            tx = generate_transaction(scenario_name, i)
            payload = json.dumps(tx).encode("utf-8")
            try:
                request = Request(
                    f"{args.api_url.rstrip('/')}/transactions/publish",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    res = response.read().decode('utf-8')
                    print(f"[{tx['transaction_id']}] Sent {scenario_name} - ${tx['amount']} - {res}")
            except Exception as e:
                print(f"Failed to publish {tx['transaction_id']}: {e}")
            time.sleep(0.5)

if __name__ == "__main__":
    main()
