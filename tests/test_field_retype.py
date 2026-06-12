"""Per-scope field *type* override: ``scoped(..., as_type=..., convert=...)``.

A field can carry a different annotation per projection — the one thing
``override=Field(...)`` cannot do — with optional ``Converter`` hooks that keep
round-trips total across the type change, per-projection ref-graph re-derivation
when a relationship field is reshaped, and full nesting in both directions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import pytest
from pydantic import Field, ValidationError

from pydantic_prism import (
    Converter,
    Scope,
    ScopedModel,
    ref,
    scoped,
)


class Storage(Scope): ...


class Llm(Scope): ...


class Event(ScopedModel):
    created: Annotated[
        datetime,
        scoped(Storage),
        scoped(
            Llm,
            as_type=str,
            convert=Converter(encode=datetime.isoformat, decode=datetime.fromisoformat),
            override=Field(description="ISO-8601 timestamp"),
        ),
    ]


# --- the annotation itself differs ------------------------------------------


def test_type_differs_per_projection() -> None:
    assert Event.scope(Storage).model_fields["created"].annotation is datetime
    assert Event.scope(Llm).model_fields["created"].annotation is str


def test_retype_drives_json_schema_and_validation() -> None:
    llm_schema = Event.scope(Llm).model_json_schema()["properties"]["created"]
    assert llm_schema["type"] == "string"
    assert llm_schema["description"] == "ISO-8601 timestamp"  # override composes
    # the Llm face validates a bare string; Storage wants a datetime
    assert (
        Event.scope(Llm)(created="2026-06-12T10:30:00").created == "2026-06-12T10:30:00"
    )
    with pytest.raises(ValidationError):
        Event.scope(Llm)(created=object())  # type: ignore[arg-type]


def test_as_type_without_override_or_convert() -> None:
    class M(ScopedModel):
        n: Annotated[int, scoped(Storage), scoped(Llm, as_type=str)]

    assert M.scope(Storage).model_fields["n"].annotation is int
    assert M.scope(Llm).model_fields["n"].annotation is str


def test_most_derived_retype_wins() -> None:
    class Wide(Scope): ...

    class Narrow(Wide): ...

    class M(ScopedModel):
        x: Annotated[
            int,
            scoped(Wide, as_type=str),
            scoped(Narrow, as_type=bytes),
        ]

    # Narrow ⊂ Wide; a Narrow projection selects both markers, most-derived wins
    assert M.scope(Narrow).model_fields["x"].annotation is bytes


def test_as_type_requires_single_scope() -> None:
    with pytest.raises(TypeError, match="exactly one scope"):
        scoped(Storage, Llm, as_type=str)


def test_convert_without_as_type_requires_single_scope() -> None:
    with pytest.raises(TypeError, match="exactly one scope"):
        scoped(Storage, Llm, convert=Converter(encode=str))


# --- converters: round-trips stay total -------------------------------------


def test_encode_decode_round_trip() -> None:
    dt = datetime(2026, 6, 12, 10, 30)
    event = Event(created=dt)
    llm = Event.scope(Llm).from_canonical(event)
    assert llm.created == "2026-06-12T10:30:00"  # encoded
    back = Event.from_projection(llm)
    assert back.created == dt  # decoded


def test_encode_only_with_native_decode_fallback() -> None:
    class M(ScopedModel):
        when: Annotated[
            datetime,
            scoped(Storage),
            scoped(Llm, as_type=str, convert=Converter(encode=datetime.isoformat)),
        ]

    dt = datetime(2026, 1, 2, 3, 4)
    llm = M.scope(Llm).from_canonical(M(when=dt))
    assert llm.when == "2026-01-02T03:04:00"
    # no decoder: pydantic's native ISO-string → datetime coercion bridges it
    assert M.from_projection(llm).when == dt


def test_decode_only() -> None:
    class M(ScopedModel):
        when: Annotated[
            datetime,
            scoped(Storage),
            scoped(Llm, as_type=str, convert=Converter(decode=datetime.fromisoformat)),
        ]

    llm = M.scope(Llm)(when="2026-01-02T03:04:00")
    assert M.from_projection(llm).when == datetime(2026, 1, 2, 3, 4)


def test_convert_without_as_type_transforms_round_trip() -> None:
    """A converter need not retype — it can just transform the value per scope."""

    class M(ScopedModel):
        code: Annotated[
            str,
            scoped(Storage),
            scoped(Llm, convert=Converter(encode=str.upper, decode=str.lower)),
        ]

    llm = M.scope(Llm).from_canonical(M(code="abc"))
    assert llm.code == "ABC"
    assert M.from_projection(llm).code == "abc"


def test_with_updates_decodes_patch() -> None:
    dt = datetime(2026, 6, 12, 10, 30)
    base = Event(created=datetime(2020, 1, 1))
    patch = Event.scope(Llm)(created=dt.isoformat())
    assert base.with_updates(patch).created == dt  # decoded onto the canonical


# --- nesting: both directions -----------------------------------------------


def test_nested_converter_round_trips() -> None:
    class Inner(ScopedModel):
        ts: Annotated[
            datetime,
            scoped(Storage),
            scoped(
                Llm,
                as_type=str,
                convert=Converter(
                    encode=datetime.isoformat, decode=datetime.fromisoformat
                ),
            ),
        ]

    class Outer(ScopedModel):
        inner: Annotated[Inner, scoped(Storage, Llm)]

    dt = datetime(2026, 6, 12, 9, 0)
    outer = Outer(inner=Inner(ts=dt))
    llm = Outer.scope(Llm).from_canonical(outer)
    assert llm.inner.ts == "2026-06-12T09:00:00"  # nested encode
    back = Outer.from_projection(llm)
    assert back.inner.ts == dt  # nested decode


# --- ref-graph re-derivation ------------------------------------------------


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Storage, Llm)]


def test_retype_reshapes_a_ref_edge() -> None:
    class Order(ScopedModel):
        cust: Annotated[
            UUID, ref(Customer), scoped(Storage), scoped(Llm, as_type=list[UUID])
        ]
        # a second, *non-retyped* ref: its canonical edge is kept verbatim while
        # the projection re-derives only `cust`
        seller: Annotated[UUID, ref(Customer), scoped(Storage, Llm)]

    assert Order.__refs__["cust"].shape.value == "scalar"
    assert Order.scope(Storage).__refs__["cust"].shape.value == "scalar"
    llm = Order.scope(Llm)
    assert llm.__refs__["cust"].shape.value == "collection"  # re-derived
    assert llm.__refs__["cust"].target is Customer  # marker preserved
    assert llm.__refs__["seller"].shape.value == "scalar"  # untouched canonical edge


def test_retype_can_drop_an_embedded_edge() -> None:
    class Order(ScopedModel):
        # canonically embeds Customer (auto-detected edge); retyped to str in Llm
        payload: Annotated[Customer, scoped(Storage), scoped(Llm, as_type=str)]
        note: Annotated[str, scoped(Storage, Llm)]

    assert Order.scope(Storage).__refs__["payload"].kind == "embedded"
    assert "payload" not in Order.scope(Llm).__refs__  # edge dropped on retype
    assert "note" not in Order.scope(Llm).__refs__  # plain field, never an edge


def test_retype_keeps_an_explicit_ref_edge() -> None:
    class Order(ScopedModel):
        # an explicit ref() declares the relationship; retyping the key only
        # reshapes the edge (here scalar UUID → keyed dict), it does not drop it
        cust: Annotated[
            UUID,
            ref(Customer),
            scoped(Storage),
            scoped(Llm, as_type=dict[UUID, UUID]),
        ]

    edge = Order.scope(Llm).__refs__["cust"]
    assert edge.kind == "ref"
    assert edge.shape.value == "keyed_dict"  # re-derived
    assert edge.target is Customer


def test_retype_can_add_an_embedded_edge() -> None:
    class Order(ScopedModel):
        payload: Annotated[str, scoped(Storage), scoped(Llm, as_type=Customer)]

    assert "payload" not in Order.scope(Storage).__refs__
    edge = Order.scope(Llm).__refs__["payload"]
    assert edge.kind == "embedded"
    assert edge.target is Customer


# --- composition with the rest of the engine --------------------------------


def test_partial_scope_composes_with_retype() -> None:
    class Patch(Scope, partial=True): ...

    class M(ScopedModel):
        created: Annotated[datetime, scoped(Storage), scoped(Patch, as_type=str)]

    # partial makes it optional (MISSING) *and* retyped to str
    patch = M.scope(Patch)()
    assert "created" in M.scope(Patch).model_fields
    assert (
        M.scope(Patch)(created="2026-06-12T00:00:00").created == "2026-06-12T00:00:00"
    )
    assert patch.model_dump() == {}  # unset stays absent


def test_reprojection_carries_retype() -> None:
    class Public(Scope): ...

    class Internal(Public): ...  # Internal is the broader scope

    class M(ScopedModel):
        x: Annotated[str, scoped(Public, as_type=bytes)]  # retype on the base scope

    # the broad Internal view sees the Public field (retyped); re-projecting it
    # *down* to Public only narrows, so the retype survives
    assert M.scope(Internal).model_fields["x"].annotation is bytes
    assert M.scope(Internal).scope(Public).model_fields["x"].annotation is bytes
