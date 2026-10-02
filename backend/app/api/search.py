"""Admin search route. Elasticsearch only."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.search import SearchRequest, SearchResponse
from app.services import search_service

router = APIRouter()


@router.post("/search/orders", response_model=SearchResponse)
async def search_orders(req: SearchRequest) -> SearchResponse:
    return await search_service.search_orders(req)
