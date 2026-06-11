"""Integration: raw SQLAlchemy ORM rows bridged to prism canonicals.

The other half of ``docs/use-case-orm-bridge.md``. A SQLAlchemy ORM row is *not*
a pydantic model, so (unlike SQLModel) it cannot be a canonical or a carried
base. The bridge is a mirror: a ``ScopedModel`` mirrors the columns and reads a
live row via ``from_attributes=True``; projections derive from it. Confirms the
read/derive/write-back round trip, the ref graph, and that an ORM class is
rejected as a projection base.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated

import pytest
from pydantic import ConfigDict
from sqlalchemy import ForeignKey, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from pydantic_prism import Scope, ScopedModel, ref, scoped


class Api(Scope): ...


class Internal(Api): ...


class Base(DeclarativeBase): ...


class CustomerRow(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]


class OrderRow(Base):
    __tablename__ = "order"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
    total: Mapped[Decimal] = mapped_column()
    internal_note: Mapped[str] = mapped_column(default="")


class Customer(ScopedModel):
    model_config = ConfigDict(from_attributes=True)
    id: Annotated[int, scoped(Api)]
    name: Annotated[str, scoped(Api)]
    email: Annotated[str, scoped(Internal)]


class Order(ScopedModel):
    model_config = ConfigDict(from_attributes=True)
    id: Annotated[int, scoped(Api)]
    customer_id: Annotated[int, ref(Customer), scoped(Api)]
    total: Annotated[Decimal, scoped(Api)]
    internal_note: Annotated[str, scoped(Internal)]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as seeded:
        seeded.add(CustomerRow(id=1, name="Ada", email="ada@example.com"))
        seeded.add(
            OrderRow(id=1, customer_id=1, total=Decimal("42"), internal_note="rush")
        )
        seeded.commit()
        yield seeded
    engine.dispose()


def test_from_attributes_reads_a_live_orm_row(session: Session) -> None:
    row = session.execute(select(OrderRow)).scalar_one()
    order = Order.model_validate(row)  # ORM row -> prism canonical
    assert order.model_dump() == {
        "id": 1,
        "customer_id": 1,
        "total": Decimal("42"),
        "internal_note": "rush",
    }


def test_faces_derive_from_the_mirrored_canonical(session: Session) -> None:
    row = session.execute(select(OrderRow)).scalar_one()
    order = Order.model_validate(row)
    api_face = Order.scope(Api)
    api = api_face.from_canonical(order)
    assert set(api_face.model_fields) == {"id", "customer_id", "total"}
    assert "internal_note" not in api.model_dump()


def test_ref_graph_spans_the_mirrored_models() -> None:
    assert Order.__refs__["customer_id"].target is Customer


def test_write_back_to_a_new_orm_row(session: Session) -> None:
    order = Order.model_validate(session.execute(select(OrderRow)).scalar_one())
    clone = OrderRow(**{**order.model_dump(), "id": 2})  # canonical -> ORM row
    session.add(clone)
    session.commit()
    stored = session.get(OrderRow, 2)
    assert stored is not None
    assert stored.total == Decimal("42")


def test_orm_class_is_rejected_as_a_projection_base() -> None:
    # A SQLAlchemy ORM class is not a pydantic BaseModel, so it cannot be carried.
    with pytest.raises(TypeError, match="not a pydantic BaseModel subclass"):
        Order.scope(Api, bases=(OrderRow,))  # pyright: ignore[reportArgumentType]
