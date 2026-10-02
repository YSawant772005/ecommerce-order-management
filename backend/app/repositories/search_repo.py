"""Elasticsearch-only order search. No PG/Mongo import lives here."""

from __future__ import annotations

from decimal import Decimal

from app.core.elasticsearch import get_es
from app.core.settings import get_settings
from app.models._money import quantize
from app.models.search import SearchHit, SearchRequest, SearchResponse


def _money(value: object) -> Decimal:
    return quantize(Decimal(str(value)))


async def search_orders(req: SearchRequest) -> SearchResponse:
    """`multi_match` omni-search plus `terms`/`range` filters.

    Aggregations are siblings of `size`: revenue and facets always cover the
    whole filtered set, never just the returned page.
    """
    es = await get_es()
    must: list[dict] = []
    if req.q:
        must.append(
            {
                "multi_match": {
                    "query": req.q,
                    "fields": [
                        "customer.name^2",
                        "items.title.prefix",
                        "items.title",
                        "customer.email",
                    ],
                }
            }
        )
    else:
        must.append({"match_all": {}})
    filters: list[dict] = []
    if req.statuses:
        filters.append({"terms": {"status": req.statuses}})
    if req.date_from or req.date_to:
        bounds: dict[str, str] = {}
        if req.date_from:
            bounds["gte"] = req.date_from.isoformat()
        if req.date_to:
            bounds["lte"] = req.date_to.isoformat()
        filters.append({"range": {"order_date": bounds}})
    if req.price_min is not None or req.price_max is not None:
        bounds_n: dict[str, str] = {}
        if req.price_min is not None:
            bounds_n["gte"] = format(quantize(req.price_min), "f")
        if req.price_max is not None:
            bounds_n["lte"] = format(quantize(req.price_max), "f")
        filters.append({"range": {"total_amount": bounds_n}})

    body = {
        "query": {"bool": {"must": must, "filter": filters}},
        "aggs": {
            "orders_revenue": {"sum": {"field": "total_amount"}},
            "orders_by_status": {"terms": {"field": "status"}},
        },
        "from": (req.page - 1) * req.size,
        "size": req.size,
        "sort": [{"order_date": "desc"}],
    }
    res = await es.search(index=get_settings().es_orders_index, **body)
    hits = [
        SearchHit(
            order_id=h["_source"]["order_id"],
            status=h["_source"]["status"],
            total_amount=_money(h["_source"]["total_amount"]),
            order_date=h["_source"]["order_date"],
            updated_at=h["_source"]["updated_at"],
            version=h["_source"]["version"],
            customer=h["_source"]["customer"],
            items=[
                {
                    "product_id": i["product_id"],
                    "title": i["title"],
                    "quantity": i["quantity"],
                    "unit_price": _money(i["unit_price"]),
                }
                for i in h["_source"]["items"]
            ],
        )
        for h in res["hits"]["hits"]
    ]
    revenue_raw = (res.get("aggregations") or {}).get("orders_revenue", {}).get("value")
    facets = {
        b["key"]: b["doc_count"]
        for b in (res.get("aggregations") or {}).get("orders_by_status", {}).get("buckets", [])
    }
    return SearchResponse(
        total=res["hits"]["total"]["value"],
        page=req.page,
        size=req.size,
        revenue=_money(revenue_raw or 0),
        status_facets=facets,
        hits=hits,
    )
