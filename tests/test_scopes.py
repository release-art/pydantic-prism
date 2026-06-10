"""Scope algebra: matching, selection, operators, canonical equality."""

import pytest

from pydantic_prism import Scope
from pydantic_prism._scopes import as_expr, union_all


class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


class Llm(Scope): ...


def test_atom_matches_along_inheritance() -> None:
    expr = as_expr(Public)
    assert expr.matches(Public)
    assert expr.matches(Internal)  # Internal extends Public
    assert expr.matches(Storage)
    assert not expr.matches(Llm)


def test_root_scope_is_wildcard() -> None:
    root = as_expr(Scope)
    for scope in (Public, Internal, Storage, Llm):
        assert root.matches(scope)


def test_union_matches_either() -> None:
    expr = Public | Llm
    assert expr.matches(Public)
    assert expr.matches(Llm)
    assert expr.matches(Internal)
    assert not expr.matches(Scope)


def test_intersection_matches_both() -> None:
    class LlmInternal(Internal, Llm): ...

    expr = Internal & Llm
    assert not expr.matches(Internal)
    assert not expr.matches(Llm)
    assert expr.matches(LlmInternal)


def test_difference_and_complement() -> None:
    diff = Scope - Llm
    assert diff.matches(Public)
    assert not diff.matches(Llm)

    comp = ~Llm
    assert comp.matches(Public)
    assert not comp.matches(Llm)

    class SuperLlm(Llm): ...

    # exclusion propagates to scopes extending the excluded one
    assert not diff.matches(SuperLlm)
    assert not comp.matches(SuperLlm)


def test_selects_uses_tag_membership() -> None:
    tag = as_expr(Public)
    assert as_expr(Internal).selects(tag)  # Public field visible in Internal
    assert not as_expr(Public).selects(as_expr(Internal))  # not vice versa
    assert (~as_expr(Llm)).selects(tag)
    assert not (~as_expr(Public)).selects(tag)


def test_operators_compose_classes_and_expressions() -> None:
    assert (Public | Llm) == (as_expr(Public) | Llm)
    assert (Public & Llm) == (as_expr(Public) & Llm)
    assert (Public - Llm) == (as_expr(Public) - Llm)
    # reflected: expression on the right of a class
    assert (Public | (Llm & Internal)) == ((Llm & Internal) | Public)


def test_canonical_equality_and_hash() -> None:
    assert (Public | Llm) == (Llm | Public)
    assert hash(Public | Llm) == hash(Llm | Public)
    assert (Public | (Llm | Storage)) == (Storage | Llm | Public)  # flattens
    assert union_all([as_expr(Public), as_expr(Public)]) == as_expr(Public)  # dedupes
    assert (Public | Llm) != (Public & Llm)


def test_tokens_used_for_class_names() -> None:
    assert as_expr(Public).token() == "Public"
    assert (Public | Llm).token() == "LlmOrPublic"  # deterministic order
    assert (Public - Llm).token() == "PublicNotLlm"
    assert (~Llm).token() == "NotLlm"
    assert (Public & Llm).token() == "LlmAndPublic"


def test_scopes_are_never_instantiated() -> None:
    with pytest.raises(TypeError, match="never instantiated"):
        Public()


def test_as_expr_rejects_non_scopes() -> None:
    with pytest.raises(TypeError, match="Scope subclass"):
        as_expr(42)
    with pytest.raises(TypeError, match="Scope subclass"):
        as_expr(int)
