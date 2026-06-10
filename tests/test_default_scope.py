"""Class-level default scope: ``default_scope=`` fills untagged fields."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, Field

from pydantic_prism import (
    MISSING,
    EmptyProjectionError,
    Scope,
    ScopedModel,
    ScopeExpr,
    scoped,
)


class Ref(Scope): ...


class Public(Ref): ...


class Internal(Public): ...


class Storage(Internal): ...


class Update(Storage, partial=True): ...


# The motivating model: mostly-Storage rows, a couple of explicit deviations.
class Screenshot(ScopedModel, default_scope=Storage):
    id: Annotated[UUID, scoped(Ref)] = Field(default_factory=uuid4)
    website_id: Annotated[UUID, scoped(Public)]
    container_name: str  # implicitly scoped(Storage)
    blob_path: str  # implicitly scoped(Storage)
    md5_hash: str  # implicitly scoped(Storage)


def test_basic_untagged_fields_take_the_default() -> None:
    storage = Screenshot.scope(Storage)
    assert set(storage.model_fields) == {
        "id",
        "website_id",
        "container_name",
        "blob_path",
        "md5_hash",
    }


def test_explicit_marker_overrides_default_no_merge() -> None:
    """Replace, not merge: a tagged field ignores the class default."""
    assert repr(Screenshot.__field_scopes__["website_id"]) == "Public"
    # website_id is Public only — NOT Public | Storage. A pure-Ref projection
    # (narrower than Public) excludes it.
    ref_only = Screenshot.scope(Ref)
    assert set(ref_only.model_fields) == {"id"}


def test_default_scoped_fields_resolved_in_field_scopes() -> None:
    assert repr(Screenshot.__field_scopes__["container_name"]) == "Storage"
    assert repr(Screenshot.__field_scopes__["blob_path"]) == "Storage"
    assert repr(Screenshot.__field_scopes__["md5_hash"]) == "Storage"


def test_default_exposed_for_introspection() -> None:
    assert isinstance(Screenshot.__prism_default_scope__, ScopeExpr)
    assert repr(Screenshot.__prism_default_scope__) == "Storage"
    # A model without a default reports None.
    assert Plain.__prism_default_scope__ is None


def test_scopes_includes_default_scope_atoms() -> None:
    assert Storage in Screenshot.scopes()


# --- override via explicit scoped(...) -------------------------------------


def test_explicit_can_be_narrower_or_wider_than_default() -> None:
    class M(ScopedModel, default_scope=Internal):
        a: str  # Internal
        b: Annotated[str, scoped(Public)]  # narrower
        c: Annotated[str, scoped(Ref)]  # wider
        d: Annotated[str, scoped(Public, Storage)]  # explicit union

    assert repr(M.__field_scopes__["a"]) == "Internal"
    assert repr(M.__field_scopes__["b"]) == "Public"
    assert repr(M.__field_scopes__["c"]) == "Ref"
    assert M.__field_scopes__["d"].atoms() == frozenset({Public, Storage})


# --- multiple defaults via | -----------------------------------------------


def test_default_scope_accepts_an_expression() -> None:
    class Sibling(Scope): ...

    class M(ScopedModel, default_scope=Public | Sibling):
        a: str

    assert M.__field_scopes__["a"].atoms() == frozenset({Public, Sibling})


# --- inheritance -----------------------------------------------------------


def test_subclass_inherits_default() -> None:
    class Sub(Screenshot):
        note: str  # no own default declared -> inherits Storage

    assert repr(Sub.__field_scopes__["note"]) == "Storage"
    assert repr(Sub.__prism_default_scope__) == "Storage"


def test_subclass_override_redefaults_inherited_untagged_fields() -> None:
    class Sub(Screenshot, default_scope=Public):
        note: str

    # The subclass's new field takes the new default...
    assert repr(Sub.__field_scopes__["note"]) == "Public"
    # ...and an inherited *untagged* field re-defaults to it too.
    assert repr(Sub.__field_scopes__["container_name"]) == "Public"
    # An inherited *explicitly tagged* field keeps its own scope.
    assert repr(Sub.__field_scopes__["website_id"]) == "Public"
    assert repr(Sub.__field_scopes__["id"]) == "Ref"


def test_subclass_can_clear_default() -> None:
    class Sub(Screenshot, default_scope=None):
        note: str  # now genuinely untagged

    assert Sub.__prism_default_scope__ is None
    assert "note" not in Sub.__field_scopes__
    # Inherited untagged fields lose their default too.
    assert "container_name" not in Sub.__field_scopes__


# --- projection_bases interaction ------------------------------------------


class AzureTableBase(BaseModel):
    def envelope(self) -> str:
        return "azure"


def test_default_scope_with_projection_bases() -> None:
    class Row(
        AzureTableBase,
        ScopedModel,
        default_scope=Storage,
        projection_bases=(AzureTableBase,),
    ):
        id: Annotated[UUID, scoped(Public)] = Field(default_factory=uuid4)
        container_name: str  # Storage by default
        blob_path: str  # Storage by default

    storage = Row.scope(Storage)
    assert set(storage.model_fields) == {"id", "container_name", "blob_path"}
    # Carried base behavior survives alongside the default-scoped fields.
    assert issubclass(storage, AzureTableBase)
    assert storage(container_name="c", blob_path="b").envelope() == "azure"


# --- partial=True interaction ----------------------------------------------


def test_partial_flows_through_default_scoped_fields() -> None:
    update = Screenshot.scope(Update)
    # default-scoped Storage fields survive into the Update projection...
    assert "container_name" in update.model_fields
    instance = update()
    # ...and are optional (absent -> MISSING), exactly like explicit ones.
    assert instance.container_name is MISSING  # type: ignore[attr-defined]
    assert instance.md5_hash is MISSING  # type: ignore[attr-defined]
    assert update(container_name="c").model_dump() == {"container_name": "c"}


# --- error on bad value ----------------------------------------------------


def test_bad_default_scope_value_raises_at_class_definition() -> None:
    with pytest.raises(TypeError, match="Scope subclass or a scope expression"):

        class Bad(ScopedModel, default_scope="storage"):  # type: ignore[arg-type]
            x: str

    with pytest.raises(TypeError):

        class Bad2(ScopedModel, default_scope=42):  # type: ignore[arg-type]
            x: str


# --- backward compat: no default still raises on untagged-only -------------


class Plain(ScopedModel):
    x: Annotated[str, scoped(Public)]
    y: str  # genuinely untagged -> in no scope


def test_untagged_field_without_default_stays_scopeless() -> None:
    assert "y" not in Plain.__field_scopes__
    public = Plain.scope(Public)
    assert set(public.model_fields) == {"x"}


def test_all_untagged_no_default_still_raises_empty_projection() -> None:
    class AllUntagged(ScopedModel):
        a: str
        b: str

    with pytest.raises(EmptyProjectionError):
        AllUntagged.scope(Public)


# --- ref/backref fields take the default (uniform fallback) ----------------


def test_untagged_ref_field_takes_default() -> None:
    from pydantic_prism import ref

    class Target(ScopedModel, default_scope=Public):
        id: Annotated[UUID, scoped(Public)] = Field(default_factory=uuid4)

    class Source(ScopedModel, default_scope=Storage):
        id: Annotated[UUID, scoped(Public)] = Field(default_factory=uuid4)
        target_id: Annotated[UUID, ref(Target)]  # untagged -> Storage default

    assert repr(Source.__field_scopes__["target_id"]) == "Storage"
    storage = Source.scope(Storage)
    assert "target_id" in storage.model_fields
    # The ref edge survives onto the projection.
    assert "target_id" in storage.__refs__.outgoing
