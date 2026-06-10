"""Every README example, as a test. Mirrors README.md section by section.

The FastAPI section is covered verbatim by tests/test_fastapi.py.
"""

from typing import Annotated, Optional
from uuid import UUID

from pydantic_prism import Scope, ScopedModel, backref, ref, scoped

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
    assert Document.scope(Public | Internal) is Document.scope(Public, Internal)
    assert list(Document.scope(~Llm).model_fields) == ["owner_email", "embedding"]
    for scope in (Public, Internal, Storage, Llm):
        assert "note" not in Document.scope(scope).model_fields


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
    info = Order.__refs__["customer_id"]
    assert info.target is Customer
    assert info.target_field == "id"
    assert info.many is False
    assert info.optional is False
    assert info.kind == "ref"

    assert set(Order.__refs__.outgoing) == {"customer_id"}
    assert set(Customer.__refs__.incoming) == {"order_ids"}
    assert Order.__refs__.targets() == {Customer}
    assert [(src, edge.field_name) for src, edge in Order.__refs__.walk()] == [
        (Order, "customer_id")
    ]


def test_refs_survive_projection_example() -> None:
    OrderPublic = Order.scope(Public)
    assert OrderPublic.__refs__["customer_id"].target is Customer


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
