"""
Transaction worker — standalone process entry point.

Run with:
    python -m app.workers.transaction_worker

Why this is a separate process from FastAPI:
FastAPI's job is to serve HTTP requests quickly and return. This
worker's job is to block indefinitely, waiting on RabbitMQ deliveries.
Putting a `channel.start_consuming()` loop inside FastAPI's startup
event would freeze the whole API — no requests could ever be served,
because that call never returns until the process is killed. So they
run as two independent processes, connected only through RabbitMQ and
MongoDB, exactly as required by the "producer must not depend on the
worker" architecture principle.

MongoDB connection handling here:
This worker calls connect_to_mongo() itself, on its own startup,
independently of FastAPI's lifespan — because it's a different OS
process with its own memory space, so it needs its own MongoClient
instance, not FastAPI's.
"""

import logging
import sys

from app.database.mongodb import connect_to_mongo
from app.messaging.consumer import start_consuming
from app.messaging.rabbitmq import create_channel, create_connection
from app.messaging.topology import declare_topology

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Starting NexusGuard transaction worker...")

    connect_to_mongo()

    connection = create_connection()
    channel = create_channel(connection)
    declare_topology(channel)

    try:
        start_consuming(channel)
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user, shutting down...")
    finally:
        if connection.is_open:
            connection.close()
        logger.info("Worker stopped.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Worker crashed on startup")
        sys.exit(1)
