"""Store clients and the Elasticsearch `orders` index definition.

Two of these assertions are money boundaries and two are mapping decisions that
are expensive to get wrong later:

* money is BSON `Decimal128` on the MongoDB side and `scaled_float(100)` on the
  Elasticsearch side -- never a float and never a string;
* `items` is `object`, not `nested`. Both expose a `properties` key, so the
  discriminator is asserted explicitly rather than inferred from key presence.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128

from app.core.elasticsearch import ensure_orders_index, get_es
from app.core.settings import get_settings


@pytest.fixture
async def mapping(es):
    await ensure_orders_index()
    return (await es.indices.get_mapping(index="orders"))["orders"]["mappings"]["properties"]


async def test_ensure_orders_index_creates_index_with_scaling(es):
    await ensure_orders_index()
    props = (await es.indices.get_mapping(index="orders"))["orders"]["mappings"]["properties"]
    assert props["total_amount"]["type"] == "scaled_float"
    assert props["total_amount"]["scaling_factor"] == 100
    assert props["items"]["properties"]["unit_price"]["scaling_factor"] == 100
    assert props["status"]["type"] == "keyword"


async def test_items_is_object_not_nested(es):
    await ensure_orders_index()
    props = (await es.indices.get_mapping(index="orders"))["orders"]["mappings"]["properties"]
    # Elasticsearch normalises away `"type": "object"` because object is the
    # default, so its ABSENCE is what proves the field is an object. A `nested`
    # field would report "type": "nested" explicitly.
    assert props["items"].get("type", "object") == "object"
    assert "nested" not in props["items"]


async def test_prefix_subfields_present(es):
    await ensure_orders_index()
    props = (await es.indices.get_mapping(index="orders"))["orders"]["mappings"]["properties"]
    assert {"prefix"} <= set(props["customer"]["properties"]["name"]["fields"])
    assert {"prefix"} <= set(props["items"]["properties"]["title"]["fields"])


async def test_spec_field_types(mapping):
    """Every field in spec §9, with the type the assignment pins for it."""
    assert mapping["order_id"]["type"] == "long"
    assert mapping["order_date"]["type"] == "date"
    assert mapping["updated_at"]["type"] == "date"
    assert mapping["version"]["type"] == "integer"
    assert mapping["customer"]["properties"]["id"]["type"] == "long"
    assert mapping["customer"]["properties"]["email"]["type"] == "keyword"
    assert mapping["items"]["properties"]["product_id"]["type"] == "keyword"
    assert mapping["items"]["properties"]["quantity"]["type"] == "integer"
    assert mapping["customer"]["properties"]["name"]["type"] == "text"
    assert mapping["customer"]["properties"]["name"]["fields"]["keyword"]["type"] == "keyword"
    assert mapping["items"]["properties"]["title"]["type"] == "text"
    assert mapping["items"]["properties"]["title"]["fields"]["keyword"]["type"] == "keyword"


async def test_index_settings(es):
    await ensure_orders_index()
    settings = (await es.indices.get_settings(index="orders"))["orders"]["settings"]["index"]
    assert settings["number_of_shards"] == "1"
    assert settings["number_of_replicas"] == "0"
    assert settings["refresh_interval"] == "1s"


async def test_autocomplete_analyzer_is_edge_ngram(es):
    """Partial typing ('Wir' -> 'Wireless') needs index-time n-grams.

    A standard analyzer stores whole tokens only, so no query-time option can
    recover the missing prefixes after the fact.
    """
    await ensure_orders_index()
    analysis = (await es.indices.get_settings(index="orders"))["orders"]["settings"]["index"][
        "analysis"
    ]
    assert "autocomplete_index" in analysis["analyzer"]
    filter_def = analysis["analyzer"]["autocomplete_index"]["filter"]
    gram = analysis["filter"][filter_def[-1]]
    assert gram["type"] == "edge_ngram"
    # Elasticsearch returns analysis settings as strings.
    assert int(gram["min_gram"]) == 2
    assert int(gram["max_gram"]) == 15


async def test_ensure_orders_index_is_idempotent(es):
    await ensure_orders_index()
    await ensure_orders_index()
    assert await es.indices.exists(index="orders")


# ---------------------------------------------------------------------------
# Money boundaries
# ---------------------------------------------------------------------------


async def test_product_price_roundtrips_as_decimal128(mongo_db):
    await mongo_db.products.insert_one({"title": "Mouse", "price": Decimal128("50.16")})
    got = await mongo_db.products.find_one({"title": "Mouse"})
    assert isinstance(got["price"], Decimal128)
    assert got["price"].to_decimal() == Decimal("50.16")


@pytest.mark.parametrize("raw", ["0.01", "19.99", "1234.56", "99999999.99"])
async def test_es_scaled_float_preserves_cents(es, raw):
    await ensure_orders_index()
    await es.index(
        index="orders",
        id="1",
        document={"total_amount": float(Decimal(raw)), "version": 1, "order_id": 1},
    )
    await es.indices.refresh(index="orders")
    src = (await es.search(index="orders", size=1))["hits"]["hits"][0]["_source"]
    assert Decimal(str(src["total_amount"])).quantize(Decimal("0.01")) == Decimal(raw)


async def test_clients_are_singletons():
    assert await get_es() is await get_es()
    assert get_settings().es_orders_index == "orders"
