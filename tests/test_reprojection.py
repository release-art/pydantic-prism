"""Round 18: re-projection — deriving a narrower projection from a projection."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, model_validator

from pydantic_prism import Scope, ScopedModel, ref, scoped


class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


class Org(ScopedModel):
    id: Annotated[UUID, scoped(Public)]


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    org_id: Annotated[UUID, ref(Org), scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    password: Annotated[str, scoped(Storage)]
    name: Annotated[str, scoped(Public)]


# --- the core mechanic -----------------------------------------------------


def test_reprojection_narrows_to_the_intersection() -> None:
    # UserInternal.scope(Public) == User.scope(Internal & Public) == UserPublic fields
    reproj = User.scope(Internal).scope(Public)
    assert set(reproj.model_fields) == set(User.scope(Public).model_fields)
    assert set(reproj.model_fields) == {"id", "org_id", "name"}
    assert reproj.__prism_scope__ == (Internal & Public)


def test_reprojection_only_narrows_never_widens() -> None:
    # re-projecting a Public view to a wider scope cannot resurrect dropped fields
    wider = User.scope(Public).scope(Internal)
    assert set(wider.model_fields) == set(User.scope(Public).model_fields)
    assert "email" not in wider.model_fields  # Internal-only field stays gone


def test_reprojection_is_a_sibling_not_a_subclass() -> None:
    internal = User.scope(Internal)
    reproj = internal.scope(Public)
    assert reproj.__prism_source__ is User  # of the canonical, not of `internal`
    assert not issubclass(reproj, internal)


def test_reprojection_is_cached() -> None:
    internal = User.scope(Internal)
    assert internal.scope(Public) is internal.scope(Public)


def test_nested_reprojection_chains() -> None:
    chained = User.scope(Storage).scope(Internal).scope(Public)
    assert set(chained.model_fields) == set(User.scope(Public).model_fields)


def test_reprojection_carries_refs_filtered_to_survivors() -> None:
    reproj = User.scope(Internal).scope(Public)
    assert "org_id" in reproj.__refs__
    assert reproj.__refs__["org_id"].target is Org


# --- naming + bases --------------------------------------------------------


def test_default_name_is_the_intersection_token() -> None:
    assert User.scope(Internal).scope(Public).__name__ == "UserInternalAndPublic"


def test_name_override() -> None:
    reproj = User.scope(Internal).scope(Public, name="UserCard")
    assert reproj.__name__ == "UserCard"


class EnvelopeBase(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _unwrap(cls, values: Any) -> Any:
        if isinstance(values, dict) and "__envelope__" in values:
            return values["__envelope__"]
        return values

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return {"__envelope__": super().model_dump(**kwargs)}


class Row(EnvelopeBase, ScopedModel, projection_bases=(EnvelopeBase,)):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    secret: Annotated[str, scoped(Internal)]


def test_reprojection_carries_bases_by_default() -> None:
    # a carried-base projection, re-projected, keeps the base behavior
    row_internal = Row.scope(Internal)
    assert issubclass(row_internal, EnvelopeBase)
    reproj = row_internal.scope(Public)
    assert issubclass(reproj, EnvelopeBase)  # base survived the narrowing
    # the carried base's dump-envelope and unwrap-validator both still work
    dumped = reproj(id=uuid4(), name="x").model_dump()
    assert "__envelope__" in dumped
    assert reproj.model_validate(dumped).name == "x"


def test_reprojection_bases_override_opts_out() -> None:
    # bases=() drops the carried base; a distinct name= avoids colliding with the
    # default-name re-projection that *kept* the base.
    reproj = Row.scope(Internal).scope(Public, bases=(), name="RowPlain")
    assert not issubclass(reproj, EnvelopeBase)


# --- instance-level counterpart already works via from_canonical -----------


def test_instance_narrowing_via_from_canonical() -> None:
    user = User(id=uuid4(), org_id=uuid4(), email="a@b.c", password="pw", name="Ada")
    internal = User.scope(Internal).from_canonical(user)
    # narrow the wider projection's *instance* down to the Public view
    public = User.scope(Public).from_canonical(internal)
    assert set(public.model_dump()) == {"id", "org_id", "name"}
