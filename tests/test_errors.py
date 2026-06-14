"""Error cases: misuse raises TypeError, domain failures raise PrismError."""

from typing import Annotated
from uuid import UUID

import pytest
from pydantic import BaseModel

from pydantic_prism import (
    EmptyProjectionError,
    PrismError,
    RefResolutionError,
    Scope,
    ScopedModel,
    backref,
    ref,
    scoped,
)


class Public(Scope): ...


class Llm(Scope): ...


class Target(ScopedModel):
    id: Annotated[UUID, scoped(Public)]


def test_marker_as_default_is_rejected_at_definition() -> None:
    with pytest.raises(TypeError, match="inside Annotated"):

        class Bad(ScopedModel):
            x: str = scoped(Public)  # type: ignore[assignment]


def test_ref_marker_as_default_is_rejected() -> None:
    with pytest.raises(TypeError, match="inside Annotated"):

        class Bad(ScopedModel):
            x: UUID = ref(Target)  # type: ignore[assignment]


def test_ref_target_must_be_scoped_model_or_string() -> None:
    class Plain(BaseModel):
        id: UUID

    with pytest.raises(TypeError, match="ScopedModel subclass or a string"):
        ref(Plain)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ScopedModel subclass or a string"):
        ref(42)  # type: ignore[arg-type]


def test_backref_argument_types() -> None:
    with pytest.raises(TypeError, match="ScopedModel subclass or a string"):
        backref(3.14, via="x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="via must be a field name"):
        backref(Target, via=42)  # type: ignore[arg-type]


def test_scoped_requires_scopes() -> None:
    with pytest.raises(TypeError, match="at least one scope"):
        scoped()
    with pytest.raises(TypeError, match="Scope subclass"):
        scoped("public")  # type: ignore[arg-type]  # strings are not scopes


def test_scope_call_requires_scopes() -> None:
    with pytest.raises(TypeError, match="required positional argument"):
        Target.scope()  # type: ignore[call-arg]  # scope is required
    with pytest.raises(TypeError, match="Scope subclass"):
        Target.scope("public")  # type: ignore[arg-type]


def test_multiple_ref_markers_rejected() -> None:
    with pytest.raises(TypeError, match="at most one"):

        class Bad(ScopedModel):
            x: Annotated[UUID, ref(Target), backref(Target, via="id"), scoped(Public)]


def test_empty_projection() -> None:
    class OnlyPublic(ScopedModel):
        x: Annotated[int, scoped(Public)]

    with pytest.raises(EmptyProjectionError, match="selects no fields"):
        OnlyPublic.scope(Llm)
    # PrismError is the common base
    with pytest.raises(PrismError):
        OnlyPublic.scope(Llm)


def test_unresolvable_circular_string_ref() -> None:
    class Lonely(ScopedModel):
        other_id: Annotated[UUID, ref("DefinedNowhere"), scoped(Public)]

    with pytest.raises(RefResolutionError, match="DefinedNowhere"):
        Lonely.__prism__.refs["other_id"]


def test_projection_classes_can_be_rescoped_to_narrow() -> None:
    # Round 18: projections re-project (narrowing); see test_reprojection.py.
    projected = Target.scope(Public)
    assert hasattr(projected, "scope")
    assert projected.scope(Public).__prism__.source is Target
