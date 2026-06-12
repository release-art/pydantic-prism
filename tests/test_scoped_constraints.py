"""Per-scope field overrides via ``scoped(..., override=Field(...))``.

A field's *core* validation constraints (``min_length``, ``ge``, ``pattern``, …)
— and any other ``FieldInfo`` attribute — can differ per projection, not just
its JSON-schema annotations. The override merges with the canonical ``Field(...)``
(constraints by kind, ``json_schema_extra`` merged, the rest replaced) and lands
in both the core schema and the JSON schema. ``override=`` also accepts a plain
mapping as a relaxed form.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field, ValidationError

from pydantic_prism import Scope, ScopedModel, scoped


class Body(Scope): ...


class Storage(Scope): ...


class Card(ScopedModel):
    name: Annotated[str, scoped(Body, Storage)]
    image_description: Annotated[
        str,
        scoped(Body, override=Field(min_length=200)),
        scoped(Storage, override={"min_length": 10}),  # relaxed mapping form
        Field(max_length=5000),
    ]


def test_constraint_differs_in_core_schema() -> None:
    """One projection accepts a value the other rejects — real validation."""
    short = "c" * 50
    storage = Card.scope(Storage)(name="x", image_description=short)
    assert storage.image_description == short
    with pytest.raises(ValidationError) as exc:
        Card.scope(Body)(name="x", image_description=short)
    assert exc.value.errors()[0]["type"] == "string_too_short"


def test_constraint_shows_in_json_schema() -> None:
    body = Card.scope(Body).model_json_schema()["properties"]["image_description"]
    storage = Card.scope(Storage).model_json_schema()["properties"]["image_description"]
    assert body["minLength"] == 200
    assert storage["minLength"] == 10
    # the canonical ``max_length`` is shared by both (inherited, not overridden)
    assert body["maxLength"] == storage["maxLength"] == 5000


def test_distinct_overrides_are_distinct_cached_classes() -> None:
    body = Card.scope(Body)
    storage = Card.scope(Storage)
    assert body is not storage
    assert Card.scope(Body) is body  # identity caching still holds


def test_override_replaces_canonical_of_same_kind() -> None:
    """A per-scope bound *overrides* a canonical one of the same kind."""

    class Loose(Scope): ...

    class Tight(Scope): ...

    class M(ScopedModel):
        code: Annotated[
            str,
            scoped(Loose, override=Field(min_length=2)),
            scoped(Tight, override=Field(min_length=8)),
            # canonical min_length is itself overridden per scope; max inherits
            Field(min_length=4, max_length=20),
        ]

    # Loose loosens below the canonical 4; Tight tightens above it.
    assert M.scope(Loose)(code="ab").code == "ab"
    assert M.scope(Tight)(code="abcdefgh").code == "abcdefgh"
    with pytest.raises(ValidationError):
        M.scope(Tight)(code="abcd")
    # the un-overridden canonical max_length survives on both
    for scope in (Loose, Tight):
        assert (
            M.scope(scope).model_json_schema()["properties"]["code"]["maxLength"] == 20
        )


def test_override_requires_single_scope() -> None:
    with pytest.raises(TypeError, match="exactly one scope"):
        scoped(Body, Storage, override=Field(min_length=1))


def test_override_carries_constraint_and_annotation_together() -> None:
    class Only(Scope): ...

    class M(ScopedModel):
        note: Annotated[
            str, scoped(Only, override=Field(min_length=3, description="a note"))
        ]

    schema = M.scope(Only).model_json_schema()["properties"]["note"]
    assert schema["description"] == "a note"
    assert schema["minLength"] == 3


def test_relaxed_mapping_rejects_unknown_kwargs() -> None:
    with pytest.raises(TypeError):
        scoped(Body, override={"not_a_field_kwarg": 1})


def test_override_can_set_a_per_scope_default() -> None:
    """Override spans the whole FieldInfo surface, not just constraints."""

    class Only(Scope): ...

    class M(ScopedModel):
        tier: Annotated[str, scoped(Only, override=Field(default="free"))]

    assert M.scope(Only)().tier == "free"
