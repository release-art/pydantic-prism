"""Custom-base composition: bases= / projection_bases=, warning, base fields."""

import warnings
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, model_validator

from pydantic_prism import ProjectionBaseError, Scope, ScopedModel, scoped


class Public(Scope): ...


class Storage(Public): ...


class EnvelopeBase(BaseModel):
    """Azure-style base: wraps dumps in an envelope, unwraps on validation."""

    @model_validator(mode="before")
    @classmethod
    def _unwrap(cls, values: Any) -> Any:
        if isinstance(values, dict) and "__envelope__" in values:
            return values["__envelope__"]
        return values

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return {"__envelope__": super().model_dump(**kwargs)}

    def storage_key(self) -> str:
        return f"row:{getattr(self, 'id', '?')}"


class Row(EnvelopeBase, ScopedModel, projection_bases=(EnvelopeBase,)):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    secret: Annotated[str, scoped(Storage - Public)]


def test_envelope_round_trip_through_projection() -> None:
    """The round-2 acceptance test: custom model_dump envelope survives.

    The canonical dumps a wrapped envelope; the projection (carrying the
    base) unwraps it on validation and re-wraps on its own dump.
    """
    row = Row(id=uuid4(), name="ada", secret="s3cr3t")
    public = Row.scope(Public).from_canonical(row)
    assert public.name == "ada"  # type: ignore[attr-defined]
    dumped = public.model_dump()
    assert set(dumped) == {"__envelope__"}
    assert dumped["__envelope__"]["name"] == "ada"
    # and the projection validates its own envelope back
    again = Row.scope(Public).model_validate(dumped)
    assert again == public


def test_projection_isinstance_of_carried_base() -> None:
    public = Row.scope(Public)(id=uuid4(), name="x")
    assert isinstance(public, EnvelopeBase)
    assert public.storage_key().startswith("row:")


def test_carried_base_is_part_of_cache_key_and_naming() -> None:
    assert Row.scope(Public) is Row.scope(Public)
    # same expression, different bases -> different class; the auto-generated
    # name is taken, so a name= is required to disambiguate
    from pydantic_prism import ProjectionNameError

    with pytest.raises(ProjectionNameError):
        Row.scope(Public, bases=())
    bare = Row.scope(Public, bases=(), name="RowPublicBare")
    assert bare is not Row.scope(Public)
    assert not isinstance(bare(id=uuid4(), name="x"), EnvelopeBase)


def test_per_call_bases_without_class_declaration() -> None:
    class PlainRow(EnvelopeBase, ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        note: Annotated[str, scoped(Public)]

    carried = PlainRow.scope(Public, bases=(EnvelopeBase,))
    instance = carried(id=uuid4(), note="n")
    assert isinstance(instance, EnvelopeBase)
    assert set(instance.model_dump()) == {"__envelope__"}


def test_dropped_behavior_warns_once_per_model() -> None:
    class Unaware(EnvelopeBase, ScopedModel):
        id: Annotated[UUID, scoped(Public)]

    with pytest.warns(UserWarning, match="do not inherit"):
        Unaware.scope(Public)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        Unaware.scope(Public, name="UnawareAgain")
    assert not [w for w in record if issubclass(w.category, UserWarning)]


def test_explicit_empty_projection_bases_silences_warning(
    recwarn: pytest.WarningsRecorder,
) -> None:
    class OptedOut(EnvelopeBase, ScopedModel, projection_bases=()):
        id: Annotated[UUID, scoped(Public)]

    OptedOut.scope(Public)
    assert not [w for w in recwarn if issubclass(w.category, UserWarning)]


def test_plain_models_never_warn(recwarn: pytest.WarningsRecorder) -> None:
    class NoBase(ScopedModel):
        id: Annotated[UUID, scoped(Public)]

    NoBase.scope(Public)
    assert not [w for w in recwarn if issubclass(w.category, UserWarning)]


def test_untagged_base_fields_are_present_on_every_projection() -> None:
    class TableBase(BaseModel):
        partition_key: str = "default"

    class Item(TableBase, ScopedModel, projection_bases=(TableBase,)):
        id: Annotated[UUID, scoped(Public)]

    projected = Item.scope(Public)
    assert "partition_key" in projected.model_fields
    instance = projected(id=uuid4(), partition_key="p1")
    assert instance.partition_key == "p1"  # type: ignore[attr-defined]


def test_tagged_base_field_not_selected_raises() -> None:
    class TaggedBase(BaseModel):
        etag: Annotated[str, scoped(Storage)] = ""

    class Versioned(TaggedBase, ScopedModel, projection_bases=(TaggedBase,)):
        id: Annotated[UUID, scoped(Public)]

    with pytest.raises(ProjectionBaseError, match="etag"):
        Versioned.scope(Public)
    # selecting the field is fine
    assert "etag" in Versioned.scope(Storage).model_fields


def test_base_model_validator_runs_on_projection_input() -> None:
    public = Row.scope(Public)
    via_envelope = public.model_validate({"__envelope__": {"id": str(uuid4()), "name": "e"}})
    assert via_envelope.name == "e"  # type: ignore[attr-defined]


def test_invalid_bases_rejected() -> None:
    class Unrelated(BaseModel):
        x: int = 0

    class Simple(ScopedModel):
        id: Annotated[UUID, scoped(Public)]

    with pytest.raises(TypeError, match="not an ancestor"):
        Simple.scope(Public, bases=(Unrelated,))
    with pytest.raises(TypeError, match="not a pydantic BaseModel"):
        Simple.scope(Public, bases=(object,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="is a ScopedModel"):

        class Child(Simple):
            extra: Annotated[str, scoped(Public)] = ""

        Child.scope(Public, bases=(Simple,))


def test_invalid_class_level_projection_bases_rejected() -> None:
    class SomeBase(BaseModel):
        y: int = 0

    with pytest.raises(TypeError, match="not an ancestor"):

        class Broken(ScopedModel, projection_bases=(SomeBase,)):
            id: Annotated[UUID, scoped(Public)]


def test_class_level_declaration_is_inherited() -> None:
    class ChildRow(Row):
        extra: Annotated[str, scoped(Public)] = ""

    projected = ChildRow.scope(Public)
    assert isinstance(projected(id=uuid4(), name="x"), EnvelopeBase)
