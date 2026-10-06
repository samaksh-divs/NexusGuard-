"""
NexusGuard Phase 9 — Alert Service.

This module handles alert persistence and lifecycle transitions.

IMPORTANT:
    - Alerting consumes the existing transaction risk result.
    - It does NOT calculate fraud risk.
    - It does NOT modify the existing fraud/ML pipeline.
    - One transaction can create at most one alert.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.database.mongodb import get_database

logger = logging.getLogger(__name__)


# ================================================================
# ALERT STATUS
# ================================================================

STATUS_NEW = "NEW"
STATUS_ACKNOWLEDGED = "ACKNOWLEDGED"
STATUS_RESOLVED = "RESOLVED"


# Valid state transitions.
_ALLOWED_TRANSITIONS = {
    STATUS_NEW: {
        STATUS_ACKNOWLEDGED,
        STATUS_RESOLVED,
    },
    STATUS_ACKNOWLEDGED: {
        STATUS_RESOLVED,
    },
    STATUS_RESOLVED: set(),
}


class AlertNotFoundError(Exception):
    """Raised when an alert does not exist."""


class InvalidAlertStateError(Exception):
    """Raised when an alert state transition is invalid."""


# ================================================================
# INDEXES
# ================================================================

def ensure_alert_indexes() -> None:
    """
    Create alert indexes.

    alert_id is unique.
    transaction_id is unique so the same transaction can never
    generate multiple alerts.
    """

    db = get_database()
    collection = db["alerts"]

    collection.create_index(
        [("alert_id", 1)],
        unique=True,
    )

    collection.create_index(
        [("transaction_id", 1)],
        unique=True,
    )

    collection.create_index(
        [("status", 1)],
    )

    collection.create_index(
        [("created_at", -1)],
    )

    logger.info("Phase 9 alert indexes ensured.")


# ================================================================
# ALERT CREATION
# ================================================================

def should_create_alert(
    *,
    risk_level: str | None,
    decision: str | None,
) -> bool:
    """
    Determine whether an existing transaction result requires
    an operational alert.

    This is NOT a fraud rule. It only consumes the already
    calculated backend result.
    """

    return (
        str(risk_level or "").upper() == "HIGH"
        or str(decision or "").upper() == "BLOCK"
    )


def create_alert_for_transaction(
    *,
    transaction_id: str,
    account_id: str,
    risk_score: float,
    risk_level: str,
    decision: str,
    reasons: list[str] | None = None,
) -> dict | None:
    """
    Create one alert for a transaction.

    Returns:
        Created alert document, or None if the transaction does
        not meet the existing HIGH/BLOCK operational alert condition.

    Duplicate alert creation is safely ignored.
    """

    if not should_create_alert(
        risk_level=risk_level,
        decision=decision,
    ):
        return None

    db = get_database()
    collection = db["alerts"]

    now = datetime.now(timezone.utc)

    alert = {
        "alert_id": f"ALT-{uuid4().hex[:12].upper()}",
        "transaction_id": transaction_id,
        "account_id": account_id,
        "severity": "HIGH",
        "risk_score": float(risk_score),
        "risk_level": risk_level,
        "decision": decision,
        "reasons": list(reasons or []),
        "status": STATUS_NEW,
        "created_at": now,
        "acknowledged_at": None,
        "resolved_at": None,
    }

    try:
        collection.insert_one(alert)

    except DuplicateKeyError:
        logger.info(
            "Alert already exists for transaction: %s",
            transaction_id,
        )

        existing = collection.find_one(
            {"transaction_id": transaction_id}
        )

        if existing is None:
            return None

        return serialize_alert(existing)

    logger.info(
        "Alert created: alert_id=%s transaction_id=%s",
        alert["alert_id"],
        transaction_id,
    )

    return serialize_alert(alert)


# ================================================================
# SERIALIZATION
# ================================================================

def serialize_alert(document: dict) -> dict:
    """
    Convert a MongoDB alert document into a JSON-safe dictionary.
    """

    return {
        "id": str(document.get("_id")),
        "alert_id": document["alert_id"],
        "transaction_id": document["transaction_id"],
        "account_id": document.get(
            "account_id",
            "UNKNOWN",
        ),
        "severity": document.get(
            "severity",
            "HIGH",
        ),
        "risk_score": float(
            document.get(
                "risk_score",
                0,
            )
        ),
        "risk_level": document.get(
            "risk_level",
        ),
        "decision": document.get(
            "decision",
        ),
        "reasons": list(
            document.get(
                "reasons",
                [],
            )
        ),
        "status": document.get(
            "status",
            STATUS_NEW,
        ),
        "created_at": document.get(
            "created_at",
        ),
        "acknowledged_at": document.get(
            "acknowledged_at",
        ),
        "resolved_at": document.get(
            "resolved_at",
        ),
    }


# ================================================================
# READ ALERTS
# ================================================================

def get_alerts(
    *,
    limit: int = 50,
    status: str | None = None,
) -> list[dict]:
    """
    Return recent alerts.

    Optional status filtering is supported.
    """

    if limit < 1:
        limit = 1

    if limit > 100:
        limit = 100

    db = get_database()
    collection = db["alerts"]

    query: dict = {}

    if status is not None:
        query["status"] = status

    cursor = (
        collection.find(query)
        .sort("created_at", -1)
        .limit(limit)
    )

    return [
        serialize_alert(document)
        for document in cursor
    ]


def get_alert(
    alert_id: str,
) -> dict | None:
    """Return one alert by alert_id."""

    db = get_database()

    document = db["alerts"].find_one(
        {"alert_id": alert_id}
    )

    if document is None:
        return None

    return serialize_alert(document)


# ================================================================
# STATE TRANSITIONS
# ================================================================

def transition_alert(
    *,
    alert_id: str,
    target_status: str,
) -> dict:
    """
    Move an alert through its allowed lifecycle.

    NEW -> ACKNOWLEDGED
    NEW -> RESOLVED
    ACKNOWLEDGED -> RESOLVED
    """

    target_status = target_status.upper()

    if target_status not in {
        STATUS_NEW,
        STATUS_ACKNOWLEDGED,
        STATUS_RESOLVED,
    }:
        raise InvalidAlertStateError(
            f"Unsupported alert status: {target_status}"
        )

    db = get_database()
    collection = db["alerts"]

    document = collection.find_one(
        {"alert_id": alert_id}
    )

    if document is None:
        raise AlertNotFoundError(
            f"Alert '{alert_id}' not found."
        )

    current_status = document.get(
        "status",
        STATUS_NEW,
    )

    allowed = _ALLOWED_TRANSITIONS.get(
        current_status,
        set(),
    )

    if target_status not in allowed:
        raise InvalidAlertStateError(
            f"Cannot transition alert "
            f"'{alert_id}' from "
            f"{current_status} to {target_status}."
        )

    now = datetime.now(timezone.utc)

    update_fields = {
        "status": target_status,
    }

    if target_status == STATUS_ACKNOWLEDGED:
        update_fields["acknowledged_at"] = now

    elif target_status == STATUS_RESOLVED:
        update_fields["resolved_at"] = now

    collection.update_one(
        {"alert_id": alert_id},
        {
            "$set": update_fields,
        },
    )

    updated = collection.find_one(
        {"alert_id": alert_id}
    )

    if updated is None:
        raise AlertNotFoundError(
            f"Alert '{alert_id}' disappeared during update."
        )

    logger.info(
        "Alert transition: %s %s -> %s",
        alert_id,
        current_status,
        target_status,
    )

    return serialize_alert(updated)


def acknowledge_alert(
    alert_id: str,
) -> dict:
    """Acknowledge a NEW alert."""

    return transition_alert(
        alert_id=alert_id,
        target_status=STATUS_ACKNOWLEDGED,
    )


def resolve_alert(
    alert_id: str,
) -> dict:
    """Resolve a NEW or ACKNOWLEDGED alert."""

    return transition_alert(
        alert_id=alert_id,
        target_status=STATUS_RESOLVED,
    )