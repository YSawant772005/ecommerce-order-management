"""Product catalog models — the MongoDB document, as the API exposes it.

`price` is a plain Python `Decimal` here. BSON `Decimal128` is a *wire* type, not
a Pydantic type, so it appears only in `repositories/products_repo.py`: the model
stays storage-agnostic and the same class serves the HTTP layer and the catalog
layer. `attributes` is a free-form object and `variants` is an array of
sub-documents, which is the whole reason this catalog lives in MongoDB.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models._money import Money


class Variant(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True)

    sku: str
    color: str | None = None
    stock: int = Field(default=0, ge=0)
    price: Money | None = None


class Product(BaseModel):
    """A catalog document. `id` is the MongoDB ObjectId as a string."""

    # `validate_assignment` closes the hole where `product.price = "44.00"`
    # after construction would leave a str in a Decimal field, which then
    # serializes wrong and breaks the money guarantee.
    model_config = ConfigDict(populate_by_name=True, extra="ignore", validate_assignment=True)

    id: str = Field(alias="_id")
    sku: str
    title: str
    description: str
    price: Money
    category: str
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    variants: list[Variant] = Field(default_factory=list)
    active: bool = True
    updated_at: datetime


class ProductCreate(BaseModel):
    """Screen 5 create. Validated here so the catalog cannot hold a bad document."""

    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    price: Money
    category: str = Field(min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    variants: list[Variant] = Field(default_factory=list)
    active: bool = True

    @model_validator(mode="after")
    def _require_document_shape(self) -> ProductCreate:
        # A catalog entry with no variants or no attributes would not exercise the
        # document-oriented part of MongoDB that Screen 5 exists to demonstrate.
        if not self.variants:
            raise ValueError("a product must have at least one variant")
        if not self.attributes:
            raise ValueError("a product must have at least one attribute")
        return self


class ProductUpdate(BaseModel):
    """Screen 5 edit. Same validation as create; every field is optional."""

    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    price: Money | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    tags: list[str] | None = None
    attributes: dict[str, Any] | None = None
    variants: list[Variant] | None = None
    active: bool | None = None
