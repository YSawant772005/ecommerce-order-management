"""Catalog repository tests, against the real MongoDB.

These assert the two rules that are easy to break silently:

* money survives a BSON round trip exactly (MongoDB has no decimal type, so this
  is a conversion bug waiting to happen);
* the catalog contains **products and nothing else**. No order, no order item, no
  status, no total is ever written here, and the last test proves it.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from bson import Decimal128
from pydantic import ValidationError
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING

from app.models.product import Product, ProductCreate, ProductUpdate, Variant
from app.repositories.products_repo import (
    COLLECTION,
    DuplicateSku,
    ProductsRepo,
    to_decimal,
    to_decimal128,
)


@pytest.fixture
async def repo():
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27017")
    db = client["ecommerce_test"]
    await db.drop_collection(COLLECTION)
    r = ProductsRepo(db)
    await r.ensure_indexes()
    yield r
    await db.drop_collection(COLLECTION)
    client.close()


def sample(sku="WM-001", price="50.16", title="Wireless Mouse") -> ProductCreate:
    return ProductCreate(
        sku=sku,
        title=title,
        description="Ergonomic 2.4GHz mouse",
        price=price,
        category="peripherals",
        tags=["wireless", "usb"],
        attributes={"color": "black", "dpi": 1600, "battery_hours": 18},
        variants=[Variant(sku=f"{sku}-BLK", color="black", stock=40)],
    )


def sample_with_variant_price() -> ProductCreate:
    return ProductCreate(
        sku="WM-002",
        title="Wireless Mouse",
        description="Ergonomic 2.4GHz mouse",
        price="50.16",
        category="peripherals",
        tags=["wireless"],
        attributes={"color": "black"},
        variants=[Variant(sku="WM-002-BLK", color="black", stock=40, price="44.00")],
    )


# --- money round trip -------------------------------------------------------


async def test_price_survives_bson_round_trip_exactly(repo):
    """Stored as `Decimal128`, surfaced to Python as `Decimal` — never either else."""
    await repo.create(sample(price="50.16"))
    stored = await repo.get_by_sku("WM-001")
    assert isinstance(stored.price, Decimal)
    assert stored.price == Decimal("50.16")
    assert stored.model_dump(mode="json")["price"] == "50.16"


async def test_money_is_stored_as_decimal128_not_double(repo):
    """A double would make 0.1 + 0.2 a different number than PostgreSQL's NUMERIC."""
    await repo.create(sample(price="0.10"))
    raw = await repo._col.find_one({"sku": "WM-001"})
    assert isinstance(raw["price"], Decimal128)
    assert not isinstance(raw["price"], float)
    # The whole point of Decimal128: 0.10 + 0.20 is exactly 0.30, not 0.30000000000000004.
    assert raw["price"].to_decimal() + Decimal("0.20") == Decimal("0.30")


async def test_large_and_small_amounts_survive(repo):
    for price in ("99999999.99", "0.01", "123456789012.34", "0.10", "0.000001"):
        await repo.create(sample(sku=f"SKU-{price}", price=price))
        got = await repo.get_by_sku(f"SKU-{price}")
        assert str(got.price) == price, price


async def test_variant_price_round_trips(repo):
    await repo.create(sample_with_variant_price())
    raw = await repo._col.find_one({"sku": "WM-002"})
    assert isinstance(raw["variants"][0]["price"], Decimal128)
    stored = await repo.get_by_sku("WM-002")
    assert stored.variants[0].price == Decimal("44.00")


async def test_to_decimal_leaves_non_money_attributes_alone():
    """dpi must stay an int. Wrapping every value in Decimal would corrupt it."""
    assert to_decimal(Decimal128("50.16")) == Decimal("50.16")
    assert isinstance(to_decimal(Decimal128("50.16")), Decimal)
    assert to_decimal(1600) == 1600 and isinstance(to_decimal(1600), int)
    assert to_decimal("black") == "black"
    nested = to_decimal({"a": Decimal128("1.50"), "b": {"c": Decimal128("2.50")}, "n": 7})
    assert nested["a"] == Decimal("1.50")
    assert nested["b"]["c"] == Decimal("2.50")
    assert nested["n"] == 7 and isinstance(nested["n"], int)


async def test_to_decimal128_is_exact():
    """`Decimal128` is a wrapper: it converts, it does not compute."""
    assert to_decimal128(Decimal("0.1")).to_decimal() + to_decimal128("0.2").to_decimal() == Decimal("0.3")
    assert to_decimal128("50.16") == Decimal128("50.16")


# --- CRUD -------------------------------------------------------------------


async def test_create_returns_a_full_product(repo):
    product = await repo.create(sample())
    assert isinstance(product, Product)
    assert product.title == "Wireless Mouse"
    assert product.active is True
    assert product.attributes["dpi"] == 1600
    assert product.variants[0].sku == "WM-001-BLK"
    assert product.id


async def test_duplicate_sku_is_rejected(repo):
    await repo.create(sample())
    with pytest.raises(DuplicateSku):
        await repo.create(sample(title="Impostor"))


async def test_get_by_id_and_missing(repo):
    created = await repo.create(sample())
    assert (await repo.get_by_id(created.id)).sku == "WM-001"
    assert await repo.get_by_id("507f1f77bcf86cd799439011") is None
    assert await repo.get_by_id("not-an-oid") is None
    assert await repo.get_by_sku("NOPE") is None


async def test_list_filters_and_counts(repo):
    await repo.create(sample(sku="A-1", title="Alpha", price="10.00"))
    await repo.create(sample(sku="B-2", title="Beta", price="20.00"))
    await repo.create(sample(sku="C-3", title="Gamma", price="30.00"))
    third = await repo.get_by_sku("C-3")
    await repo.update(third.id, ProductUpdate(active=False))

    active, total = await repo.list(active=True)
    assert total == 2
    assert {p.sku for p in active} == {"A-1", "B-2"}

    inactive, total = await repo.list(active=False)
    assert total == 1 and inactive[0].sku == "C-3"

    _, total = await repo.list()
    assert total == 3

    found, total = await repo.list(search="Beta")
    assert total == 1 and found[0].title == "Beta"

    _, total = await repo.list(category="peripherals")
    assert total == 3
    _, total = await repo.list(category="nope")
    assert total == 0

    page, total = await repo.list(skip=0, limit=2)
    assert total == 3 and len(page) == 2


async def test_update_changes_fields_and_bumps_updated_at(repo):
    created = await repo.create(sample())
    updated = await repo.update(created.id, ProductUpdate(price="59.99", title="Mouse v2"))
    assert updated.price == Decimal("59.99")
    assert updated.title == "Mouse v2"
    assert updated.updated_at >= created.updated_at
    assert updated.sku == "WM-001"  # untouched fields survive


async def test_update_leaves_absent_fields_alone(repo):
    created = await repo.create(sample())
    await repo.update(created.id, ProductUpdate(price="1.00"))
    again = await repo.get_by_id(created.id)
    assert again.title == "Wireless Mouse"
    assert again.attributes["dpi"] == 1600
    assert again.variants[0].sku == "WM-001-BLK"


async def test_update_missing_product_returns_none(repo):
    assert await repo.update("507f1f77bcf86cd799439011", ProductUpdate(price="1.00")) is None
    assert await repo.update("not-an-oid", ProductUpdate(price="1.00")) is None


async def test_delete(repo):
    created = await repo.create(sample())
    assert await repo.delete(created.id) is True
    assert await repo.get_by_id(created.id) is None
    assert await repo.delete(created.id) is False


async def test_get_many_by_ids_is_one_lookup(repo):
    a = await repo.create(sample(sku="A-1"))
    b = await repo.create(sample(sku="B-2"))
    found = await repo.get_many_by_ids([a.id, b.id, "not-an-oid"])
    assert set(found) == {a.id, b.id}


# --- the isolation guarantee ------------------------------------------------


async def test_indexes_exist(repo):
    names = {ix["name"]: ix async for ix in repo._col.list_indexes()}
    assert names["sku_unique"]["unique"] is True
    # Motor returns index keys as a SON mapping, not a list of pairs.
    assert list(names["sku_unique"]["key"].items()) == [("sku", ASCENDING)]
    assert list(names["category_active"]["key"].items()) == [
        ("category", ASCENDING),
        ("active", ASCENDING),
    ]
    assert list(names["tags_idx"]["key"].items()) == [("tags", ASCENDING)]


async def test_no_order_data_ever_lands_in_mongo(repo):
    """The catalog holds products. No order may be mirrored here."""
    await repo.create(sample())
    doc = await repo._col.find_one({"sku": "WM-001"})
    for forbidden in ("order_id", "user_id", "status", "total_amount", "quantity", "unit_price"):
        assert forbidden not in doc, f"{forbidden} leaked into the catalog"


async def test_mongo_collections_contain_only_the_catalog(repo):
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27017")
    db = client["ecommerce_test"]
    assert set(await db.list_collection_names()) == {COLLECTION}
    client.close()


async def test_timestamps_are_timezone_aware_utc(repo):
    """BSON returns naive datetimes; the API must not leak them."""
    created = await repo.create(sample())
    assert created.updated_at.tzinfo is not None
    fetched = await repo.get_by_sku("WM-001")
    assert fetched.updated_at.tzinfo is not None
    assert fetched.updated_at.tzinfo.utcoffset(None) == timedelta(0)


async def test_assignment_cannot_bypass_money_validation(repo):
    """`validate_assignment` stops `product.price = "44.00"` leaking a str."""
    from decimal import Decimal as D

    product = await repo.create(sample())
    with pytest.raises(ValidationError):
        product.price = object()
    product.price = "44.00"
    assert product.price == D("44.00")
    assert product.model_dump(mode="json")["price"] == "44.00"


def test_decimal128_is_confined_to_the_repository():
    """Grep-enforceable: only `products_repo` may know MongoDB has no decimal type.

    If a service or API module started importing `Decimal128`, money would acquire
    a second representation outside the one boundary the money rule names.
    """
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app.rglob("*.py"):
        if path.name == "products_repo.py":
            continue
        source = path.read_text()
        # Ignore prose in docstrings/comments; only real imports count.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and "Decimal128" in stripped:
                offenders.append(f"{path.name}: {stripped}")
    assert offenders == []
