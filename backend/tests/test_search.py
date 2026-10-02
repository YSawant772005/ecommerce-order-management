"""Admin search: Elasticsearch only, aggregations over the whole filtered set."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.search import SearchRequest
from app.services import search_service
from tests.conftest import insert_items, insert_order, insert_user


async def _index_all(pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index
    from app.services.sync_service import build_order_document

    await ensure_orders_index()
    oids = await pg_pool.fetch("SELECT id FROM orders ORDER BY id")
    async with pg_pool.acquire() as conn:
        for r in oids:
            doc = await build_order_document(conn, r["id"])
            await es.index(
                index="orders", id=str(r["id"]), document=doc,
                version=doc["version"], version_type="external",
            )
    await es.indices.refresh(index="orders")


async def _fixture(pg_pool):
    wendy = await insert_user(pg_pool, "Wendy Wireless", "wendy.wireless@example.com")
    john = await insert_user(pg_pool, "John Doe", "john.doe@example.com")
    a = await insert_order(
        pg_pool, wendy, "100.32", status="PENDING",
        order_date=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    await insert_items(pg_pool, a, [("p1", "Wireless Mouse", 2, "50.16")])
    b = await insert_order(
        pg_pool, john, "199.00", status="SHIPPED",
        order_date=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    await insert_items(pg_pool, b, [("p2", "Noise Cancelling Headphones", 1, "199.00")])
    return a, b


async def test_partial_customer_name_matches(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest(q="Wendy"))
    assert res.total == 1
    assert res.hits[0].customer.name == "Wendy Wireless"


async def test_partial_title_prefix_matches(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest(q="Wir"))
    assert res.total == 1
    assert res.hits[0].items[0].title == "Wireless Mouse"


async def test_status_filter_shrinks(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest(statuses=["SHIPPED"]))
    assert res.total == 1
    assert res.hits[0].status == "SHIPPED"


async def test_price_filter_shrinks(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest(price_min=Decimal("150.00")))
    assert res.total == 1
    assert res.hits[0].total_amount == Decimal("199.00")


async def test_date_filter_shrinks(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(
        SearchRequest(date_from=datetime(2026, 9, 1, tzinfo=timezone.utc))
    )
    assert res.total == 1


async def test_revenue_agg_spans_all_pages_not_just_hits(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest(size=1))
    assert res.total == 2
    assert len(res.hits) == 1
    assert res.revenue == Decimal("299.32")
    assert res.status_facets == {"PENDING": 1, "SHIPPED": 1}


async def test_revenue_matches_postgres_to_the_cent(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest())
    pg_total = await pg_pool.fetchval("SELECT SUM(total_amount) FROM orders")
    assert res.revenue == Decimal(pg_total).quantize(Decimal("0.01"))


async def test_money_serializes_as_string(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest())
    body = res.model_dump(mode="json")
    assert body["revenue"] == "299.32"
    assert body["hits"][0]["total_amount"] in ("100.32", "199.00")
    assert body["hits"][0]["items"][0]["unit_price"] in ("50.16", "199.00")


async def test_empty_result(pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    res = await search_service.search_orders(SearchRequest(q="qqqzzz"))
    assert res.total == 0 and res.hits == []
    assert res.revenue == Decimal("0.00")


async def test_search_endpoint_uses_service(client, pg_pool, es):
    await _fixture(pg_pool)
    await _index_all(pg_pool, es)
    r = await client.post("/api/search/orders", json={"q": "Wendy"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
