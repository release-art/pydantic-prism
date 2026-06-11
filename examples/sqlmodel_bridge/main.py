"""SQLModel bridge: one table model, many derived faces (API / admin / PATCH).

Run from the repository root:

    pdm run python examples/sqlmodel_bridge/main.py

SQLModel's "one model" promise officially breaks down — its own docs concede you
end up hand-writing ``Create`` / ``Update`` / ``Public`` models around the table
model. prism is that missing half: the **canonical model is the SQLModel table
row**, and every API/admin/PATCH face is *derived* from it by tagging fields with
scopes — no parallel DTO classes to keep in sync.

    class Order(SQLModel, ScopedModel, table=True): ...   # the row
    Order.scope(Api)        # public response DTO
    Order.scope(Internal)   # admin view
    Order.scope(Update)     # PATCH body (partial)

A ``ScopedModel`` composes with a ``SQLModel`` table model directly:
``SQLModelMetaclass`` already subclasses pydantic's ``ModelMetaclass``, so the
two co-exist with no custom metaclass. prism's ``ref()`` graph runs over the
foreign keys; a SQLAlchemy ``Relationship()`` can be declared alongside as usual
(it is not a pydantic field, so prism never sees it) — omitted here only to keep
the example a single runnable file.

Two boundaries worth knowing (see ``tests/test_sqlmodel_bridge.py``):

* **Projections are plain pydantic DTOs, never tables.** You would not want an
  API-response model carrying SQLAlchemy instrumentation, and prism cannot give
  you one: carrying a ``SQLModel`` base onto a projection makes SQLAlchemy try to
  map the derived class and fails. Carry only *plain* pydantic bases (or none).
* **prism's class keywords don't survive SQLModel's metaclass.** ``table=True``
  models silently drop ``default_scope=`` / ``projection_bases=`` /
  ``projection_name_template=``. Tag every field explicitly and use the per-call
  forms (``Model.scope(..., bases=...)``) instead.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from sqlmodel import Field as Col
from sqlmodel import Session, SQLModel, create_engine, select

from pydantic_prism import Scope, ScopedModel, ref, scoped


# --- visibility ladder ------------------------------------------------------
class Api(Scope): ...  # public API response


class Internal(Api): ...  # admin/internal view


class Storage(Internal): ...  # the full persisted row


class Update(Storage, partial=True): ...  # PATCH body (every field optional)


# --- the table models (canonical = the row) ---------------------------------
class Customer(SQLModel, ScopedModel, table=True):
    id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
    name: Annotated[str, scoped(Api)] = Col()
    email: Annotated[str, scoped(Internal)] = Col()


class Order(SQLModel, ScopedModel, table=True):
    id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
    customer_id: Annotated[int | None, ref(Customer), scoped(Api)] = Col(
        default=None, foreign_key="customer.id"
    )
    total: Annotated[Decimal, scoped(Api)] = Col()
    internal_note: Annotated[str, scoped(Internal)] = Col(default="")


# --- the derived faces ------------------------------------------------------
# bases=() opts each projection out of carrying the SQLModel base (so they are
# plain DTOs, not tables). The class-level projection_bases=() would be cleaner
# but SQLModel's metaclass swallows it, so the per-call form is the way.
OrderApi = Order.scope(Api, bases=())  # public response: id, customer_id, total
OrderAdmin = Order.scope(Internal, bases=())  # adds internal_note
OrderPatch = Order.scope(Update, bases=())  # partial body for PATCH


def demo() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        ada = Customer(name="Ada", email="ada@example.com")
        session.add(ada)
        session.commit()
        session.refresh(ada)
        order = Order(customer_id=ada.id, total=Decimal("42.00"), internal_note="rush")
        session.add(order)
        session.commit()
        session.refresh(order)

        print(f"persisted row: {order.model_dump()}")

        # project the live row to each face — canonical-only fields are dropped
        api = OrderApi.from_canonical(order)
        admin = OrderAdmin.from_canonical(order)
        print(f"Api face  (no internal_note): {api.model_dump()}")
        print(f"Admin face (with note):       {admin.model_dump()}")
        assert "internal_note" not in api.model_dump()

        # a PATCH delta applied back onto the canonical row
        patch = OrderPatch(internal_note="shipped")
        updated = order.with_updates(patch)
        print(f"after PATCH: internal_note={updated.internal_note!r}")

        # the ref graph still resolves across the table models
        print(f"Order.customer_id -> {Order.__refs__['customer_id'].target.__name__}")

        # ordinary SQLAlchemy querying is untouched
        found = session.exec(select(Order).where(Order.total > 10)).all()
        print(f"queried {len(found)} order(s) over $10")


if __name__ == "__main__":
    demo()
