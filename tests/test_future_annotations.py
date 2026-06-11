"""Bug sweep #1: markers on forward-referenced annotations must not vanish.

This module deliberately uses ``from __future__ import annotations``, so every
annotation is lazy and fields referencing later-defined classes stay
unresolved at class-creation time. Marker collection must refresh once the
forward references resolve (explicit model_rebuild or the automatic one
inside .scope()).
"""

from __future__ import annotations

from typing import Annotated

import pytest

from pydantic_prism import Scope, ScopedModel, ref, scoped


class Public(Scope): ...


class Author(ScopedModel):
    name: Annotated[str, scoped(Public)]
    # Both reference Book, defined below — unresolved at class creation.
    favorite: Annotated[Book | None, scoped(Public)] = None
    book_id: Annotated[str, ref("Book"), scoped(Public)] = ""


class Book(ScopedModel):
    title: Annotated[str, scoped(Public)]


class Reader(ScopedModel):
    name: Annotated[str, scoped(Public)]
    reading: Annotated[Novel | None, scoped(Public)] = None


class Novel(ScopedModel):
    title: Annotated[str, scoped(Public)]


def test_explicit_rebuild_recovers_markers() -> None:
    Author.model_rebuild()
    assert set(Author.__field_scopes__) == {"name", "favorite", "book_id"}
    assert set(Author.scope(Public).model_fields) == {"name", "favorite", "book_id"}
    assert Author.__refs__["book_id"].target is Book


def test_scope_rebuilds_automatically() -> None:
    # No manual model_rebuild for Reader anywhere.
    projected = Reader.scope(Public)
    assert set(projected.model_fields) == {"name", "reading"}
    value = projected.model_validate({"name": "a", "reading": {"title": "t"}})
    assert value.reading is not None and value.reading.title == "t"


def test_unresolvable_forward_ref_errors_instead_of_silently_dropping() -> None:
    class Dangling(ScopedModel):
        name: Annotated[str, scoped(Public)]
        thing: Annotated[NeverDefined | None, scoped(Public)] = None  # noqa: F821

    with pytest.raises(Exception, match="NeverDefined"):
        Dangling.scope(Public)
