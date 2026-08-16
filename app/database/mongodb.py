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

from pymongo import ASCENDING, MongoClient
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
        _client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)

        # The ismaster/hello command is cheap and forces pymongo to
        # actually attempt a connection right now, rather than lazily
        # on first real query.
        _client.admin.command("ping")

        _database = _client[settings.mongodb_database]
        _ensure_indexes(_database)

        logger.info("Connected to MongoDB at %s (db=%s)", settings.mongodb_uri, settings.mongodb_database)

    except PyMongoError:
        logger.exception("Failed to connect to MongoDB at %s", settings.mongodb_uri)
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

    Raises RuntimeError if called before connect_to_mongo() has run
    (e.g. if a route is hit before startup finished) — this is a
    programming error, not a runtime/network failure, so we fail loudly.
    """
    if _database is None:
        raise RuntimeError("MongoDB has not been initialized. Was connect_to_mongo() called on startup?")
    return _database


def check_mongo_health() -> bool:
    """
    Lightweight connectivity check used by the /health endpoint.

    Returns True/False rather than raising, so the API can report a
    degraded status instead of crashing when MongoDB is down.
    """
    if _client is None:
        return False
    try:
        _client.admin.command("ping")
        return True
    except PyMongoError:
        logger.warning("MongoDB health check failed", exc_info=True)
        return False


def _ensure_indexes(database: Database) -> None:
    """
    Create indexes needed by the collections defined in the project spec.

    MongoDB collections and indexes don't need to be created ahead of
    time — a collection is created automatically the first time a
    document is inserted into it. We create indexes explicitly anyway
    because:
      - it documents which fields matter for lookups
      - create_index() is idempotent (safe to call every startup)
      - we want transaction_id to be unique from day one, before any
        real data exists, so duplicates are rejected at the DB level.
    """
    # transactions: looked up by transaction_id constantly, and it
    # must be unique. timestamp is indexed for range/sort queries
    # (e.g. "most recent transactions") added in later phases.
    database["transactions"].create_index([("transaction_id", ASCENDING)], unique=True)
    database["transactions"].create_index([("timestamp", ASCENDING)])

    # predictions / explanations / failed_transactions will be written
    # to by later phases (ML, SHAP, DLQ handling). We index
    # transaction_id now since every document in those collections
    # will be looked up by it.
    database["predictions"].create_index([("transaction_id", ASCENDING)])
    database["explanations"].create_index([("transaction_id", ASCENDING)])
    database["failed_transactions"].create_index([("transaction_id", ASCENDING)])
