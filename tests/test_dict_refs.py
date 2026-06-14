"""Dict-keyed-by-id collections as a ref primitive."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest

from pydantic_prism import (
    RefResolutionError,
    RefShape,
    Scope,
    ScopedModel,
    ref,
    scoped,
)


class Public(Scope): ...


class Internal(Public): ...


class Highlight(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    text: Annotated[str, scoped(Public)]
    notes: Annotated[str, scoped(Internal)] = ""


class Page(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    highlights: Annotated[dict[UUID, Highlight], ref(Highlight), scoped(Public)]


def test_keyed_dict_ref_shape() -> None:
    info = Page.__prism__.refs["highlights"]
    assert info.kind == "ref"
    assert info.target is Highlight
    assert info.shape is RefShape.KEYED_DICT
    assert info.shape == "keyed_dict"  # StrEnum: string comparison works
    assert info.key_type is UUID
    assert info.many  # compat property
    assert not info.optional


def test_keyed_dict_ref_survives_projection() -> None:
    projected = Page.scope(Public)
    info = projected.__prism__.refs["highlights"]
    assert info.target is Highlight
    assert info.shape is RefShape.KEYED_DICT
    # the value type narrowed with the projection
    hid = uuid4()
    page = projected(id=uuid4(), highlights={hid: {"id": hid, "text": "t"}})
    value = page.highlights[hid]  # type: ignore[attr-defined]
    assert type(value) is Highlight.scope(Public)


def test_key_type_mismatch_raises_lazily() -> None:
    class BadPage(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        highlights: Annotated[dict[int, Highlight], ref(Highlight), scoped(Public)]

    with pytest.raises(RefResolutionError, match="does not match"):
        BadPage.__prism__.refs["highlights"]


def test_missing_target_field_raises() -> None:
    class NoSuchField(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        highlights: Annotated[
            dict[UUID, Highlight], ref(Highlight, field="nope"), scoped(Public)
        ]

    with pytest.raises(RefResolutionError, match="no field named 'nope'"):
        NoSuchField.__prism__.refs["highlights"]


def test_value_type_need_not_be_the_target() -> None:
    """Keys are ids of the target; the value may be an opaque payload."""

    class Scores(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        by_highlight: Annotated[dict[UUID, float], ref(Highlight), scoped(Public)]

    info = Scores.__prism__.refs["by_highlight"]
    assert info.target is Highlight
    assert info.shape is RefShape.KEYED_DICT


def test_optional_keyed_dict() -> None:
    class MaybePage(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        highlights: Annotated[
            dict[UUID, Highlight] | None, ref(Highlight), scoped(Public)
        ] = None

    info = MaybePage.__prism__.refs["highlights"]
    assert info.shape is RefShape.KEYED_DICT
    assert info.optional
    assert info.key_type is UUID


def test_realistic_expected_found_shape() -> None:
    """The SiteCompliance shape: two keyed dicts, one with a back-pointer."""

    class ExpectedHighlight(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        quote: Annotated[str, scoped(Public)]

    class FoundHighlight(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        expected_id: Annotated[UUID, ref(ExpectedHighlight), scoped(Public)]
        snippet: Annotated[str, scoped(Public)]

    class Audit(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        expected: Annotated[
            dict[UUID, ExpectedHighlight], ref(ExpectedHighlight), scoped(Public)
        ]
        found: Annotated[
            dict[UUID, FoundHighlight], ref(FoundHighlight), scoped(Public)
        ]

    assert Audit.__prism__.refs["expected"].shape is RefShape.KEYED_DICT
    assert Audit.__prism__.refs["found"].target is FoundHighlight
    assert FoundHighlight.__prism__.refs["expected_id"].target is ExpectedHighlight
    edges = {
        (source.__name__, info.field_name)
        for source, info in Audit.__prism__.refs.walk()
    }
    assert ("Audit", "expected") in edges
    assert ("Audit", "found") in edges
    assert ("FoundHighlight", "expected_id") in edges

    # the shape validates and projects
    eid, fid = uuid4(), uuid4()
    audit = Audit.scope(Public).from_canonical(
        Audit(
            id=uuid4(),
            expected={eid: ExpectedHighlight(id=eid, quote="q")},
            found={fid: FoundHighlight(id=fid, expected_id=eid, snippet="s")},
        )
    )
    assert audit.found[fid].expected_id == eid  # type: ignore[attr-defined]
