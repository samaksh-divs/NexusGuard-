"""
MongoDB connection layer.

Why this file exists:
Creating a new MongoClient for every request is wasteful — MongoClient
already manages its own internal connection pool, so we want exactly
ONE client instance shared across the whole application (FastAPI routes
today; RabbitMQ workers and ML workers in later phases).

This module is intentionally the ONLY place that talks to
`pymongo.MongoClient` directly. Everything else (routes, repositories,
workers) should import `get_database()` or the collection helpers from
here instead of creating their own connections.
"""

import logging

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.config.settings import settings

logger = logging.getLogger(__name__)

# Module-level singleton. Created lazily on first use (see connect_to_mongo).
_client: MongoClient | None = None
_database: Database | None = None


def connect_to_mongo() -> None:
    """
    Create the MongoClient and verify connectivity.

    Call this once at application startup (see app/main.py's startup
    event). If MongoDB is unreachable, this raises so the failure is
    visible immediately instead of surfacing later as a mysterious
    error on the first request.
    """
    global _client, _database

    try:
        # serverSelectionTimeoutMS keeps failures fast (5s) instead of
        # hanging for pymongo's default 30s when Mongo is down.
        _client = MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,
        )

        # The ismaster/hello command is cheap and forces pymongo to
        # actually attempt a connection right now.
        _client.admin.command("ping")

        _database = _client[settings.mongodb_database]
        _ensure_indexes(_database)

        logger.info(
            "Connected to MongoDB at %s (db=%s)",
            settings.mongodb_uri,
            settings.mongodb_database,
        )

    except PyMongoError:
        logger.exception(
            "Failed to connect to MongoDB at %s",
            settings.mongodb_uri,
        )
        raise


def close_mongo_connection() -> None:
    """Close the MongoDB client. Call this on application shutdown."""
    global _client

    if _client is not None:
        _client.close()
        logger.info("MongoDB connection closed")


def get_database() -> Database:
    """
    Return the shared database handle.

    Raises RuntimeError if called before connect_to_mongo() has run.
    """
    if _database is None:
        raise RuntimeError(
            "MongoDB has not been initialized. "
            "Was connect_to_mongo() called on startup?"
        )

    return _database


def check_mongo_health() -> bool:
    """
    Lightweight connectivity check used by the /health endpoint.

    Returns True/False rather than raising.
    """
    if _client is None:
        return False

    try:
        _client.admin.command("ping")
        return True

    except PyMongoError:
        logger.warning(
            "MongoDB health check failed",
            exc_info=True,
        )
        return False


def _ensure_indexes(database: Database) -> None:
    """
    Create indexes needed by NexusGuard collections.

    create_index() is idempotent, so this is safe on every startup.
    """

    # ============================================================
    # TRANSACTIONS
    # ============================================================

    database["transactions"].create_index(
        [("transaction_id", ASCENDING)],
        unique=True,
    )

    database["transactions"].create_index(
        [("timestamp", ASCENDING)],
    )

    database["transactions"].create_index(
        [
            ("account_id", ASCENDING),
            ("timestamp", ASCENDING),
        ],
    )

    # ============================================================
    # EXISTING FUTURE-USE COLLECTIONS
    # ============================================================

    database["predictions"].create_index(
        [("transaction_id", ASCENDING)],
    )

    database["explanations"].create_index(
        [("transaction_id", ASCENDING)],
    )

    database["failed_transactions"].create_index(
        [("transaction_id", ASCENDING)],
    )

    # ============================================================
    # PHASE 9 — ALERTS
    # ============================================================

    # Every alert gets a globally unique alert_id.
    database["alerts"].create_index(
        [("alert_id", ASCENDING)],
        unique=True,
    )

    # CRITICAL:
    # A transaction may create at most one operational alert.
    database["alerts"].create_index(
        [("transaction_id", ASCENDING)],
        unique=True,
    )

    # Useful for filtering/monitoring alert lifecycle state.
    database["alerts"].create_index(
        [("status", ASCENDING)],
    )

    # Newest alerts first.
    database["alerts"].create_index(
        [("created_at", DESCENDING)],
    )

    logger.info("MongoDB indexes verified, including Phase 9 alerts.")