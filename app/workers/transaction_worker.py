"""
NexusGuard Transaction Worker

Standalone RabbitMQ worker process.

Run:

    python -m app.workers.transaction_worker
"""

import logging
import sys

from app.database.mongodb import connect_to_mongo
from app.messaging.rabbitmq import (
    create_channel,
    create_connection,
)
from app.messaging.topology import declare_topology
from app.messaging.consumer import start_consuming


# ================================================================
# LOGGING
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


# ================================================================
# MAIN
# ================================================================

def main() -> None:

    logger.info(
        "Starting NexusGuard transaction worker..."
    )

    # ------------------------------------------------------------
    # MONGODB
    # ------------------------------------------------------------

    connect_to_mongo()

    # ------------------------------------------------------------
    # RABBITMQ CONNECTION
    # ------------------------------------------------------------

    connection = create_connection()

    logger.info(
        "RabbitMQ worker connection established."
    )

    # ------------------------------------------------------------
    # CHANNEL
    # ------------------------------------------------------------

    channel = create_channel(
        connection
    )

    # ------------------------------------------------------------
    # TOPOLOGY
    # ------------------------------------------------------------

    declare_topology(
        channel
    )

    logger.info(
        "RabbitMQ topology initialized."
    )

    # ------------------------------------------------------------
    # START CONSUMER
    # ------------------------------------------------------------

    try:

        start_consuming(
            channel
        )

    except KeyboardInterrupt:

        logger.info(
            "Worker interrupted by user, shutting down..."
        )

    finally:

        try:

            if connection.is_open:

                connection.close()

        except Exception:

            logger.exception(
                "Error while closing RabbitMQ connection."
            )

        logger.info(
            "NexusGuard transaction worker stopped."
        )


# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":

    try:

        main()

    except Exception:

        logger.exception(
            "Worker crashed on startup."
        )

        sys.exit(1)