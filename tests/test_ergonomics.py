"""Round-2 ergonomics: scopes(), richer errors, recursion stress test."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest

from pydantic_prism import EmptyProjectionError, Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


class Admin(Internal): ...


class Llm(Scope): ...


class Account(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    flags: Annotated[list[str], scoped(Admin)] = []
    body: Annotated[str, scoped(Scope - Llm)] = ""


def test_scopes_returns_atom_classes() -> None:
    assert Account.scopes() == frozenset({Public, Internal, Admin, Scope, Llm})


def test_scopes_feed_back_into_scope() -> None:
    for scope in Account.scopes() - {Llm}:
        assert Account.scope(scope) is Account.scope(scope)


def test_scopes_empty_for_untagged_model() -> None:
    class Bare(ScopedModel):
        note: str = ""

    assert Bare.scopes() == frozenset()


def test_empty_projection_error_lists_defined_scopes() -> None:
    class Unrelated(Scope): ...

    with pytest.raises(EmptyProjectionError) as excinfo:
        Account.scope(Unrelated - Scope, name="AccountNothing")
    message = str(excinfo.value)
    assert "Account defines scopes: Admin, Internal, Llm, Public, Scope" in message


def test_empty_projection_error_on_untagged_model() -> None:
    class Bare(ScopedModel):
        note: str = ""

    with pytest.raises(EmptyProjectionError, match="no fields of Bare are tagged"):
        Bare.scope(Public)


def test_recursive_dict_tuple_and_projection_together() -> None:
    """The round-2 recursion stress test: dict[str, Self], tuple[Self, ...],
    and projection, all at once."""

    class Tree(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        label: Annotated[str, scoped(Internal)] = ""
        branches: Annotated[dict[str, "Tree"], scoped(Public)] = {}
        ordered: Annotated[tuple["Tree", ...], scoped(Public)] = ()

    projected = Tree.scope(Public)
    tree = projected(
        id=uuid4(),
        branches={"left": {"id": uuid4(), "branches": {"deep": {"id": uuid4()}}}},
        ordered=({"id": uuid4()},),
    )
    left = tree.branches["left"]  # type: ignore[attr-defined]
    assert type(left) is projected
    assert type(left.branches["deep"]) is projected
    assert type(tree.ordered[0]) is projected  # type: ignore[attr-defined]
    assert "label" not in projected.model_fields
    # the self-edges register as embedded composition
    assert Tree.__refs__["branches"].target is Tree
    assert Tree.__refs__["ordered"].target is Tree
