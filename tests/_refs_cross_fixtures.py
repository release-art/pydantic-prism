"""A ScopedModel in its own module, the target of the cross-module ref tests."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class CrossTarget(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    label: Annotated[str, scoped(Public)]
