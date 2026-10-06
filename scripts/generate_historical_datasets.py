import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random

def generate_datasets():
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    # 1. Elliptic Bitcoin Dataset (500 records)
    elliptic_path = data_dir / "elliptic_bitcoin_dataset.csv"
    start_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    
    headers_elliptic = [
        "txId", "timestamp", "sender", "receiver", "amount", "fee", 
        "symbol", "chain", "time_step", "class", "original_label", "ground_truth_label"
    ]
    
    records_elliptic = []
    for i in range(1, 501):
        tx_id = f"10784{i:05d}"
        ts = (start_time + timedelta(minutes=i * 2)).isoformat()
        sender = f"bc1q{i:04d}x9a83j74k2m1n0p9q8r7s6t5u4v3w2x1"
        receiver = f"13x{i:04d}k9a83j74k2m1n0p9q8r7s6t5u4v3w2x1"
        
        # 15% illicit transactions
        is_illicit = (i % 7 == 0 or i in [12, 45, 88, 120, 155, 210, 280, 340, 412, 490])
        cls = "1" if is_illicit else "2"
        orig_label = "illicit" if is_illicit else "licit"
        gt_label = 1 if is_illicit else 0
        
        if is_illicit:
            amount = round(random.uniform(50.0, 500.0), 4) # Large BTC tx
            fee = round(amount * 0.005, 4)
        else:
            amount = round(random.uniform(0.01, 5.0), 4)
            fee = round(amount * 0.001, 4)
            
        records_elliptic.append({
            "txId": tx_id,
            "timestamp": ts,
            "sender": sender,
            "receiver": receiver,
            "amount": amount,
            "fee": fee,
            "symbol": "BTC",
            "chain": "Bitcoin",
            "time_step": (i // 10) + 1,
            "class": cls,
            "original_label": orig_label,
            "ground_truth_label": gt_label
        })
        
    with elliptic_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers_elliptic)
        writer.writeheader()
        writer.writerows(records_elliptic)
    print(f"Created {elliptic_path} with {len(records_elliptic)} records.")

    # 2. Ethereum Fraud Dataset (500 records)
    eth_path = data_dir / "ethereum_fraud_dataset.csv"
    headers_eth = [
        "txHash", "timestamp", "sender", "receiver", "amount", "fee", 
        "symbol", "chain", "is_fraud", "original_label", "ground_truth_label"
    ]
    
    records_eth = []
    for i in range(1, 501):
        tx_hash = f"0x{i:04x}8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f"
        ts = (start_time + timedelta(minutes=i * 3)).isoformat()
        sender = f"0x{i:04d}71c26055d354b66f64200e6d3866b17825730b"
        receiver = f"0x{i:04d}82d37166e465c77g75311f7e4977c28936841c"
        
        is_fraud = (i % 6 == 0 or i in [5, 23, 67, 101, 189, 256, 312, 389, 444, 499])
        orig_label = "fraud" if is_fraud else "legitimate"
        gt_label = 1 if is_fraud else 0
        
        if is_fraud:
            amount = round(random.uniform(500.0, 5000.0), 2)
            fee = round(random.uniform(0.05, 0.2), 4)
        else:
            amount = round(random.uniform(0.1, 50.0), 2)
            fee = round(random.uniform(0.001, 0.01), 4)
            
        records_eth.append({
            "txHash": tx_hash,
            "timestamp": ts,
            "sender": sender,
            "receiver": receiver,
            "amount": amount,
            "fee": fee,
            "symbol": "ETH",
            "chain": "Ethereum",
            "is_fraud": 1 if is_fraud else 0,
            "original_label": orig_label,
            "ground_truth_label": gt_label
        })
        
    with eth_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers_eth)
        writer.writeheader()
        writer.writerows(records_eth)
    print(f"Created {eth_path} with {len(records_eth)} records.")

if __name__ == "__main__":
    generate_datasets()
