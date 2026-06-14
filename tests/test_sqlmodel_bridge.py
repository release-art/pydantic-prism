"""Integration: SQLModel table models as prism canonicals (the ORM bridge).

Retires the metaclass risk from ``docs/use-case-orm-bridge.md``. Confirms what
works (co-existence, scope filtering over a live SQLite row, partial PATCH, ref
graph, carrying a *plain* base) and pins the two real boundaries (SQLModel's
metaclass swallows prism's class keywords; carrying a *SQLModel* base onto a
projection makes SQLAlchemy try to map it and fails).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

import pytest
from pydantic import BaseModel
from sqlalchemy.exc import ArgumentError
from sqlmodel import Field as Col
from sqlmodel import Session, SQLModel, create_engine, select

from pydantic_prism import Scope, ScopedModel, ref, scoped


class Api(Scope): ...


class Internal(Api): ...


class Storage(Internal): ...


class Update(Storage, partial=True): ...


class Account(SQLModel, ScopedModel, table=True):
    __tablename__ = "t_account"
    id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
    name: Annotated[str, scoped(Api)] = Col()
    email: Annotated[str, scoped(Internal)] = Col()


class Invoice(SQLModel, ScopedModel, table=True):
    __tablename__ = "t_invoice"
    id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
    account_id: Annotated[int | None, ref(Account), scoped(Api)] = Col(
        default=None, foreign_key="t_account.id"
    )
    total: Annotated[Decimal, scoped(Api)] = Col()
    internal_note: Annotated[str, scoped(Internal)] = Col(default="")


# --- co-existence -----------------------------------------------------------


def test_canonical_is_both_sqlmodel_and_scopedmodel() -> None:
    assert issubclass(Invoice, SQLModel)
    assert issubclass(Invoice, ScopedModel)
    assert Invoice.__tablename__ == "t_invoice"  # a real SQLAlchemy table
    # prism collected the scope tags off the same fields
    assert set(Invoice.__prism__.field_scopes) == {
        "id",
        "account_id",
        "total",
        "internal_note",
    }


def test_scope_filters_the_table_model() -> None:
    api = Invoice.scope(Api, bases=())
    assert set(api.model_fields) == {"id", "account_id", "total"}
    assert "internal_note" not in api.model_fields  # Internal-only, dropped
    assert not issubclass(api, SQLModel)  # the projection is a plain DTO


def test_ref_graph_resolves_across_table_models() -> None:
    edge = Invoice.__prism__.refs["account_id"]
    assert edge.target is Account
    assert edge.target_field == "id"


# --- live persistence round-trip -------------------------------------------


def test_persist_query_and_project_a_live_row() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            acct = Account(name="Ada", email="ada@example.com")
            session.add(acct)
            session.commit()
            session.refresh(acct)
            session.add(
                Invoice(account_id=acct.id, total=Decimal("42"), internal_note="x")
            )
            session.commit()

            row = session.exec(select(Invoice)).one()
            api = Invoice.scope(Api, bases=()).from_canonical(row)
            assert api.model_dump() == {
                "id": row.id,
                "account_id": acct.id,
                "total": Decimal("42"),
            }
            assert "internal_note" not in api.model_dump()
    finally:
        engine.dispose()


def test_partial_patch_applies_back_onto_a_row() -> None:
    row = Invoice(account_id=1, total=Decimal("10"), internal_note="before")
    patch = Invoice.scope(Update, bases=())(internal_note="after")
    updated = row.with_updates(patch)
    assert updated.internal_note == "after"
    assert updated.total == Decimal("10")  # untouched fields preserved


# --- carrying bases: plain works, SQLModel base does not --------------------


def test_plain_pydantic_base_carries_onto_a_projection() -> None:
    class Audited(BaseModel):
        def audit(self) -> str:
            return "audited"

    class Ledger(Audited, SQLModel, ScopedModel, table=True):
        __tablename__ = "t_ledger"
        id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
        amount: Annotated[Decimal, scoped(Api)] = Col()

    proj = Ledger.scope(Api, bases=(Audited,), name="LedgerApiAudited")
    inst = proj(id=1, amount=Decimal("1"))
    assert isinstance(inst, Audited)
    assert inst.audit() == "audited"
    assert not issubclass(proj, SQLModel)  # still a plain DTO, not a table


def test_carrying_a_sqlmodel_base_raises() -> None:
    # A projection inheriting a SQLModel base makes SQLAlchemy try to map the
    # synthetic class — which has no table/PK — and fail. This is why DTO
    # projections must carry only plain pydantic bases (or none).
    class SQLAudit(SQLModel): ...

    class Receipt(SQLAudit, ScopedModel, table=True):
        __tablename__ = "t_receipt"
        id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
        amount: Annotated[Decimal, scoped(Api)] = Col()

    with pytest.raises(ArgumentError, match="could not assemble any primary key"):
        Receipt.scope(Api, bases=(SQLAudit,), name="ReceiptCarrySql")


# --- the swallowed-keyword boundary -----------------------------------------


def test_sqlmodel_metaclass_swallows_prism_class_keywords() -> None:
    # On a table=True model, SQLModel's metaclass does not forward prism's class
    # keywords to ScopedModel.__init_subclass__, so they are silently dropped.
    # Workaround: tag every field and use the per-call scope(..., bases=) form.
    class Widget(
        SQLModel,
        ScopedModel,
        table=True,
        default_scope=Api,
        projection_name_template="{model}__{scope}",
    ):
        __tablename__ = "t_widget"
        id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
        untagged: str = Col(default="")

    assert Widget.__prism__.default_scope is None  # default_scope was dropped
    assert Widget.__prism__.name_template is None  # template was dropped
    assert Widget.__prism__.field_scopes.get("untagged") is None  # no default applied
    # control: the same keywords take effect on a plain (non-SQLModel) ScopedModel
    assert Account.scope(Api, bases=()).__name__ == "AccountApi"
