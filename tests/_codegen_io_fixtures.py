"""A model with read/write-only fields, for the ``.input()`` / ``.output()``
codegen tests.

Kept out of ``_codegen_fixtures`` (which is module-scanned) on purpose: scanning
a model whose fields carry ``In`` / ``Out`` direction tags would emit bare
``.scope(In)`` / ``.scope(Out)`` projections. These models are reached only
through explicit ``[[tool.pydantic-prism.projections]]`` entries.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from pydantic_prism import In, Out, Scope, ScopedModel, scoped


class Public(Scope): ...


class Account(ScopedModel, default_scope=Public):
    """A user account row."""

    id: Annotated[UUID, scoped(Public, Out)] = Field(default_factory=uuid4)
    handle: Annotated[str, scoped(Public)]
    password: Annotated[str, scoped(Public, In)] = ""
