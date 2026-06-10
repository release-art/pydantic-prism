"""Partial scopes: the all-fields-optional Update projection."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pydantic_prism import Scope, ScopedModel, scoped


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
    assert update.id is None  # type: ignore[attr-defined]
    assert update.name is None  # type: ignore[attr-defined]


def test_canonical_defaults_are_dropped() -> None:
    """PATCH semantics: absent means "don't touch", not "write the default"."""
    update = Row.scope(Update)()
    assert update.status is None  # type: ignore[attr-defined]
    sparse = update.model_dump(exclude_none=True)
    assert sparse == {}


def test_partial_fields_still_validate_values() -> None:
    update = Row.scope(Update)(name="ada")
    assert update.name == "ada"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        Row.scope(Update)(id="not-a-uuid")


def test_json_schema_reflects_optionality() -> None:
    schema = Row.scope(Update).model_json_schema()
    assert "required" not in schema
    id_schema = schema["properties"]["id"]
    assert {"type": "null"} in id_schema["anyOf"]
    assert id_schema["default"] is None


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


def test_partial_propagates_into_nested_models() -> None:
    class Inner(ScopedModel):
        label: Annotated[str, scoped(Public)]

    class Outer(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        inner: Annotated[Inner, scoped(Public)]

    projected = Outer.scope(Update)
    instance = projected(inner={})
    assert instance.inner.label is None  # type: ignore[attr-defined]
    assert projected() is not None  # inner itself is optional too
