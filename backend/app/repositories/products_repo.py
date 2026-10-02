"""The catalog repository — the only place BSON `Decimal128` exists.

MongoDB has no decimal type, so the catalog's money is stored as `Decimal128`
inside a BSON sub-document. `products_repo` converts at the boundary and nothing
else in the codebase is allowed to import `bson` or `Decimal128`. That is what
keeps the money rule enforceable by grep rather than by convention.

The same documents are also what `order_service` reads to price a cart. That
lookup is the only MongoDB read on the order path, and it returns snapshots
which are then copied into PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import Decimal128, ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.models.product import Product, ProductCreate, ProductUpdate

COLLECTION = "products"

#: Money stored in MongoDB is wrapped, so it can never be indexed or compared as
#: a double by an unrelated tool reading the collection directly.
SIX_PLACES = Decimal128("0.000001")


def to_decimal128(value) -> Decimal128:
    """Python `Decimal` (or int/str/float) -> BSON `Decimal128`, exact."""
    from decimal import Decimal

    return Decimal128(Decimal(str(value)))


def to_decimal(value: Any) -> Any:
    """BSON `Decimal128` -> Python `Decimal`. Any other value passes through.

    Non-decimal leaves matter: `attributes.dpi` is an int, and turning it into a
    `Decimal` would corrupt the catalog for any client that reads attributes back.
    """
    from decimal import Decimal

    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, dict):
        return {k: to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_decimal(v) for v in value]
    return value


def _as_utc(value: Any) -> Any:
    """BSON hands back naive datetimes; the rest of the app uses aware ones.

    Comparing a naive BSON datetime with an aware one raises `TypeError`, and
    FastAPI would emit a `Z`-less string. Everything leaving this module is
    timezone-aware UTC.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _to_product(doc: dict[str, Any]) -> Product:
    """BSON document -> `Product`, with `_id` stringified and money unwrapped."""
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    doc["price"] = to_decimal(doc.get("price"))
    for variant in doc.get("variants") or []:
        if variant.get("price") is not None:
            variant["price"] = to_decimal(variant["price"])
    if doc.get("attributes"):
        doc["attributes"] = to_decimal(doc["attributes"])
    doc["updated_at"] = _as_utc(doc.get("updated_at"))
    return Product.model_validate(doc)


def _to_document(product: ProductCreate | ProductUpdate) -> dict[str, Any]:
    """Validated model -> BSON document. Only non-`None` fields are written."""
    doc: dict[str, Any] = {}
    for name, value in product.model_dump(exclude_none=True).items():
        if name == "price":
            doc[name] = to_decimal128(value)
        elif name == "variants":
            doc[name] = [
                {
                    k: (to_decimal128(v) if k == "price" and v is not None else v)
                    for k, v in variant.items()
                }
                for variant in value
            ]
        else:
            doc[name] = value
    return doc


def _is_oid(value: str) -> bool:
    return ObjectId.is_valid(value)


class ProductNotFound(Exception):
    """Raised when a product id or sku does not resolve."""


class DuplicateSku(Exception):
    """Raised when a create would violate the unique `sku` index."""


class ProductsRepo:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self._col = db[COLLECTION]

    # -- indexes ------------------------------------------------------------

    async def ensure_indexes(self) -> None:
        """The three catalog indexes from the spec.

        `sku` is unique because it is the business key a human uses; the
        compound index serves the Screen 5 filter; `tags` is a multikey index for
        tag lookups.
        """
        await self._col.create_index("sku", unique=True, name="sku_unique")
        await self._col.create_index(
            [("category", 1), ("active", 1)], name="category_active"
        )
        await self._col.create_index("tags", name="tags_idx")

    # -- reads --------------------------------------------------------------

    async def list(
        self,
        *,
        search: str | None = None,
        category: str | None = None,
        active: bool | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Product], int]:
        """Filtered page plus the total match count (Screen 5, MongoDB only)."""
        query: dict[str, Any] = {}
        if search:
            # `search` is a free-text hint, not the admin Search screen. Screen 3
            # searches Elasticsearch; this is a plain catalog listing.
            query["$or"] = [
                {"title": {"$regex": search, "$options": "i"}},
                {"sku": {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
            ]
        if category:
            query["category"] = category
        if active is not None:
            query["active"] = active

        total = await self._col.count_documents(query)
        cursor = self._col.find(query).sort("title", 1).skip(skip).limit(limit)
        return [_to_product(doc) async for doc in cursor], total

    async def get_by_id(self, product_id: str) -> Product | None:
        if not _is_oid(product_id):
            return None
        return await self._get(self._col.find_one({"_id": ObjectId(product_id)}))

    async def get_by_sku(self, sku: str) -> Product | None:
        return await self._get(self._col.find_one({"sku": sku}))

    async def get_many_by_ids(self, product_ids: list[str]) -> dict[str, Product]:
        """Batch lookup for cart pricing.

        One query, not one query per cart line. A 3-line cart is a single round
        trip, which is the only way checkout latency stays independent of cart
        size.
        """
        oids = [ObjectId(pid) for pid in product_ids if _is_oid(pid)]
        if not oids:
            return {}
        found = {}
        async for doc in self._col.find({"_id": {"$in": oids}}):
            product = _to_product(doc)
            found[product.id] = product
        return found

    async def _get(self, cursor) -> Product | None:
        doc = await cursor
        return _to_product(doc) if doc else None

    # -- writes -------------------------------------------------------------

    async def create(self, product: ProductCreate) -> Product:
        doc = _to_document(product)
        doc["updated_at"] = datetime.now(timezone.utc)
        try:
            result = await self._col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateSku(f"sku already exists: {product.sku}") from exc
        doc["_id"] = result.inserted_id
        return _to_product(doc)

    async def update(self, product_id: str, product: ProductUpdate) -> Product | None:
        changes = _to_document(product)
        changes["updated_at"] = datetime.now(timezone.utc)
        if not _is_oid(product_id):
            return None
        try:
            doc = await self._col.find_one_and_update(
                {"_id": ObjectId(product_id)},
                {"$set": changes},
                return_document=True,
            )
        except DuplicateKeyError as exc:
            raise DuplicateSku("sku already exists") from exc
        return _to_product(doc) if doc else None

    async def delete(self, product_id: str) -> bool:
        if not _is_oid(product_id):
            return False
        result = await self._col.delete_one({"_id": ObjectId(product_id)})
        return result.deleted_count == 1
