"""Money crosses HTTP as a JSON string, and the client never supplies a price.

Two independent guarantees are checked here:

* the money *representation* at the HTTP boundary is a string, so no JavaScript
  float and no `150.5`-vs-`150.50` disagreement can appear between screens;
* the client cannot dictate a price. `OrderCreate` forbids extra keys, so a
  tampered body that includes `unit_price` is a 422 rather than a silently
  trusted number.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.order import (
    OrderCreate,
    OrderDetail,
    OrderItemIn,
    OrderItemOut,
    OrderOut,
    StatusUpdate,
)
from app.models.product import Product, Variant
from app.models.search import SearchHit, SearchRequest, SearchResponse
from app.models.sync import SyncStatusOut
from app.models.user import User


# ---------------------------------------------------------------------------
# Money serialization
# ---------------------------------------------------------------------------


def test_money_serializes_as_string():
    o = OrderOut(
        order_id=1, total_amount=Decimal("150.50"), status="PENDING", sync_status="QUEUED"
    )
    assert o.model_dump(mode="json")["total_amount"] == "150.50"


def test_money_never_serializes_as_a_float():
    """`150.5` in JSON would let a JS client round it. Strings only."""
    o = OrderOut(
        order_id=1, total_amount=Decimal("799.00"), status="PENDING", sync_status="QUEUED"
    )
    assert isinstance(o.model_dump(mode="json")["total_amount"], str)
    assert o.model_dump(mode="json")["total_amount"] == "799.00"


def test_product_price_serializes_as_string():
    p = Product(
        id="64f1a2b3c4d5e6f7a8b9c0d1",
        sku="WM-001",
        title="Wireless Mouse",
        description="Ergonomic 2.4GHz mouse",
        price=Decimal("50.16"),
        category="peripherals",
        tags=["wireless", "usb"],
        attributes={"color": "black", "dpi": 1600},
        variants=[Variant(sku="WM-001-BLK", color="black", stock=40)],
        active=True,
        updated_at="2026-09-25T10:00:00Z",
    )
    assert p.model_dump(mode="json")["price"] == "50.16"


def test_order_item_unit_price_serializes_as_string():
    item = OrderItemOut(product_id="p1", title="Wireless Mouse", quantity=2, unit_price=Decimal("50.16"))
    assert item.model_dump(mode="json")["unit_price"] == "50.16"


def test_search_hit_money_serializes_as_string():
    hit = SearchHit(
        order_id=7,
        status="SHIPPED",
        total_amount=Decimal("150.50"),
        order_date="2026-07-09T19:00:00Z",
        updated_at="2026-07-09T19:05:00Z",
        version=2,
        customer=User(id=5, name="John Doe", email="john.doe@example.com"),
        items=[OrderItemOut(product_id="p1", title="Wireless Mouse", quantity=1, unit_price=Decimal("50.16"))],
    )
    body = hit.model_dump(mode="json")
    assert body["total_amount"] == "150.50"
    assert body["items"][0]["unit_price"] == "50.16"
    assert all(isinstance(v, str) for v in [body["total_amount"], body["items"][0]["unit_price"]])


def test_money_is_quantized_to_two_places():
    """A float sneaks in at an edge; the model still refuses to lose the cent."""
    o = OrderOut(order_id=1, total_amount=Decimal("799.0000000001"), status="PENDING", sync_status="QUEUED")
    assert o.model_dump(mode="json")["total_amount"] == "799.00"


def test_response_money_is_decimal_in_python_and_string_in_json():
    o = OrderOut(order_id=1, total_amount=Decimal("150.50"), status="PENDING", sync_status="QUEUED")
    assert o.total_amount == Decimal("150.50")
    assert o.model_dump()["total_amount"] == Decimal("150.50")
    assert o.model_dump(mode="json")["total_amount"] == "150.50"


# ---------------------------------------------------------------------------
# The client may not set a price
# ---------------------------------------------------------------------------


def test_order_create_rejects_client_price():
    with pytest.raises(ValidationError):
        OrderCreate(user_id=1, items=[{"product_id": "x", "quantity": 1, "unit_price": "0.01"}])


def test_order_create_rejects_client_title():
    with pytest.raises(ValidationError):
        OrderCreate(user_id=1, items=[{"product_id": "x", "quantity": 1, "title": "Free"}])


def test_order_create_rejects_unknown_top_level_keys():
    with pytest.raises(ValidationError):
        OrderCreate(user_id=1, items=[{"product_id": "x", "quantity": 1}], total_amount="0.01")


def test_order_create_accepts_exactly_product_id_and_quantity():
    o = OrderCreate(user_id=1, items=[{"product_id": "x", "quantity": 2}])
    assert o.items == [OrderItemIn(product_id="x", quantity=2)]


def test_quantity_must_be_positive():
    with pytest.raises(ValidationError):
        OrderCreate(user_id=1, items=[{"product_id": "x", "quantity": 0}])


def test_order_needs_at_least_one_item():
    with pytest.raises(ValidationError):
        OrderCreate(user_id=1, items=[])


# ---------------------------------------------------------------------------
# Remaining model contracts
# ---------------------------------------------------------------------------


def test_status_update_constrains_status_to_the_schema_check():
    with pytest.raises(ValidationError):
        StatusUpdate(status="DELIVERED", expected_version=1)
    assert StatusUpdate(status="SHIPPED", expected_version=1).status == "SHIPPED"


def test_status_update_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        StatusUpdate(status="SHIPPED", expected_version=1, version=2)


def test_status_update_requires_a_positive_expected_version():
    with pytest.raises(ValidationError):
        StatusUpdate(status="SHIPPED", expected_version=0)


def test_search_request_defaults_and_bounds():
    r = SearchRequest()
    assert (r.page, r.size) == (1, 20)
    assert r.q is None and r.statuses == []
    with pytest.raises(ValidationError):
        SearchRequest(page=0)
    with pytest.raises(ValidationError):
        SearchRequest(size=0)


def test_search_response_carries_revenue_and_facets():
    body = SearchResponse(total=2, page=1, size=20, revenue=Decimal("301.00"), status_facets={"SHIPPED": 2})
    dumped = body.model_dump(mode="json")
    assert dumped["revenue"] == "301.00"
    assert dumped["status_facets"] == {"SHIPPED": 2}


def test_sync_status_states():
    for state in ("IN_SYNC", "OUT_OF_SYNC", "MISSING_IN_ES"):
        assert SyncStatusOut(order_id=1, state=state, pg_version=2).state == state
    with pytest.raises(ValidationError):
        SyncStatusOut(order_id=1, state="MAYBE", pg_version=2)


def test_order_detail_carries_snapshots():
    d = OrderDetail(
        order_id=7,
        user_id=5,
        user_name="John Doe",
        user_email="john.doe@example.com",
        order_date="2026-07-09T19:00:00Z",
        updated_at="2026-07-09T19:05:00Z",
        status="PENDING",
        total_amount=Decimal("100.32"),
        version=1,
        items=[OrderItemOut(product_id="p1", title="Wireless Mouse", quantity=2, unit_price=Decimal("50.16"))],
    )
    body = d.model_dump(mode="json")
    assert body["items"][0]["title"] == "Wireless Mouse"
    assert body["items"][0]["unit_price"] == "50.16"
    assert body["total_amount"] == "100.32"


def test_no_model_field_is_annotated_as_a_python_float():
    """A float annotation is the classic way money quietly loses a cent."""
    import typing

    from app.models import order as order_models
    from app.models import product as product_models
    from app.models import search as search_models

    offenders: list[str] = []
    for module in (order_models, product_models, search_models):
        for name in dir(module):
            model = getattr(module, name)
            if not isinstance(model, type) or not hasattr(model, "model_fields"):
                continue
            for field_name, field in model.model_fields.items():
                if float in typing.get_args(field.annotation) or field.annotation is float:
                    offenders.append(f"{module.__name__}.{name}.{field_name}")
    assert offenders == []
