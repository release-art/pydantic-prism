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

## Open questions

- Does an ORM declarative metaclass co-exist with `ScopedModel`'s class
  machinery without a custom metaclass merge? Needs a spike before promising it.
- If it mostly works, this is high-leverage: it reaches the SQLModel audience
  without prism taking on any storage scope.
