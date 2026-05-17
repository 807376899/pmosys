from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


T = TypeVar("T")


class PagedResponse(APIModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

