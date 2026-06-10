"""SQLAlchemy ORM bridge: prism canonical mirrors the row, faces derive from it.

Run from the repository root:

    pdm run python examples/sqlalchemy_orm/main.py

Unlike SQLModel (where the table model *is* a pydantic model — see
``examples/sqlmodel_bridge/``), a raw SQLAlchemy ORM row is **not** a pydantic
model, so it cannot be a prism canonical or a carried projection base. The bridge
is instead a thin mirror:

  * the ORM class (``OrderRow``) owns persistence;
  * a ``ScopedModel`` (``Order``) mirrors its columns and owns the *shapes*;
  * ``model_config = ConfigDict(from_attributes=True)`` lets the canonical read a
    live ORM row directly (``Order.model_validate(row)``), and every API / admin
    / PATCH face is then derived with ``Order.scope(...)`` — no hand-written DTOs.

prism does no storage, sessions, or lazy loading: the ORM stays in charge of the
database, prism only projects. The reverse trip is just as plain — a canonical's
fields construct or update an ORM row (``OrderRow(**order.model_dump())``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict
from sqlalchemy import ForeignKey, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from pydantic_prism import Scope, ScopedModel, ref, scoped


# --- visibility ladder ------------------------------------------------------
class Api(Scope): ...  # public API response


class Internal(Api): ...  # admin/internal view


# --- raw SQLAlchemy 2.0 declarative ORM (owns persistence) ------------------
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
    total: Mapped[Decimal]
    internal_note: Mapped[str] = mapped_column(default="")


# --- prism canonicals mirror the rows; from_attributes bridges reads --------
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


# --- the derived faces ------------------------------------------------------
OrderApi = Order.scope(Api)  # public response: id, customer_id, total
OrderAdmin = Order.scope(Internal)  # adds internal_note


def demo() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(CustomerRow(id=1, name="Ada", email="ada@example.com"))
        session.add(
            OrderRow(id=1, customer_id=1, total=Decimal("42.00"), internal_note="rush")
        )
        session.commit()

        # read a live ORM row straight into the prism canonical
        row = session.execute(select(OrderRow)).scalar_one()
        order = Order.model_validate(row)
        print(f"ORM row -> canonical: {order.model_dump()}")

        # derive the faces from the canonical
        api = OrderApi.from_canonical(order)
        admin = OrderAdmin.from_canonical(order)
        print(f"Api face  (no internal_note): {api.model_dump()}")
        print(f"Admin face (with note):       {admin.model_dump()}")
        assert "internal_note" not in api.model_dump()

        # the ref graph spans the mirrored models
        print(f"Order.customer_id -> {Order.__refs__['customer_id'].target.__name__}")

        # reverse trip: a canonical writes back to a new ORM row (prism does no I/O)
        clone = OrderRow(**order.model_dump())
        clone.id = 2
        session.add(clone)
        session.commit()
        print(f"wrote back as order id={clone.id}")


if __name__ == "__main__":
    demo()
