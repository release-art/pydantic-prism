"""Classification-tagged models for the data-flow / CLI ``flow`` tests.

A diamond ref graph (``Account`` → ``User`` → ``Org`` and ``Account`` → ``Org``)
so the walk re-reaches ``Org`` — exercising the "already seen" branches — and a
mix of classified (``User``) and unclassified (``Account``, ``Org``) models. In
its own importable module so ``prism flow tests._flow_fixtures:Account`` resolves.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic_prism import Classification, Scope, ScopedModel, ref, scoped


class Public(Scope): ...


class Internal(Public): ...


class Pii(Classification): ...


class Secret(Classification): ...


class Org(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Public), scoped(Pii)]
    secret_note: Annotated[str, scoped(Internal), scoped(Pii), scoped(Secret)]
    org_id: Annotated[UUID, ref(Org), scoped(Internal)]


class Account(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    user_id: Annotated[UUID, ref(User), scoped(Public)]
    org_id: Annotated[UUID, ref(Org), scoped(Public)]


class Bare(ScopedModel):
    """No tagged fields and no refs — its ``data_flow()`` is empty/falsy."""

    x: int
