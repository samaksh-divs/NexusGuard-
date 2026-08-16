from pathlib import Path
import pandas as pd


DATA_DIR = Path("data/elliptic")

FEATURES_FILE = DATA_DIR / "elliptic_txs_features.csv"
CLASSES_FILE = DATA_DIR / "elliptic_txs_classes.csv"


def load_elliptic_dataset():
    """
    Load the Elliptic Bitcoin transaction dataset.

    Features file:
        txId | time_step | 165 features

    Classes file:
        txId | class
    """

    # Load features without assuming a header row
    features = pd.read_csv(
        FEATURES_FILE,
        header=None
    )

    # Create correct column names
    feature_columns = (
        ["txId", "time_step"]
        + [f"feature_{i}" for i in range(1, 166)]
    )

    features.columns = feature_columns

    # Load class labels
    classes = pd.read_csv(CLASSES_FILE)

    # Merge labels with transaction features
    dataset = features.merge(
        classes,
        on="txId",
        how="left"
    )

    return dataset


def get_labeled_dataset(dataset):
    """
    Return only transactions with known labels.

    class 1 = illicit
    class 2 = licit
    """

    labeled = dataset[
        dataset["class"].isin(["1", "2", 1, 2])
    ].copy()

    labeled["target"] = (
        labeled["class"]
        .astype(str)
        .map({
            "1": 1,   # illicit
            "2": 0    # licit
        })
    )

    return labeled


def get_ml_features(dataset):
    """
    Extract the 165 numerical transaction features.
    """

    feature_columns = [
        f"feature_{i}"
        for i in range(1, 166)
    ]

    return dataset[feature_columns]


def split_by_time(dataset, train_ratio=0.8):
    """
    Time-based split to prevent future information
    leaking into model training.
    """

    dataset = dataset.sort_values("time_step").reset_index(drop=True)

    split_index = int(len(dataset) * train_ratio)

    train = dataset.iloc[:split_index].copy()
    test = dataset.iloc[split_index:].copy()

    return train, test
def prepare_training_data(dataset):
    """
    Prepare labeled transactions for ML training.
    """

    labeled = get_labeled_dataset(dataset)

    # Sort chronologically
    labeled = labeled.sort_values("time_step").reset_index(drop=True)

    # Extract features and target
    X = get_ml_features(labeled)
    y = labeled["target"]

    return X, y, labeled


def time_based_train_test_split(dataset, train_ratio=0.8):
    """
    Split labeled transactions chronologically.

    Earlier transactions -> training
    Later transactions  -> testing

    This prevents future information leaking into training.
    """

    labeled = get_labeled_dataset(dataset)

    labeled = labeled.sort_values(
        "time_step"
    ).reset_index(drop=True)

    split_index = int(len(labeled) * train_ratio)

    train = labeled.iloc[:split_index].copy()
    test = labeled.iloc[split_index:].copy()

    X_train = get_ml_features(train)
    y_train = train["target"]

    X_test = get_ml_features(test)
    y_test = test["target"]

    return X_train, X_test, y_train, y_test