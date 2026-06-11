"""Scope algebra: matching, selection, operators, canonical equality."""

import pytest

from pydantic_prism import Scope, ScopeExpr
from pydantic_prism._internal.scopes import as_expr, union_all


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


def test_named_methods_mirror_the_operators() -> None:
    from functools import reduce

    # varargs named forms on an expression, equivalent to the operators
    assert as_expr(Public).union(Internal, Llm) == (Public | Internal | Llm)
    assert as_expr(Public).intersection(Llm) == (Public & Llm)
    assert as_expr(Scope).difference(Llm, Internal) == ((Scope - Llm) - Internal)
    # and on a Scope class (via the metaclass)
    assert Public.union(Llm) == (Public | Llm)
    assert Public.intersection(Llm) == (Public & Llm)
    assert Public.difference(Llm) == (Public - Llm)
    # zero-arg forms are identity (left side unchanged)
    assert as_expr(Public).union() == as_expr(Public)
    assert as_expr(Public).difference() == as_expr(Public)
    assert as_expr(Public).intersection() == as_expr(Public)
    # the point: programmatic composition over a runtime list
    assert reduce(ScopeExpr.union, map(as_expr, [Public, Internal, Llm])) == (
        Public | Internal | Llm
    )


def test_canonical_equality_and_hash() -> None:
    assert (Public | Llm) == (Llm | Public)
    assert hash(Public | Llm) == hash(Llm | Public)
    assert (Public | (Llm | Storage)) == (Storage | Llm | Public)  # flattens
    assert union_all([as_expr(Public), as_expr(Public)]) == as_expr(Public)  # dedupes
    assert (Public | Llm) != (Public & Llm)
    # operands sort deterministically by sort_key regardless of kind/order — a
    # complement inside a union/intersection canonicalizes too
    assert (~Llm | Public) == (Public | ~Llm)
    assert (~Llm & Public) == (Public & ~Llm)


def test_tokens_used_for_class_names() -> None:
    assert as_expr(Public).token() == "Public"
    assert (Public | Llm).token() == "LlmOrPublic"  # deterministic order
    assert (Public - Llm).token() == "PublicNotLlm"
    assert (~Llm).token() == "NotLlm"
    assert (Public & Llm).token() == "LlmAndPublic"


def test_cls_name_token_overrides_class_name() -> None:
    class Tagged(Scope, cls_name_token="Slug"): ...

    class Sub(Tagged): ...  # the token is per-class, not inherited

    assert as_expr(Tagged).token() == "Slug"  # the override
    assert as_expr(Sub).token() == "Sub"  # fallback to own __name__
    assert (Tagged | Llm).token() == "LlmOrSlug"  # composes in expressions


def test_cls_name_token_must_be_an_identifier_fragment() -> None:
    with pytest.raises(TypeError, match="must be a non-empty fragment"):

        class Spaced(Scope, cls_name_token="Read Only"): ...

    with pytest.raises(TypeError, match="must be a non-empty fragment"):

        class Empty(Scope, cls_name_token=""): ...


def test_scopes_are_never_instantiated() -> None:
    with pytest.raises(TypeError, match="never instantiated"):
        Public()


def test_as_expr_rejects_non_scopes() -> None:
    with pytest.raises(TypeError, match="Scope subclass"):
        as_expr(42)
    with pytest.raises(TypeError, match="Scope subclass"):
        as_expr(int)
