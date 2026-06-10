"""ScopedModel.with_updates: apply a partial projection as a PATCH."""

from typing import Annotated, Optional

import pytest
from pydantic import Field

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


class Update(Storage, partial=True): ...


class Inner(ScopedModel):
    label: Annotated[str, scoped(Public)]


class Row(ScopedModel):
    name: Annotated[str, scoped(Public)]
    note: Annotated[Optional[str], scoped(Public)] = "default"  # noqa: UP045
    count: Annotated[int, scoped(Storage)] = 0
    inner: Annotated[Inner, scoped(Public)]


def _row() -> Row:
    return Row(name="a", note="hi", count=1, inner=Inner(label="x"))


# --- core behavior ----------------------------------------------------------


def test_applies_only_set_fields() -> None:
    patched = _row().with_updates(Row.scope(Update)(name="b"))
    assert patched.name == "b"
    assert patched.note == "hi"  # untouched
    assert patched.count == 1  # untouched (different scope, not set)


def test_returns_new_instance_leaves_self_unchanged() -> None:
    original = _row()
    patched = original.with_updates(Row.scope(Update)(name="b"))
    assert patched is not original
    assert original.name == "a"


def test_revalidates_and_reconstructs_nested_models() -> None:
    patch = Row.scope(Update)(inner=Inner.scope(Update)(label="y"))
    patched = _row().with_updates(patch)
    assert isinstance(patched.inner, Inner)  # not a raw dict
    assert patched.inner.label == "y"
    assert patched.name == "a"


def test_explicit_none_clears_optional_field() -> None:
    patched = _row().with_updates(Row.scope(Update)(note=None))
    assert patched.note is None  # explicitly set None IS an update


def test_unset_does_not_write_back_defaults() -> None:
    # note defaults to "default" on the partial, but isn't *set* -> not applied.
    patched = _row().with_updates(Row.scope(Update)(name="b"))
    assert patched.note == "hi"  # the canonical's current value survives


def test_empty_patch_is_a_faithful_copy() -> None:
    original = _row()
    patched = original.with_updates(Row.scope(Update)())
    assert patched.model_dump() == original.model_dump()


# --- works with non-partial projections too --------------------------------


def test_accepts_non_partial_projection() -> None:
    # A regular (non-partial) projection: its set fields are applied.
    pub = Row.scope(Public)(name="z", note="n", inner={"label": "q"})  # type: ignore[arg-type]
    patched = _row().with_updates(pub)
    assert patched.name == "z"
    assert patched.note == "n"
    assert patched.count == 1  # Storage field, not on the Public projection


# --- validation runs --------------------------------------------------------


def test_patched_value_must_satisfy_canonical_validation() -> None:
    class Bounded(ScopedModel):
        n: Annotated[int, scoped(Public), Field(ge=0)]

    inst = Bounded(n=5)
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        inst.with_updates(Bounded.scope(Update)(n=-1))


# --- provenance -------------------------------------------------------------


def test_wrong_model_projection_raises() -> None:
    class Other(ScopedModel):
        x: Annotated[str, scoped(Public)]

    with pytest.raises(TypeError, match="expects a projection of Row"):
        _row().with_updates(Other.scope(Public)(x="z"))


def test_non_projection_raises() -> None:
    with pytest.raises(TypeError):
        _row().with_updates(Inner(label="x"))  # type: ignore[arg-type]


def test_subclass_instance_accepts_base_projection() -> None:
    class Sub(Row):
        extra: Annotated[str, scoped(Public)] = ""

    sub = Sub(name="a", inner=Inner(label="x"), extra="e")
    # a projection of the base Row applied to a Sub instance is allowed
    patched = sub.with_updates(Row.scope(Update)(name="b"))
    assert isinstance(patched, Sub)
    assert patched.name == "b"
    assert patched.extra == "e"
