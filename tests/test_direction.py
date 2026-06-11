"""Round 17: the read/write direction axis — ``In`` / ``Out`` + input()/output()."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pydantic_prism import (
    Direction,
    In,
    Out,
    ProjectionNameError,
    Scope,
    ScopedModel,
    scoped,
)


class Public(Scope): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public, Out)]  # read-only
    email: Annotated[str, scoped(Public)]  # read-write
    password: Annotated[str, scoped(Public, In)]  # write-only


# --- the vocabulary --------------------------------------------------------


def test_in_out_are_directions_and_scopes() -> None:
    assert issubclass(In, Direction)
    assert issubclass(Out, Direction)
    assert issubclass(Direction, Scope)
    # a direction *is* a scope: it can be projected to directly.
    assert set(User.scope(In).model_fields) == {"password"}
    assert set(User.scope(Out).model_fields) == {"id"}


def test_directions_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError, match="used as a class, never instantiated"):
        In()
    with pytest.raises(TypeError, match="used as a class, never instantiated"):
        Out()


def test_directions_excluded_from_classifications() -> None:
    # The direction axis is orthogonal to classification.
    assert User.classifications() == frozenset()


def test_direction_atoms_carry_a_distinct_name_token() -> None:
    # token= keeps a direct scope(Out)/scope(In) from stealing the "...Out" /
    # "...In" names the output()/input() helpers default to.
    assert User.scope(Out).__name__ == "UserReadOnly"
    assert User.scope(In).__name__ == "UserWriteOnly"
    assert User.output(Public).__name__ == "UserOut"  # no collision
    assert User.input(Public).__name__ == "UserIn"


# --- shape: read-only / write-only / read-write ----------------------------


def test_input_drops_read_only() -> None:
    UserIn = User.input(Public)
    assert set(UserIn.model_fields) == {"email", "password"}
    assert "id" not in UserIn.model_fields  # read-only cannot be over-posted


def test_output_drops_write_only() -> None:
    UserOut = User.output(Public)
    assert set(UserOut.model_fields) == {"id", "email"}
    assert "password" not in UserOut.model_fields  # write-only never echoed


def test_plain_scope_keeps_everything() -> None:
    # A directional tag still belongs to its visibility scope; plain scope() is
    # the full schema, input()/output() are the directional filters.
    assert set(User.scope(Public).model_fields) == {"id", "email", "password"}


# --- extra="forbid" on input -----------------------------------------------


def test_input_forbids_extra_by_default() -> None:
    UserIn = User.input(Public)
    assert UserIn.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        UserIn(email="a@b.c", password="pw", is_admin=True)


def test_input_extra_override() -> None:
    # A view's extra is chosen once; use a local model so it doesn't collide
    # with the default-forbid "UserIn" built elsewhere.
    class Acct(ScopedModel):
        name: Annotated[str, scoped(Public)]

    AcctIn = Acct.input(Public, extra="ignore")
    assert AcctIn.model_config.get("extra") == "ignore"
    # unknown key tolerated (and dropped) under the opt-out
    instance = AcctIn(name="x", is_admin=True)
    assert not hasattr(instance, "is_admin")


def test_input_extra_allow_re_opens_the_door() -> None:
    class Acct(ScopedModel):
        name: Annotated[str, scoped(Public)]

    AcctIn = Acct.input(Public, extra="allow")
    assert AcctIn.model_config.get("extra") == "allow"


def test_output_leaves_extra_untouched() -> None:
    UserOut = User.output(Public)
    assert (
        "extra" not in UserOut.model_config
        or UserOut.model_config.get("extra") != "forbid"
    )


# --- naming ----------------------------------------------------------------


def test_default_names() -> None:
    assert User.input(Public).__name__ == "UserIn"
    assert User.output(Public).__name__ == "UserOut"


def test_name_override() -> None:
    assert User.input(Public, name="UserCreate").__name__ == "UserCreate"
    assert User.output(Public, name="UserRead").__name__ == "UserRead"


def test_two_input_views_collide_on_default_name() -> None:
    class Internal(Public): ...

    class Account(ScopedModel):
        a: Annotated[int, scoped(Public)]
        b: Annotated[int, scoped(Internal)]

    Account.input(Public)
    # A second input view wants the same "AccountIn" name for a different
    # expression — forces an explicit name=.
    with pytest.raises(ProjectionNameError):
        Account.input(Internal)
    assert Account.input(Internal, name="AccountAdminIn").__name__ == "AccountAdminIn"


# --- caching / identity ----------------------------------------------------


def test_helpers_are_cached() -> None:
    assert User.input(Public) is User.input(Public)
    assert User.output(Public) is User.output(Public)


def test_input_is_distinct_from_bare_scope() -> None:
    # Same expression (Public - Out) but extra="forbid" → a separate class with
    # its own name; the config fork is the whole reason it is not the bare scope.
    bare = User.scope(Public - Out)
    typed = User.input(Public)
    assert bare is not typed
    assert bare.__name__ != typed.__name__
    assert bare.model_config.get("extra") != "forbid"
    assert set(bare.model_fields) == set(typed.model_fields)


# --- default_scope fallback (direction-only) -------------------------------


class Wire(Scope): ...


class Account(ScopedModel, default_scope=Wire):
    id: Annotated[UUID, scoped(Wire, Out)]
    handle: Annotated[str, scoped(Wire)]
    secret: Annotated[str, scoped(Wire, In)]
    note: str  # untagged → default_scope Wire (read-write)


def test_no_arg_falls_back_to_default_scope() -> None:
    assert set(Account.input().model_fields) == {"handle", "secret", "note"}
    assert set(Account.output().model_fields) == {"id", "handle", "note"}


def test_no_arg_without_default_raises() -> None:
    with pytest.raises(TypeError, match=r"User\.input\(\) requires at least one"):
        User.input()
    with pytest.raises(TypeError, match=r"User\.output\(\) requires at least one"):
        User.output()


# --- composition: partial, nesting -----------------------------------------


def test_input_composes_with_partial_scope() -> None:
    class Update(Scope, partial=True): ...

    class Doc(ScopedModel):
        id: Annotated[UUID, scoped(Update, Out)]
        title: Annotated[str, scoped(Update)]

    DocIn = Doc.input(Update)
    assert set(DocIn.model_fields) == {"title"}  # read-only id dropped
    assert DocIn.__prism_scope__.is_partial()  # PATCH shape survives


def test_direction_drops_deep_through_nested_models() -> None:
    class Addr(ScopedModel):
        street: Annotated[str, scoped(Public)]
        geocode: Annotated[str, scoped(Public, Out)]  # read-only nested

    class Person(ScopedModel):
        name: Annotated[str, scoped(Public)]
        addr: Annotated[Addr, scoped(Public)]

    nested = Person.input(Public).model_fields["addr"].annotation
    assert nested is not None
    assert set(nested.model_fields) == {"street"}  # nested read-only dropped
    # extra="forbid" is top-level only; the nested projection is identical to the
    # bare projection of the same (Public - Out) expression — no fork, shared cache.
    assert nested.model_config.get("extra") != "forbid"
    assert nested is Addr.scope(Public - Out)


# --- round-trip works on a directional projection --------------------------


def test_output_round_trips_from_canonical() -> None:
    user = User(id=uuid4(), email="a@b.c", password="pw")
    out = User.output(Public).from_canonical(user)
    assert out.model_dump() == {"id": user.id, "email": "a@b.c"}
