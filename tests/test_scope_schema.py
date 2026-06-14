"""Scope-attached JSON schema metadata — field-level and model-level."""

from typing import Annotated

import pytest
from pydantic import Field

from pydantic_prism import Scope, ScopedModel, scoped


class Ref(Scope): ...


class Public(Ref, description="Public-facing view", examples=[{"id": 1}]): ...


class Internal(Public, json_schema_extra={"x-audience": "internal"}): ...


class Storage(Internal): ...


class Other(Scope): ...


class User(ScopedModel):
    id: Annotated[int, scoped(Ref)]
    email: Annotated[
        str,
        scoped(Public, override=Field(description="User contact (public-facing)")),
        scoped(
            Internal, override=Field(description="User identity, for internal audit")
        ),
    ]


def _field_schema(proj: type, field: str) -> dict:
    return proj.model_json_schema()["properties"][field]


# --- field-level ------------------------------------------------------------


def test_field_description_differs_per_projection() -> None:
    assert (
        _field_schema(User.scope(Public), "email")["description"]
        == "User contact (public-facing)"
    )
    assert (
        _field_schema(User.scope(Internal), "email")["description"]
        == "User identity, for internal audit"
    )


def test_field_membership_still_unions_across_markers() -> None:
    # email is in Public ∪ Internal; both projections keep it.
    assert "email" in User.scope(Public).model_fields
    assert "email" in User.scope(Internal).model_fields
    assert repr(User.__prism__.field_scopes["email"]) == "(Internal | Public)"


def test_most_derived_scope_wins_in_broad_projection() -> None:
    # Storage selects both Public and Internal markers; Internal (subclass) wins.
    assert (
        _field_schema(User.scope(Storage), "email")["description"]
        == "User identity, for internal audit"
    )


def test_no_schema_when_scope_unselected() -> None:
    # Ref projection keeps only id; email isn't present, and id has no schema.
    assert "description" not in _field_schema(User.scope(Ref), "id")


def test_examples_and_json_schema_extra_on_field() -> None:
    class M(ScopedModel):
        token: Annotated[
            str,
            scoped(
                Public,
                override=Field(
                    examples=["abc"], json_schema_extra={"format": "secret"}
                ),
            ),
        ]

    schema = _field_schema(M.scope(Public), "token")
    assert schema["examples"] == ["abc"]
    assert schema["format"] == "secret"


def test_override_replaces_canonical_description() -> None:
    class M(ScopedModel):
        x: Annotated[
            int,
            Field(description="canonical"),
            scoped(Public, override=Field(description="scoped")),
        ]

    assert _field_schema(M.scope(Public), "x")["description"] == "scoped"


def test_ambiguous_unrelated_scopes_raise() -> None:
    class M(ScopedModel):
        f: Annotated[
            str,
            scoped(Public, override=Field(description="p")),
            scoped(Other, override=Field(description="o")),
        ]

    M.scope(Public)  # fine: only Public selected
    with pytest.raises(TypeError, match="ambiguous scoped"):
        M.scope(Public | Other)


def test_multi_scope_with_override_rejected() -> None:
    with pytest.raises(TypeError, match="exactly one scope"):
        scoped(Public, Internal, override=Field(description="x"))
    with pytest.raises(TypeError, match="exactly one scope"):
        scoped(Public | Internal, override=Field(description="x"))


# --- model-level ------------------------------------------------------------


def test_scope_description_and_examples_land_on_model_schema() -> None:
    schema = User.scope(Public).model_json_schema()
    assert schema["description"] == "Public-facing view"
    assert schema["examples"] == [{"id": 1}]


def test_scope_json_schema_extra_lands_on_model_schema() -> None:
    schema = User.scope(Internal).model_json_schema()
    assert schema["x-audience"] == "internal"


def test_model_schema_not_inherited_between_scopes() -> None:
    # Internal does not inherit Public's description (per-class metadata).
    assert User.scope(Internal).model_json_schema().get("description") != (
        "Public-facing view"
    )


def test_model_schema_merges_canonical_json_schema_extra() -> None:
    from pydantic import ConfigDict

    class WithExtra(ScopedModel):
        model_config = ConfigDict(json_schema_extra={"x-base": "kept"})
        id: Annotated[int, scoped(Public)]

    schema = WithExtra.scope(Public).model_json_schema()
    assert schema["x-base"] == "kept"  # canonical extra preserved
    assert schema["description"] == "Public-facing view"  # scope extra merged


def test_model_schema_merges_callable_json_schema_extra() -> None:
    from pydantic import ConfigDict

    def add_base(schema: dict) -> None:
        schema["x-callable"] = "ran"

    class WithCallable(ScopedModel):
        model_config = ConfigDict(json_schema_extra=add_base)
        id: Annotated[int, scoped(Public)]

    schema = WithCallable.scope(Public).model_json_schema()
    assert schema["x-callable"] == "ran"  # original callable still ran
    assert schema["description"] == "Public-facing view"  # scope extra applied
