"""Application settings, read from the environment (and an optional .env file).

The sync strategy is deliberately a single-valued literal. Strategy 1 --
asynchronous queued dual-write -- is the only implemented strategy, so there is
no runtime switch to flip. Assigning ``ORDER_SYNC_STRATEGY=polling`` is a
configuration *error* and raises ``ValidationError`` rather than silently
selecting behaviour that does not exist. See docs/RECOVERY_AUDIT.md rulings C1.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: The one and only implemented synchronization strategy.
OrderSyncStrategy = Literal["dual_write"]


class Settings(BaseSettings):
    """Every connection string and switch the application needs."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- synchronization strategy (locked to Strategy 1) --------------------
    order_sync_strategy: OrderSyncStrategy = "dual_write"

    #: The vocabulary `POST /api/orders` reports. A single-valued literal for the
    #: same reason the strategy is: the handler returns before any worker runs, so
    #: it cannot honestly claim the order is indexed. Badge words like IN_SYNC
    #: belong to `GET /api/sync/status/{order_id}` and are impossible here.
    order_sync_placement_status: Literal["QUEUED"] = "QUEUED"

    # --- stores ------------------------------------------------------------
    # Defaults target the native local stack. Override via .env when running
    # the docker-compose services instead (see .env.example).
    pg_dsn: str = "postgresql://ecommerce:ecommerce@127.0.0.1:55432/ecommerce"
    mongo_dsn: str = "mongodb://127.0.0.1:27017"
    mongo_db_name: str = "ecommerce"
    es_url: str = "http://127.0.0.1:9200"
    es_orders_index: str = "orders"
    rabbitmq_url: str = "amqp://guest:guest@127.0.0.1:5672//"

    # --- http --------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # --- seed --------------------------------------------------------------
    # A constant anchor, never `datetime.now()`: "at least 5 orders in the last
    # 7 days" must not silently expire as real time passes, and two seed runs
    # must be byte-reproducible.
    seed_anchor_date: str = "2026-09-30T00:00:00Z"
    seed_default: int = 42

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept `a,b` from .env as well as a JSON array."""
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
