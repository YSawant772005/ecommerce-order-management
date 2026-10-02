"""Screen 3 orchestration. Elasticsearch only: no PG/Mongo repository here."""

from __future__ import annotations

from app.models.search import SearchRequest, SearchResponse
from app.repositories import search_repo


async def search_orders(req: SearchRequest) -> SearchResponse:
    return await search_repo.search_orders(req)
