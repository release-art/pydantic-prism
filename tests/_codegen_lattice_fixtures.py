"""Fixtures for the round-25 codegen tests: a scope chain, copied behaviors,
and a callable ``default_factory``. Kept out of the module-scanned fixtures so it
is reached only through explicit projections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from pydantic_prism import Scope, ScopedModel, scoped, unprojected

if TYPE_CHECKING:
    # Imported only at type-check time, so it is absent from this module's
    # runtime globals — a signature annotation referencing it cannot be resolved
    # by codegen, exercising the untyped-fallback path.
    from tests._refs_cross_fixtures import CrossTarget


class A(Scope): ...


class B(A): ...


class C(B): ...


class Hashes(BaseModel):
    sha: str = ""


class Card(ScopedModel, default_scope=C):
    """A card row with a three-rung scope chain and copied behaviors."""

    id: Annotated[UUID, scoped(A)] = Field(default_factory=uuid4)
    title: Annotated[str, scoped(A)]
    angles: Annotated[int, scoped(B)] = 0
    body: Annotated[str, scoped(C)] = ""
    hashes: Annotated[Hashes, scoped(A), Field(default_factory=Hashes)]

    @property
    def is_quarantined(self) -> bool:
        return self.title == ""

    @classmethod
    def blank(cls, title: str) -> Self:
        return cls(title=title)

    @staticmethod
    def kind() -> str:
        return "card"

    def summary(self, *args: str, verbose: bool = False, **opts: object) -> str:
        return self.title

    def labelled(self, *, tag: str = "x") -> str:
        return f"{tag}:{self.title}"

    @unprojected
    def internal_only(self) -> int:
        return 1


class Retyped(ScopedModel):
    """A field whose type diverges per scope (``as_type=``), so the narrower face
    is *not* a sound subclass of the wider one."""

    id: Annotated[UUID, scoped(A)] = Field(default_factory=uuid4)
    code: Annotated[int, scoped(A), scoped(B, as_type=str)]
    extra: Annotated[str, scoped(B)] = ""


class Unresolvable(ScopedModel):
    id: Annotated[UUID, scoped(A)] = Field(default_factory=uuid4)

    def linked(self, other: CrossTarget) -> None:
        """A method whose annotation codegen cannot resolve at gen time."""
