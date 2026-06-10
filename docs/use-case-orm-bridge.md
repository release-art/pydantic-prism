# Use case — ORM / SQLModel bridge recipe

Captured 2026-06-10 (market/feature dive). Positioning + feature note, parked
for the docs restructure.

## The opening

SQLModel's one-model promise is **officially admitted to break down**: its own
[docs](https://sqlmodel.tiangolo.com/tutorial/fastapi/multiple-models/) concede
"in most cases there are slight differences" and you end up hand-writing
`Create` / `Update` / `Public` / table models anyway. That is a large, warm,
already-frustrated audience hitting exactly the problem prism solves — but they
think of their canonical model as *the database row*, not as a pydantic model to
project from.

## Why prism already fits

The `projection_bases=` / `bases=` feature (see
[`examples/custom_base/main.py`](../examples/custom_base/main.py), the Azure
Table row case) is the bridge — it already carries a custom base's
`model_dump` / validators / `isinstance` identity onto projections. The pattern
is: **canonical = the ORM/row class, projections = API / LLM / audit views.**

```
canonical:   OrderRow(SQLModelBase, ScopedModel, projection_bases=(SQLModelBase,))
projections: OrderRow.scope(Public)   # API response
             OrderRow.scope(Update)   # PATCH body
             OrderRow.scope(Llm)      # tool input
```

One source of truth (the row), every face derived — and refs/`__refs__` give the
relationship graph SQLModel's `Relationship()` only half-models.

## The bet

Mostly **a documented recipe + example**, not new engine code:

- A worked `examples/sqlmodel_bridge/` (or a docs page) showing canonical = table
  model, the four derived faces, and the round-trips.
- Pressure-test `projection_bases=` against SQLModel / SQLAlchemy declarative
  bases specifically (metaclass interactions, `table=True`, `Relationship`
  fields) — the custom-base machinery exists but hasn't been exercised against
  an ORM metaclass; that's the real risk to retire.
- Honest boundary: prism still does **no** storage, sessions, or lazy loading
  (consistent with the "storage is your problem" stance). The pitch is "stop
  hand-writing the DTO zoo around your ORM model", not "replace your ORM".

## Spike results (2026-06-10) — risk retired

Tested against **SQLModel 0.0.38 / SQLAlchemy 2.0.50 / pydantic 2.13** (sqlmodel
added to dev deps). Worked example: [`examples/sqlmodel_bridge/`](../examples/sqlmodel_bridge/main.py);
locked by [`tests/test_sqlmodel_bridge.py`](../tests/test_sqlmodel_bridge.py).

**Works, no engine changes:**

- **Co-existence is free.** `class Order(SQLModel, ScopedModel, table=True)`
  defines with no custom metaclass — `SQLModelMetaclass` already subclasses
  pydantic's `ModelMetaclass`, so the combined metaclass resolves. prism collects
  scope tags off the same fields; the class is a real SQLAlchemy table.
- **The core bridge holds.** `Model.scope(...)` filters the table model into
  plain pydantic DTOs; `from_canonical` projects a *live, queried* SQLite row;
  `with_updates` applies a partial PATCH back onto a row.
- **Refs coexist.** `ref()`/`__refs__` run over the foreign keys; a SQLAlchemy
  `Relationship()` is not a pydantic field, so prism never sees it.
- **Carrying a *plain* pydantic base onto a projection works** (per-call
  `bases=(PlainMixin,)`): the DTO keeps the base's methods/`isinstance` and is
  itself not a table.

**Two boundaries (documented, not blockers):**

1. **SQLModel's metaclass swallows prism's class keywords.** On a `table=True`
   model, `default_scope=` / `projection_bases=` / `projection_name_template=`
   never reach `ScopedModel.__init_subclass__` and are silently dropped. Tag
   every field explicitly and use the per-call forms (`scope(..., bases=...)`).
2. **You cannot carry a `SQLModel` base onto a projection.** The synthetic
   projection base would inherit SQLAlchemy's declarative machinery, which then
   tries to map a class with no table/PK and raises `ArgumentError`. This is the
   right boundary anyway — DTO projections should not be ORM-instrumented; carry
   plain bases or `bases=()`.

Net: the bet ("a documented recipe + example, not new engine code") holds. The
pitch — *stop hand-writing the DTO zoo around your SQLModel table* — is real and
needs no storage scope from prism.

## Raw SQLAlchemy (no SQLModel) — the mirror recipe

Tested separately against **SQLAlchemy 2.0.50** declarative ORM (added to dev
deps). Example: [`examples/sqlalchemy_orm/`](../examples/sqlalchemy_orm/main.py);
locked by [`tests/test_sqlalchemy_bridge.py`](../tests/test_sqlalchemy_bridge.py).

A raw ORM row is **not** a pydantic model, so it can be neither a prism canonical
nor a carried base (`scope(..., bases=(OrderRow,))` raises the expected "not a
pydantic BaseModel subclass" `TypeError`). The bridge is therefore a **mirror**,
not a merge:

- the ORM class (`DeclarativeBase` + `Mapped`/`mapped_column`) owns persistence;
- a `ScopedModel` mirrors its columns and owns the *shapes*;
- `model_config = ConfigDict(from_attributes=True)` lets the canonical read a
  live ORM row directly (`Order.model_validate(row)`), and `Order.scope(...)`
  derives the faces; the reverse trip is plain (`OrderRow(**order.model_dump())`).

Confirmed: read-via-`from_attributes`, derive faces, write back, and the ref
graph across mirrored models all work. This is the cleaner fit for prism's
"storage is your problem" stance — the ORM is untouched, prism only projects.
The tradeoff vs SQLModel is one extra mirror class per table (you write the
columns twice), bought back by zero metaclass entanglement and no swallowed
keywords.
