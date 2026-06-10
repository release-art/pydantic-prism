"""@scoped_validator: model validators that survive projection."""

from typing import Annotated, Any

import pytest
from pydantic import ValidationError, model_validator

from pydantic_prism import (
    Scope,
    ScopedModel,
    ScopeExpr,
    scoped,
    scoped_validator,
)


class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


class Update(Storage, partial=True): ...


class Other(Scope): ...


class M(ScopedModel):
    a: Annotated[str, scoped(Public)]
    tag: Annotated[str, scoped(Public)] = ""
    n: Annotated[int, scoped(Storage)] = 0
    seen: bool = False  # untagged: canonical only

    @scoped_validator(Public, mode="before")
    @classmethod
    def derive_tag(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("a") and not data.get("tag"):
            data = {**data, "tag": str(data["a"]).upper()}
        return data

    @scoped_validator(Storage, mode="after")
    def set_n(self) -> "M":
        # guard against None: this carries to partial Update too (Update selects
        # Storage), where surviving fields may be absent.
        if self.a is not None:
            object.__setattr__(self, "n", len(self.a))
        return self

    @model_validator(mode="after")
    def plain(self) -> "M":  # never carries (decision 14)
        object.__setattr__(self, "seen", True)
        return self


# --- introspection ---------------------------------------------------------


def test_validator_scopes_introspection() -> None:
    scopes = M.__prism_validator_scopes__
    assert set(scopes) == {"derive_tag", "set_n"}  # plain is absent
    assert repr(scopes["derive_tag"]) == "Public"
    assert repr(scopes["set_n"]) == "Storage"
    assert all(isinstance(v, ScopeExpr) for v in scopes.values())


# --- canonical still runs everything ---------------------------------------


def test_canonical_runs_all_validators() -> None:
    m = M(a="hi")
    assert m.tag == "HI"  # before
    assert m.n == 2  # after, scoped
    assert m.seen is True  # plain


# --- carry by the field algebra --------------------------------------------


def test_public_projection_carries_only_selected() -> None:
    public = M.scope(Public)
    decs = public.__pydantic_decorators__.model_validators
    assert "derive_tag" in decs  # Public selects Public
    assert "set_n" not in decs  # Public does not select Storage
    assert "plain" not in decs  # plain never carries
    p = public(a="hi")
    assert p.tag == "HI"  # derive_tag ran
    assert "n" not in public.model_fields  # Storage field dropped
    assert "seen" not in public.model_fields  # untagged dropped


def test_storage_projection_carries_broader() -> None:
    storage = M.scope(Storage)
    decs = storage.__pydantic_decorators__.model_validators
    assert {"derive_tag", "set_n"} <= set(decs)  # Storage selects Public and Storage
    assert "plain" not in decs
    s = storage(a="hello")
    assert s.tag == "HELLO"  # before carried
    assert s.n == 5  # after carried, touches surviving field a


def test_plain_model_validator_never_carries() -> None:
    for scope in (Public, Internal, Storage):
        decs = M.scope(scope).__pydantic_decorators__.model_validators
        assert "plain" not in decs


# --- partial interaction (the motivating Update case) ----------------------


def test_partial_projection_carries_before_validator() -> None:
    update = M.scope(Update)
    # all fields optional in a partial projection
    assert update().model_dump(exclude_none=True) == {}
    # the before-coercion still runs on the partial Update shape
    u = update(a="example.com/page")
    assert u.tag == "EXAMPLE.COM/PAGE"
    assert u.n == len("example.com/page")  # Storage 'after' carried too


# --- expression / union args ------------------------------------------------


def test_scoped_validator_accepts_expression() -> None:
    class N(ScopedModel):
        x: Annotated[str, scoped(Public)]

        @scoped_validator(Public | Other, mode="after")
        def v(self) -> "N":
            object.__setattr__(self, "x", self.x.strip())
            return self

    assert N.__prism_validator_scopes__["v"].atoms() == frozenset({Public, Other})
    assert N(x=" hi ").x == "hi"  # runs on the canonical model


# --- inheritance ------------------------------------------------------------


def test_scoped_validator_inherited_by_subclass() -> None:
    class Sub(M):
        extra: Annotated[str, scoped(Public)] = ""

    assert "derive_tag" in Sub.__prism_validator_scopes__
    sub_public = Sub.scope(Public)
    assert "derive_tag" in sub_public.__pydantic_decorators__.model_validators
    assert sub_public(a="yo").tag == "YO"


# --- errors -----------------------------------------------------------------


def test_no_scopes_raises() -> None:
    with pytest.raises(TypeError, match="at least one scope"):
        scoped_validator(mode="after")


def test_bad_scope_raises() -> None:
    with pytest.raises(TypeError):
        scoped_validator("storage", mode="after")  # type: ignore[arg-type]


def test_after_validator_on_dropped_field_fails_at_validation() -> None:
    """The scope list is the user's assertion; prism does not check field use."""

    class Bad(ScopedModel):
        keep: Annotated[str, scoped(Public)]
        gone: Annotated[str, scoped(Storage)] = ""

        @scoped_validator(Public, mode="after")
        def touches_gone(self) -> "Bad":
            _ = self.gone  # 'gone' is Storage; absent from a Public projection
            return self

    # On the canonical model 'gone' exists, so the validator is fine.
    assert Bad(keep="x").keep == "x"
    # On a Public projection 'gone' is dropped, so the carried validator fails.
    public = Bad.scope(Public)
    assert "gone" not in public.model_fields
    with pytest.raises((AttributeError, ValidationError)):
        public(keep="x")
