"""
NexusGuard Phase 8 — Dashboard API.

Provides monitoring and analytics endpoints using
the existing MongoDB transactions collection.

Endpoints:
    GET /dashboard/summary
    GET /dashboard/recent-transactions
    GET /dashboard/risk-distribution
    GET /dashboard/suspicious-accounts
"""

import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
import asyncio
from pydantic import BaseModel

from app.database.mongodb import get_database
from app.database.repositories import (
    get_transactions,
    serialize_transaction,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)


# ================================================================
# DASHBOARD SUMMARY
# ================================================================

@router.get("/summary")
def dashboard_summary():
    """
    Return overall NexusGuard monitoring statistics.
    """

    db = get_database()
    collection = db["transactions"]

    total = collection.count_documents({})

    approved = collection.count_documents({
        "decision": "APPROVE"
    })

    review = collection.count_documents({
        "decision": "REVIEW"
    })

    blocked = collection.count_documents({
        "decision": "BLOCK"
    })

    processed = collection.count_documents({
        "processed_at": {
            "$exists": True
        }
    })

    unprocessed = total - processed

    # ------------------------------------------------------------
    # Average risk score
    # ------------------------------------------------------------

    pipeline = [
        {
            "$match": {
                "risk_score": {
                    "$exists": True
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "average_risk_score": {
                    "$avg": "$risk_score"
                },
            }
        },
    ]

    result = list(
        collection.aggregate(pipeline)
    )

    average_risk_score = 0.0

    if result:
        average_risk_score = round(
            float(
                result[0].get(
                    "average_risk_score",
                    0,
                )
            ),
            2,
        )

    # ------------------------------------------------------------
    # Risk levels
    # ------------------------------------------------------------

    high_risk = collection.count_documents({
        "risk_level": "HIGH"
    })

    medium_risk = collection.count_documents({
        "risk_level": "MEDIUM"
    })

    low_risk = collection.count_documents({
        "risk_level": "LOW"
    })

    return {
        "total_transactions": total,

        "processed_transactions": processed,

        "unprocessed_transactions": unprocessed,

        "approved": approved,

        "review": review,

        "blocked": blocked,

        "risk_levels": {
            "HIGH": high_risk,
            "MEDIUM": medium_risk,
            "LOW": low_risk,
        },

        "average_risk_score": average_risk_score,
    }


# ================================================================
# RECENT TRANSACTIONS
# ================================================================

@router.get("/recent-transactions")
def recent_transactions(
    limit: int = 20,
):
    """
    Return the most recent transactions.
    """

    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="limit must be greater than 0.",
        )

    if limit > 100:
        limit = 100

    documents = get_transactions(
        limit=limit
    )

    return [
        serialize_transaction(document)
        for document in documents
    ]


# ================================================================
# RISK DISTRIBUTION
# ================================================================

@router.get("/risk-distribution")
def risk_distribution():
    """
    Return transaction distribution by risk level.
    """

    db = get_database()
    collection = db["transactions"]

    pipeline = [
        {
            "$group": {
                "_id": "$risk_level",
                "count": {
                    "$sum": 1
                },
            }
        }
    ]

    results = list(
        collection.aggregate(pipeline)
    )

    distribution = {
        "LOW": 0,
        "MEDIUM": 0,
        "HIGH": 0,
        "UNKNOWN": 0,
    }

    for item in results:

        level = item.get(
            "_id"
        )

        count = int(
            item.get(
                "count",
                0,
            )
        )

        if level in distribution:
            distribution[level] = count

        else:
            distribution["UNKNOWN"] += count

    return distribution


# ================================================================
# SUSPICIOUS ACCOUNTS
# ================================================================

@router.get("/suspicious-accounts")
def suspicious_accounts(
    limit: int = 10,
):
    """
    Return accounts with the highest average risk scores.
    """

    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="limit must be greater than 0.",
        )

    if limit > 50:
        limit = 50

    db = get_database()
    collection = db["transactions"]

    pipeline = [
        {
            "$match": {
                "risk_score": {
                    "$exists": True
                }
            }
        },
        {
            "$group": {
                "_id": "$account_id",

                "transaction_count": {
                    "$sum": 1
                },

                "average_risk_score": {
                    "$avg": "$risk_score"
                },

                "maximum_risk_score": {
                    "$max": "$risk_score"
                },

                "blocked_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$eq": [
                                    "$decision",
                                    "BLOCK",
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },

                "review_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$eq": [
                                    "$decision",
                                    "REVIEW",
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$sort": {
                "average_risk_score": -1
            }
        },
        {
            "$limit": limit
        },
    ]

    results = list(
        collection.aggregate(pipeline)
    )

    output = []

    for item in results:

        output.append({
            "account_id": item.get(
                "_id",
                "UNKNOWN",
            ),

            "transaction_count": int(
                item.get(
                    "transaction_count",
                    0,
                )
            ),

            "average_risk_score": round(
                float(
                    item.get(
                        "average_risk_score",
                        0,
                    )
                ),
                2,
            ),

            "maximum_risk_score": round(
                float(
                    item.get(
                        "maximum_risk_score",
                        0,
                    )
                ),
                2,
            ),

            "blocked_count": int(
                item.get(
                    "blocked_count",
                    0,
                )
            ),

            "review_count": int(
                item.get(
                    "review_count",
                    0,
                )
            ),
        })

    return output


# ================================================================
# REAL-TIME TRANSACTIONS WEBSOCKET
# ================================================================

@router.websocket("/live")
async def live_transactions_ws(websocket: WebSocket):
    """Stream newly processed transactions to the dashboard."""
    await websocket.accept()
    
    last_seen_id = None
    db = get_database()
    collection = db["transactions"]
    
    try:
        while True:
            # Polling strategy for simplicity in this architecture
            # Find the latest 20 if we haven't seen any yet, else find newer ones
            query = {}
            if last_seen_id:
                query["_id"] = {"$gt": last_seen_id}
                
            cursor = collection.find(query).sort("_id", -1).limit(20)
            # Need to reverse to send oldest first among the new ones
            new_txs = list(cursor)[::-1]
            
            if new_txs:
                last_seen_id = new_txs[-1]["_id"]
                serialized = [serialize_transaction(tx) for tx in new_txs]
                await websocket.send_json({"type": "new_transactions", "data": serialized})
                
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

# ================================================================
# INVESTIGATOR FEEDBACK
# ================================================================

class FeedbackModel(BaseModel):
    feedback: str  # "LEGITIMATE", "FRAUD", "FALSE_POSITIVE", "NEEDS_INVESTIGATION"

@router.post("/transactions/{transaction_id}/feedback")
def submit_feedback(transaction_id: str, feedback: FeedbackModel):
    db = get_database()
    collection = db["transactions"]
    result = collection.update_one(
        {"transaction_id": transaction_id},
        {"$set": {"investigator_feedback": feedback.feedback}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"status": "success", "feedback": feedback.feedback}