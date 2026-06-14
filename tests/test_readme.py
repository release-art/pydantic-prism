"""Every README example, as a test. Mirrors README.md section by section.

The FastAPI section is covered verbatim by tests/test_fastapi.py.
"""

from typing import Annotated, Any, Optional
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field

from pydantic_prism import (
    MISSING,
    RefShape,
    Scope,
    ScopedModel,
    backref,
    projection_diagram,
    ref,
    scope_diagram,
    scoped,
    scoped_validator,
)

# --- "30 seconds" ----------------------------------------------------------


class Public(Scope): ...


class Internal(Public): ...  # Internal sees everything Public sees


class Storage(Internal): ...  # Storage sees everything Internal sees


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    password_hash: Annotated[str, scoped(Storage)]
    display_name: Annotated[str, scoped(Public)]


UserPublic = User.scope(Public)
UserInternal = User.scope(Internal)
UserStorage = User.scope(Storage)


def test_thirty_second_example() -> None:
    assert list(UserPublic.model_fields) == ["id", "display_name"]
    assert list(UserInternal.model_fields) == ["id", "email", "display_name"]
    assert list(UserStorage.model_fields) == [
        "id",
        "email",
        "password_hash",
        "display_name",
    ]
    assert UserPublic.__name__ == "UserPublic"
    assert User.scope(Public) is User.scope(Public)


# --- "Scopes are classes" --------------------------------------------------


class Llm(Scope): ...


class Document(ScopedModel):
    body: Annotated[str, scoped(Scope)]  # wildcard: every scope
    owner_email: Annotated[str, scoped(Scope - Llm)]  # everywhere except Llm
    embedding: Annotated[
        list[float], scoped(Internal & Llm)
    ]  # only scopes that are both
    note: str = ""  # untagged: no scope, canonical only


def test_scope_algebra_example() -> None:
    assert list(Document.scope(Llm).model_fields) == ["body"]
    assert list(Document.scope(Public | Internal).model_fields) == [
        "body",
        "owner_email",
    ]
    assert Document.scope(Public | Internal) is Document.scope(Internal | Public)
    assert list(Document.scope(~Llm).model_fields) == ["owner_email", "embedding"]
    for scope in (Public, Internal, Storage, Llm):
        assert "note" not in Document.scope(scope).model_fields


# --- "Class-level default scope" -------------------------------------------


class Ref(Scope): ...


class StoragePublic(Ref): ...  # the README's "Public" under a "Ref" root


class StorageScope(StoragePublic): ...  # the README's "Storage"


class Screenshot(ScopedModel, default_scope=StorageScope):
    id: Annotated[UUID, scoped(Ref)]
    website_id: Annotated[UUID, scoped(StoragePublic)]
    container_name: str  # implicitly StorageScope
    blob_path: str  # implicitly StorageScope
    md5_hash: str  # implicitly StorageScope


def test_default_scope_example() -> None:
    assert list(Screenshot.scope(StorageScope).model_fields) == [
        "id",
        "website_id",
        "container_name",
        "blob_path",
        "md5_hash",
    ]
    # explicit replaces, not merges: website_id is StoragePublic only
    assert list(Screenshot.scope(Ref).model_fields) == ["id"]
    assert repr(Screenshot.__prism__.default_scope) == "StorageScope"
    assert repr(Screenshot.__prism__.field_scopes["container_name"]) == "StorageScope"


# --- "Relationships" -------------------------------------------------------


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    order_ids: Annotated[
        list[UUID], backref("Order", via="customer_id"), scoped(Internal)
    ]


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
    total: Annotated[str, scoped(Internal)]


def test_relationships_example() -> None:
    info = Order.__prism__.refs["customer_id"]
    assert info.target is Customer
    assert info.target_field == "id"
    assert info.many is False
    assert info.optional is False
    assert info.kind == "ref"

    assert set(Order.__prism__.refs.outgoing) == {"customer_id"}
    assert set(Customer.__prism__.refs.incoming) == {"order_ids"}
    assert Order.__prism__.refs.targets() == {Customer}
    assert [(src, edge.field_name) for src, edge in Order.__prism__.refs.walk()] == [
        (Order, "customer_id")
    ]


def test_refs_survive_projection_example() -> None:
    OrderPublic = Order.scope(Public)
    assert OrderPublic.__prism__.refs["customer_id"].target is Customer


# --- "Nested models" -------------------------------------------------------


class Address(ScopedModel):
    city: Annotated[str, scoped(Public)]
    plus_code: Annotated[str, scoped(Internal)] = ""


class Shipment(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    destination: Annotated[Address | None, scoped(Public)] = None


def test_nested_models_example() -> None:
    ShipmentPublic = Shipment.scope(Public)
    annotation = ShipmentPublic.model_fields["destination"].annotation
    assert annotation == Optional[Address.scope(Public)]  # noqa: UP045


# --- "Round trips" ---------------------------------------------------------


def test_round_trips_example() -> None:
    user = UserStorage(
        id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
        email="ada@example.com",
        password_hash="hash",
        display_name="Ada",
    )

    pub = UserPublic.from_canonical(user)
    assert set(pub.model_dump()) == {"id", "display_name"}

    back = User.from_projection(pub, email="ada@example.com", password_hash="hash")
    assert isinstance(back, User)
    assert back.email == "ada@example.com"


# --- "Round trips: with_updates" -------------------------------------------


class Account(ScopedModel):
    name: Annotated[str, scoped(Public)]
    status: Annotated[str, scoped(Storage)] = "active"


def test_with_updates_example() -> None:
    acct = Account(name="ada")
    patch = Account.scope(Update)(name="ADA")
    updated = acct.with_updates(patch)
    assert updated.name == "ADA"
    assert updated.status == "active"
    assert acct.name == "ada"  # original unchanged


# --- "Naming projections" --------------------------------------------------


class Doc(ScopedModel, projection_name_template="{model}_{scope}"):
    body: Annotated[str, scoped(Public)]


def test_naming_projections_example() -> None:
    assert Doc.scope(Public).__name__ == "Doc_Public"
    assert Doc.scope(Public | Internal).__name__ == "Doc_InternalOrPublic"


# --- "Per-scope schema metadata" -------------------------------------------


class Viewer(Scope, description="Public-facing view"): ...


class Auditor(Viewer): ...


class Person(ScopedModel):
    email: Annotated[
        str,
        scoped(Viewer, override=Field(description="User contact (public-facing)")),
        scoped(
            Auditor, override=Field(description="User identity, for internal audit")
        ),
    ]


def test_diagrams_example() -> None:
    assert "classDiagram" in scope_diagram(Update).to_mermaid()
    assert "digraph prism" in projection_diagram(User).to_dot()
    assert "direction: down" in User.__prism__.refs.diagram().to_d2()
    assert "nodes" in scope_diagram().as_dict()


def test_per_scope_schema_example() -> None:
    viewer = Person.scope(Viewer).model_json_schema()
    auditor = Person.scope(Auditor).model_json_schema()
    assert viewer["properties"]["email"]["description"] == (
        "User contact (public-facing)"
    )
    assert auditor["properties"]["email"]["description"] == (
        "User identity, for internal audit"
    )
    assert viewer["description"] == "Public-facing view"  # model-level


# --- "Dict-keyed refs" -----------------------------------------------------


class Highlight(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    text: Annotated[str, scoped(Public)]


class Page(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    highlights: Annotated[dict[UUID, Highlight], ref(Highlight), scoped(Public)]


def test_dict_keyed_refs_example() -> None:
    info = Page.__prism__.refs["highlights"]
    assert info.shape is RefShape.KEYED_DICT
    assert info.key_type is UUID
    assert info.target is Highlight


# --- "Embedded models and carrier records" ---------------------------------


class CarrierScope(Scope): ...


class Snapshot(ScopedModel):
    id: Annotated[UUID, scoped(Public, CarrierScope)]
    taken_at: Annotated[str, scoped(Public, CarrierScope)]
    blob: Annotated[str, scoped(Public)] = ""


SnapshotRef = Snapshot.scope(CarrierScope)


class SnapshotOwner(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    history: Annotated[list[SnapshotRef], scoped(Public)] = []  # type: ignore[valid-type]
    by_id: Annotated[dict[UUID, SnapshotRef], scoped(Public)] = {}  # type: ignore[valid-type]


def test_embedded_carrier_example() -> None:
    info = SnapshotOwner.__prism__.refs["history"]
    assert info.kind == "embedded"
    assert info.target is Snapshot
    assert info.scope == SnapshotRef.__prism__.scope
    assert info.shape is RefShape.COLLECTION
    assert "history" in SnapshotOwner.__prism__.refs.embedded
    assert "history" not in SnapshotOwner.__prism__.refs.outgoing


# --- "Custom pydantic bases" -----------------------------------------------


class AzureTableBase(BaseModel):
    def table_name(self) -> str:
        return type(self).__name__.lower()


class Row(AzureTableBase, ScopedModel, projection_bases=(AzureTableBase,)):
    id: Annotated[UUID, scoped(Public)]


def test_custom_bases_example() -> None:
    RowPublic = Row.scope(Public)
    instance = RowPublic(id="00000000-0000-0000-0000-000000000001")  # type: ignore[arg-type]
    assert isinstance(instance, AzureTableBase)
    assert instance.table_name() == "rowpublic"


# --- "Partial scopes — the Update model" -----------------------------------


class Update(Storage, partial=True): ...


class CanonicalRow(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    status: Annotated[str, scoped(Storage)] = "active"


def test_partial_scope_example() -> None:
    RowUpdate = CanonicalRow.scope(Update)
    assert RowUpdate().name is MISSING  # type: ignore[attr-defined]  # absent
    assert RowUpdate().model_dump() == {}  # MISSING auto-omitted
    assert RowUpdate(name="new").model_dump() == {"name": "new"}
    assert "required" not in RowUpdate.model_json_schema()


# --- "@scoped_validator" ----------------------------------------------------


class Webpage(ScopedModel):
    url: Annotated[str, scoped(Public)]
    hostname: Annotated[str, scoped(Public)] = ""

    @scoped_validator(Update, mode="before")  # carries to Update and broader
    @classmethod
    def derive_hostname(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("url") and not data.get("hostname"):
            data = {**data, "hostname": urlparse(data["url"]).hostname or ""}
        return data


def test_scoped_validator_example() -> None:
    update = Webpage.scope(Update)
    derived = update(url="https://example.com/page")
    assert derived.hostname == "example.com"  # type: ignore[attr-defined]
    assert "derive_hostname" in update.__pydantic_decorators__.model_validators
    assert repr(Webpage.__prism__.validator_scopes["derive_hostname"]) == "Update"
