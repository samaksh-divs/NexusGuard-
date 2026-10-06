"""
NexusGuard Phase 9B — Alert API.

Provides read and lifecycle endpoints for operational alerts.

IMPORTANT:
    This API consumes alerts created by the existing fraud/ML pipeline.
    It does NOT calculate or modify transaction risk.
"""

from fastapi import APIRouter, HTTPException

from app.alerts.service import (
    AlertNotFoundError,
    InvalidAlertStateError,
    STATUS_ACKNOWLEDGED,
    STATUS_NEW,
    STATUS_RESOLVED,
    acknowledge_alert,
    get_alert,
    get_alerts,
    resolve_alert,
)

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
)


# ================================================================
# LIST ALERTS
# ================================================================

@router.get("")
def list_alerts(
    limit: int = 50,
    status: str | None = None,
):
    """
    Return recent operational alerts.

    Optional status filtering:
        NEW
        ACKNOWLEDGED
        RESOLVED
    """

    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="limit must be greater than 0.",
        )

    if limit > 100:
        limit = 100

    if status is not None:
        status = status.upper()

        if status not in {
            STATUS_NEW,
            STATUS_ACKNOWLEDGED,
            STATUS_RESOLVED,
        }:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid alert status. "
                    "Use NEW, ACKNOWLEDGED, or RESOLVED."
                ),
            )

    return get_alerts(
        limit=limit,
        status=status,
    )


# ================================================================
# GET SINGLE ALERT
# ================================================================

@router.get("/{alert_id}")
def read_alert(
    alert_id: str,
):
    """
    Return one alert by alert_id.
    """

    alert = get_alert(alert_id)

    if alert is None:
        raise HTTPException(
            status_code=404,
            detail=f"Alert '{alert_id}' not found.",
        )

    return alert


# ================================================================
# ACKNOWLEDGE ALERT
# ================================================================

@router.post("/{alert_id}/acknowledge")
def acknowledge_existing_alert(
    alert_id: str,
):
    """
    Move an alert from NEW to ACKNOWLEDGED.
    """

    try:
        return acknowledge_alert(alert_id)

    except AlertNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except InvalidAlertStateError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )


# ================================================================
# RESOLVE ALERT
# ================================================================

@router.post("/{alert_id}/resolve")
def resolve_existing_alert(
    alert_id: str,
):
    """
    Resolve an alert.

    Allowed transitions:
        NEW -> RESOLVED
        ACKNOWLEDGED -> RESOLVED
    """

    try:
        return resolve_alert(alert_id)

    except AlertNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except InvalidAlertStateError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )