"""The single Elasticsearch client, and the one definition of the orders index.

Elasticsearch holds a **read projection** of orders for the admin search screen.
It is never the source of truth: every document here is produced by
`sync_service.build_order_document()` from committed PostgreSQL rows, so the
whole index can be deleted and rebuilt from PostgreSQL at any moment.
"""

from __future__ import annotations

import json
from pathlib import Path

from elasticsearch import AsyncElasticsearch

from app.core.settings import get_settings

MAPPING_PATH = Path(__file__).resolve().parents[1] / "search" / "orders_mapping.json"

_client: AsyncElasticsearch | None = None


async def get_es() -> AsyncElasticsearch:
    """Process-wide Elasticsearch client, created on first use."""
    global _client
    if _client is None:
        _client = AsyncElasticsearch(
            get_settings().es_url,
            request_timeout=30,
            retry_on_timeout=True,
            max_retries=3,
        )
    return _client


async def close_es() -> None:
    """Close the client if one was opened. Safe to call when there was none."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def load_orders_index_definition() -> dict:
    """The index settings + mappings, read from the checked-in JSON.

    One file, one mapping. The seed, the reindex script, the FastAPI lifespan
    and the tests all create the index from here, so the document shape cannot
    drift between the path that first indexes and the path that rebuilds.
    """
    return json.loads(MAPPING_PATH.read_text())


async def ensure_orders_index() -> None:
    """Create the `orders` index with its mapping if it does not already exist."""
    es = await get_es()
    index = get_settings().es_orders_index
    if not await es.indices.exists(index=index):
        await es.indices.create(index=index, **load_orders_index_definition())
