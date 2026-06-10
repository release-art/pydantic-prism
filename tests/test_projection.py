"""Projection derivation: membership, composition, caching, naming, fidelity."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from pydantic_prism import Projection, Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


class Llm(Scope): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    password_hash: Annotated[str, scoped(Storage)]
    display_name: Annotated[str, scoped(Public)]
    audit_note: str = "untagged"


def test_basic_membership_and_hierarchy() -> None:
    assert list(User.scope(Public).model_fields) == ["id", "display_name"]
    assert list(User.scope(Internal).model_fields) == ["id", "email", "display_name"]
    assert list(User.scope(Storage).model_fields) == [
        "id",
        "email",
        "password_hash",
        "display_name",
    ]


def test_untagged_fields_in_no_scope() -> None:
    for scope in (Public, Internal, Storage):
        assert "audit_note" not in User.scope(scope).model_fields


def test_wildcard_root_scope() -> None:
    class Doc(ScopedModel):
        body: Annotated[str, scoped(Scope)]
        secret: Annotated[str, scoped(Internal)]

    assert "body" in Doc.scope(Llm).model_fields
    assert "body" in Doc.scope(Public).model_fields
    assert "secret" not in Doc.scope(Llm).model_fields


def test_caching_identity() -> None:
    assert User.scope(Public) is User.scope(Public)
    assert User.scope(Public | Internal) is User.scope(Internal | Public)
    assert User.scope(Public, Internal) is User.scope(Public | Internal)
    assert User.scope(Public) is not User.scope(Public, name="Custom")


def test_auto_and_custom_naming() -> None:
    assert User.scope(Public).__name__ == "UserPublic"
    assert User.scope(Public | Internal).__name__ == "UserInternalOrPublic"
    assert User.scope(Storage - Llm).__name__ == "UserStorageNotLlm"
    assert User.scope(Public, name="PublicUser").__name__ == "PublicUser"


def test_composition_operators() -> None:
    class M(ScopedModel):
        a: Annotated[int, scoped(Public)]
        b: Annotated[int, scoped(Llm)]
        c: Annotated[int, scoped(Public, Llm)]

    assert list(M.scope(Public | Llm).model_fields) == ["a", "b", "c"]
    assert list(M.scope(Public & Llm).model_fields) == ["c"]
    assert list(M.scope(Public - Llm).model_fields) == ["a"]
    assert list(M.scope(~Llm).model_fields) == ["a"]


def test_projection_is_a_real_basemodel() -> None:
    UserPublic = User.scope(Public)
    assert issubclass(UserPublic, BaseModel)
    assert issubclass(UserPublic, Projection)
    assert not issubclass(UserPublic, ScopedModel)
    assert UserPublic.__prism_source__ is User
    instance = UserPublic(id=uuid4(), display_name="Ada")
    assert set(instance.model_dump()) == {"id", "display_name"}


def test_json_schema_of_projection() -> None:
    schema = User.scope(Public).model_json_schema()
    assert schema["title"] == "UserPublic"
    assert set(schema["properties"]) == {"id", "display_name"}
    assert set(schema["required"]) == {"id", "display_name"}
    assert schema["properties"]["id"]["format"] == "uuid"


def test_constraints_survive_projection() -> None:
    class Item(ScopedModel):
        qty: Annotated[int, scoped(Public), Field(gt=0)]
        note: Annotated[str, Field(max_length=3), scoped(Public)]  # marker order swapped

    ItemPublic = Item.scope(Public)
    with pytest.raises(ValidationError):
        ItemPublic(qty=0, note="ok")
    with pytest.raises(ValidationError):
        ItemPublic(qty=1, note="toolong")
    assert ItemPublic(qty=1, note="ok").qty == 1


def test_field_validators_carry_over() -> None:
    class Account(ScopedModel):
        email: Annotated[str, scoped(Public)]
        backup_email: Annotated[str, scoped(Internal)] = ""

        @field_validator("email", "backup_email")
        @classmethod
        def _lower(cls, value: str) -> str:
            return value.lower()

    # validator covers two fields; only one survives in Public
    assert Account.scope(Public)(email="A@B.C").email == "a@b.c"
    internal = Account.scope(Internal)(email="A@B.C", backup_email="X@Y.Z")
    assert internal.backup_email == "x@y.z"


def test_model_validators_do_not_carry_over() -> None:
    class Pair(ScopedModel):
        a: Annotated[int, scoped(Public)]
        b: Annotated[int, scoped(Internal)] = 0

        @model_validator(mode="after")
        def _check(self) -> "Pair":
            if self.a != self.b:
                raise ValueError("a must equal b")
            return self

    with pytest.raises(ValidationError):
        Pair(a=1, b=2)
    # the projection drops b; the model validator would be unsatisfiable
    assert Pair.scope(Public)(a=1).a == 1


def test_model_config_copied() -> None:
    class Frozen(ScopedModel):
        model_config = ConfigDict(frozen=True)
        x: Annotated[int, scoped(Public)]

    instance = Frozen.scope(Public)(x=1)
    with pytest.raises(ValidationError):
        instance.x = 2


def test_multiple_scoped_markers_union() -> None:
    class M(ScopedModel):
        x: Annotated[int, scoped(Public), scoped(Llm)]

    assert "x" in M.scope(Llm).model_fields
    assert "x" in M.scope(Public).model_fields


def test_scoped_model_inheritance() -> None:
    class AdminUser(User):
        admin_level: Annotated[int, scoped(Internal)] = 0

    fields = list(AdminUser.scope(Internal).model_fields)
    assert "email" in fields and "admin_level" in fields
    # the parent's cache is untouched by the subclass
    assert "admin_level" not in User.scope(Internal).model_fields


def test_concurrent_scope_calls_share_one_class() -> None:
    from concurrent.futures import ThreadPoolExecutor

    class Fresh(ScopedModel):
        x: Annotated[int, scoped(Public)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        classes = list(pool.map(lambda _: Fresh.scope(Public), range(32)))
    assert len({id(c) for c in classes}) == 1


def test_defaults_survive_projection() -> None:
    class WithDefault(ScopedModel):
        x: Annotated[int, scoped(Public)] = 7

    assert WithDefault.scope(Public)().x == 7
