"""
NexusGuard Phase 9C — Alert Dashboard API.

Provides dashboard-oriented alert statistics and summaries.

IMPORTANT:
    This module only reads existing alert records.
    It does NOT calculate fraud risk.
    It does NOT modify transaction risk.
    It does NOT create alerts.

Phase 9C adds:
    - Alert statistics
    - Active alert count
    - Severity/status breakdown
    - Recent alerts
"""

import logging

from fastapi import APIRouter

from app.database.mongodb import get_database
from app.alerts.service import (
    STATUS_ACKNOWLEDGED,
    STATUS_NEW,
    STATUS_RESOLVED,
    serialize_alert,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard/alerts",
    tags=["Dashboard Alerts"],
)


# ================================================================
# ALERT DASHBOARD SUMMARY
# ================================================================

@router.get("/summary")
def alert_dashboard_summary():
    """
    Return alert statistics for the security dashboard.

    This endpoint reads directly from MongoDB alerts.
    """

    collection = get_database()["alerts"]

    total_alerts = collection.count_documents({})

    new_alerts = collection.count_documents(
        {"status": STATUS_NEW}
    )

    acknowledged_alerts = collection.count_documents(
        {"status": STATUS_ACKNOWLEDGED}
    )

    resolved_alerts = collection.count_documents(
        {"status": STATUS_RESOLVED}
    )

    high_severity_alerts = collection.count_documents(
        {"severity": "HIGH"}
    )

    return {
        "total_alerts": total_alerts,
        "active_alerts": (
            new_alerts + acknowledged_alerts
        ),
        "new_alerts": new_alerts,
        "acknowledged_alerts": acknowledged_alerts,
        "resolved_alerts": resolved_alerts,
        "high_severity_alerts": high_severity_alerts,
    }


# ================================================================
# RECENT DASHBOARD ALERTS
# ================================================================

@router.get("/recent")
def recent_dashboard_alerts(
    limit: int = 10,
):
    """
    Return recent alerts for dashboard display.
    """

    if limit < 1:
        limit = 1

    if limit > 50:
        limit = 50

    collection = get_database()["alerts"]

    cursor = (
        collection.find({})
        .sort("created_at", -1)
        .limit(limit)
    )

    return [
        serialize_alert(document)
        for document in cursor
    ]