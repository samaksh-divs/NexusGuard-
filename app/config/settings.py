"""
Centralized application configuration.

Why this file exists:
Instead of scattering `os.getenv(...)` calls everywhere, we define one
Settings object that reads from environment variables / the .env file.
Every other module imports `settings` from here.

In Phase 1 we only need application-level settings. MongoDB and
RabbitMQ settings will be added in later phases, but we define the
fields now so the file doesn't need to be restructured later.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Application ---
    app_name: str = "NexusGuard"
    app_env: str = "development"
    app_debug: bool = True

    # --- MongoDB (Phase 2) ---
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "nexusguard"

    # --- RabbitMQ (Phase 3) ---
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"

    rabbitmq_exchange: str = "transaction_exchange"
    rabbitmq_queue: str = "transaction_queue"
    rabbitmq_routing_key: str = "transaction.new"

    # --- RabbitMQ Dead Letter Queue (Phase 4) ---
    rabbitmq_dlx: str = "transaction_dlx"
    rabbitmq_dlq: str = "transaction_dlq"
    rabbitmq_dlq_routing_key: str = "transaction.failed"

    # How many unacknowledged messages a single consumer may hold at
    # once. Kept configurable rather than hard-coded in consumer.py.
    rabbitmq_prefetch_count: int = 1

    # --- Fraud Detection Engine (Phase 5) ---
    # Thresholds are configurable so tuning doesn't require code
    # changes. Defaults are sensible for local development/testing
    # with typical crypto price/quantity ranges.
    fraud_high_value_threshold: float = 50000.0
    fraud_very_high_value_threshold: float = 150000.0
    fraud_high_quantity_threshold: float = 5.0

    # Comma-separated list of symbols treated as suspicious, e.g.
    # "SCAMCOIN,RUGPULL". Empty by default — no symbol is inherently
    # flagged; this just demonstrates the mechanism. Parsed via
    # suspicious_symbols_set below.
    fraud_suspicious_symbols: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore vars in .env not yet used (e.g. future Mongo/RabbitMQ keys)
    )

    @property
    def suspicious_symbols_set(self) -> set[str]:
        """
        Parse FRAUD_SUSPICIOUS_SYMBOLS ("BTC,ETH" style) into an
        uppercase set for case-insensitive lookups. A computed
        property (not a stored field) so the raw env var stays a
        plain string in .env, easy to edit by hand.
        """
        return {
            symbol.strip().upper()
            for symbol in self.fraud_suspicious_symbols.split(",")
            if symbol.strip()
        }


# Single shared settings instance, imported everywhere else.
settings = Settings()
