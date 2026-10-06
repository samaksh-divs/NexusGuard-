from pathlib import Path

import joblib
import numpy as np
import torch
import torch.nn as nn

from sklearn.preprocessing import StandardScaler

from app.ml.preprocessing import (
    load_elliptic_dataset,
    get_labeled_dataset,
)


MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "lstm_fraud.pt"
SCALER_PATH = MODEL_DIR / "lstm_scaler.pkl"


class FraudLSTM(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size=64,
        num_layers=2,
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.2,
        )

        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):

        output, _ = self.lstm(x)

        # Last timestep
        last_output = output[:, -1, :]

        return self.fc(last_output)


def create_sequences(X, y, sequence_length=10):

    sequences = []
    labels = []

    for i in range(len(X) - sequence_length):

        sequence = X[i:i + sequence_length]

        target = y[i + sequence_length]

        sequences.append(sequence)
        labels.append(target)

    return (
        np.array(sequences, dtype=np.float32),
        np.array(labels, dtype=np.float32),
    )


def train_lstm():

    print("[LSTM] Loading Elliptic dataset...")

    dataset = load_elliptic_dataset()

    dataset = get_labeled_dataset(dataset)

    # Chronological ordering
    dataset = dataset.sort_values(
        "time_step"
    ).reset_index(drop=True)

    feature_columns = [
        f"feature_{i}"
        for i in range(1, 166)
    ]

    X = dataset[feature_columns].values.astype(np.float32)

    y = dataset["target"].values.astype(np.float32)

    # Time-based split
    split_index = int(len(X) * 0.8)

    X_train = X[:split_index]
    X_test = X[split_index:]

    y_train = y[:split_index]
    y_test = y[split_index:]

    # Scale using training data ONLY
    scaler = StandardScaler()

    X_train = scaler.fit_transform(X_train)

    X_test = scaler.transform(X_test)

    joblib.dump(scaler, SCALER_PATH)

    sequence_length = 10

    X_train_seq, y_train_seq = create_sequences(
        X_train,
        y_train,
        sequence_length,
    )

    X_test_seq, y_test_seq = create_sequences(
        X_test,
        y_test,
        sequence_length,
    )

    print(
        f"[LSTM] Training sequences: {len(X_train_seq)}"
    )

    print(
        f"[LSTM] Testing sequences: {len(X_test_seq)}"
    )

    print(
        f"[LSTM] Sequence length: {sequence_length}"
    )

    device = torch.device(
        "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )

    print(f"[LSTM] Device: {device}")

    model = FraudLSTM(
        input_size=165
    ).to(device)

    X_train_tensor = torch.tensor(
        X_train_seq
    ).to(device)

    y_train_tensor = torch.tensor(
        y_train_seq
    ).unsqueeze(1).to(device)

    criterion = nn.BCEWithLogitsLoss()

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=0.001,
    )

    epochs = 10

    print("[LSTM] Training...")

    model.train()

    for epoch in range(epochs):

        optimizer.zero_grad()

        outputs = model(
            X_train_tensor
        )

        loss = criterion(
            outputs,
            y_train_tensor,
        )

        loss.backward()

        optimizer.step()

        print(
            f"Epoch {epoch + 1}/{epochs} "
            f"- Loss: {loss.item():.4f}"
        )

    torch.save(
        model.state_dict(),
        MODEL_PATH,
    )

    print(
        f"[LSTM] Model saved to: {MODEL_PATH}"
    )


if __name__ == "__main__":
    train_lstm()