"""Scoped models scanned by the codegen tests, in their own importable module.

Kept separate from ``test_codegen`` so module-scan discovery sees a clean,
fixed set of models (and so the generated stubs' runtime imports resolve).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from pydantic_prism import Scope, ScopedModel, scoped


class Ref(Scope): ...


class Public(Ref): ...


class Storage(Public): ...


class Update(Storage, partial=True): ...


class CarrierBase(BaseModel):
    def carrier(self) -> str:
        return type(self).__name__


class Tag(ScopedModel, default_scope=Public):
    id: Annotated[UUID, scoped(Ref)] = Field(default_factory=uuid4)
    label: str


class Screenshot(
    CarrierBase,
    ScopedModel,
    default_scope=Storage,
    projection_bases=(CarrierBase,),
):
    id: Annotated[UUID, scoped(Ref)] = Field(default_factory=uuid4)
    timestamp: Annotated[datetime, scoped(Ref)]
    website_id: Annotated[UUID, scoped(Public)]
    container_name: str
    count: Annotated[int, scoped(Public)] = 0
    items: Annotated[list[str], scoped(Public)] = Field(default_factory=list)
    tags: Annotated[list[Tag], scoped(Public)] = []
