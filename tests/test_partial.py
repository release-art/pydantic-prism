"""Partial scopes: the all-fields-optional Update projection (MISSING sentinel)."""

from typing import Annotated, Optional
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pydantic_prism import (
    MISSING,
    Classification,
    Scope,
    ScopedModel,
    scoped,
)


class Public(Scope): ...


class Storage(Public): ...


class Update(Storage, partial=True): ...


class Row(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    status: Annotated[str, scoped(Storage)] = "active"
    secret: Annotated[str, scoped(Storage - Public)]


def test_partial_projection_validates_empty_input() -> None:
    update = Row.scope(Update)()
    # absent fields read as the MISSING sentinel (not None)
    assert update.id is MISSING  # type: ignore[attr-defined]
    assert update.name is MISSING  # type: ignore[attr-defined]


def test_canonical_defaults_are_dropped() -> None:
    """PATCH semantics: absent means "don't touch", not "write the default"."""
    update = Row.scope(Update)()
    assert update.status is MISSING  # type: ignore[attr-defined]
    # MISSING fields are omitted from a plain dump — no exclude_none needed
    assert update.model_dump() == {}


def test_partial_fields_still_validate_values() -> None:
    update = Row.scope(Update)(name="ada")
    assert update.name == "ada"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        Row.scope(Update)(id="not-a-uuid")


def test_json_schema_reflects_optionality() -> None:
    schema = Row.scope(Update).model_json_schema()
    assert "required" not in schema  # nothing required
    id_schema = schema["properties"]["id"]
    # a required canonical field stays NON-nullable in the partial projection
    assert "anyOf" not in id_schema
    assert id_schema["type"] == "string"
    assert "default" not in id_schema  # MISSING is not a JSON default


def test_partial_preserves_canonical_nullability() -> None:
    class Account(ScopedModel):
        name: Annotated[str, scoped(Public)]  # required -> not nullable
        nickname: Annotated[Optional[str], scoped(Public)] = None  # nullable

    patch = Account.scope(Update)
    # required field: null rejected, absent fine
    with pytest.raises(ValidationError):
        patch(name=None)
    assert patch().name is MISSING  # type: ignore[attr-defined]
    # nullable field: null is a distinct, dumpable value; absent is omitted
    assert patch(nickname=None).model_dump() == {"nickname": None}
    assert patch(name="x").model_dump() == {"name": "x"}  # nickname absent


def test_from_canonical_round_trip() -> None:
    row = Row(id=uuid4(), name="ada", secret="s")
    update = Row.scope(Update).from_canonical(row)
    assert update.name == "ada"  # type: ignore[attr-defined]
    assert update.status == "active"  # type: ignore[attr-defined]
    # sparse output: only what differs from "absent"
    sparse_cls = Row.scope(Update)
    assert sparse_cls(name="new").model_dump(exclude_none=True) == {"name": "new"}


def test_mixed_expression_is_not_partial() -> None:
    """Conservative rule: every atom must be partial."""
    projected = Row.scope(Update | Public, name="RowUpdateOrPublic")
    with pytest.raises(ValidationError):
        projected()


def test_partial_flag_inherits_and_can_be_redeclared() -> None:
    class DeepUpdate(Update): ...

    class Restored(Update, partial=False): ...

    assert Row.scope(DeepUpdate, name="RowDeepUpdate")() is not None
    with pytest.raises(ValidationError):
        Row.scope(Restored, name="RowRestored")()


def test_partial_union_of_partials_is_partial() -> None:
    class OtherUpdate(Storage, partial=True): ...

    projected = Row.scope(Update | OtherUpdate, name="RowEitherUpdate")
    assert projected() is not None


def test_partial_survives_classification_subtraction() -> None:
    """A partial scope minus a classification stays a sparse PATCH model.

    Regression: ``is_partial`` once conjoined *all* atoms, so the non-partial
    classification on the subtracted side flipped the projection back to a
    required shape — silently breaking redacted sparse-update models.
    """

    class Pii(Classification): ...

    class Account(ScopedModel):
        account_id: Annotated[int, scoped(Storage)]
        email: Annotated[str, scoped(Storage), scoped(Pii)]

    assert (Update - Pii).is_partial()
    sparse = Account.scope(Update - Pii)
    assert sparse().account_id is MISSING  # type: ignore[attr-defined]
    assert "required" not in sparse.model_json_schema()

    # redacted() builds the very same difference under the hood
    redacted = Account.redacted(Update)
    assert redacted().account_id is MISSING  # type: ignore[attr-defined]
    assert "required" not in redacted.model_json_schema()


def test_complement_projection_is_never_partial() -> None:
    """A complement carries no positive scope, so it never forces optionality."""
    assert not (~Update).is_partial()


def test_partial_propagates_into_nested_models() -> None:
    class Inner(ScopedModel):
        label: Annotated[str, scoped(Public)]

    class Outer(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        inner: Annotated[Inner, scoped(Public)]

    projected = Outer.scope(Update)
    instance = projected(inner={})
    assert instance.inner.label is MISSING  # type: ignore[attr-defined]
    assert projected().inner is MISSING  # type: ignore[attr-defined]  # inner optional too
