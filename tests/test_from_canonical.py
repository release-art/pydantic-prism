"""from_canonical: model_dump kwargs passthrough and narrowing control."""

from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError, field_validator

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


class Event(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    title: Annotated[str, scoped(Public)]
    payload: Annotated[dict[str, int], scoped(Internal)] = {}


def test_mode_json_is_forwarded() -> None:
    event = Event(id=uuid4(), title="t")
    projected = Event.scope(Public).from_canonical(event, mode="json")
    assert projected.id == event.id  # type: ignore[attr-defined]


def test_context_is_forwarded_to_validation() -> None:
    class Stamped(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        label: Annotated[str, scoped(Public)]

        @field_validator("label")
        @classmethod
        def _stamp(cls, value: str, info: Any) -> str:
            suffix = (info.context or {}).get("suffix", "")
            return value + suffix

    stamped = Stamped.model_validate({"id": str(uuid4()), "label": "x"})
    projected = Stamped.scope(Public).from_canonical(stamped, context={"suffix": "!"})
    assert projected.label == "x!"  # type: ignore[attr-defined]


def test_exclude_none_is_forwarded() -> None:
    class Sparse(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        note: Annotated[str | None, scoped(Public)] = None

    sparse = Sparse(id=uuid4())
    projected = Sparse.scope(Public).from_canonical(sparse, exclude_none=True)
    assert projected.note is None  # type: ignore[attr-defined]


def test_exclude_unset_and_defaults_are_forwarded() -> None:
    event = Event(id=uuid4(), title="t")
    projection = Event.scope(Public)
    via_unset = projection.from_canonical(event, exclude_unset=True)
    via_defaults = projection.from_canonical(event, exclude_defaults=True)
    assert via_unset.title == via_defaults.title == "t"  # type: ignore[attr-defined]


def test_custom_dump_skips_narrowing_automatically() -> None:
    class Enveloped(BaseModel):
        def model_dump(self, **kwargs: Any) -> dict[str, Any]:
            return {"wrapped": super().model_dump(**kwargs)}

    class WireRow(Enveloped, ScopedModel, projection_bases=(Enveloped,)):
        id: Annotated[UUID, scoped(Public)]

        @classmethod
        def _unwrap(cls, values: Any) -> Any:  # pragma: no cover - shape helper
            return values

    # custom model_dump -> narrow auto-detects to False -> the projection's
    # model_validate receives the envelope verbatim (and fails: the carried
    # base has no unwrap validator here, which proves nothing narrowed it)
    row = WireRow(id=uuid4())
    with pytest.raises(ValidationError):
        WireRow.scope(Public).from_canonical(row)
    # forcing narrow=True restores v0.1 behavior: envelope keys are dropped
    with pytest.raises(ValidationError):
        WireRow.scope(Public).from_canonical(row, narrow=True)


def test_narrow_false_passes_dump_verbatim() -> None:
    event = Event(id=uuid4(), title="t", payload={"a": 1})
    # default config ignores extras, so the unnarrowed canonical dump validates
    projected = Event.scope(Public).from_canonical(event, narrow=False)
    assert projected.title == "t"  # type: ignore[attr-defined]
