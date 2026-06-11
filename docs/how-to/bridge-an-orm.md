# Bridge a SQLModel or SQLAlchemy ORM

**Goal:** make your ORM model the single source of truth and derive the
API/admin/PATCH faces from it — instead of hand-writing the Create/Update/Public
DTO zoo. Prism does no storage; your ORM stays in charge of persistence.

## SQLModel — the table *is* the canonical

Compose `SQLModel` and `ScopedModel` directly and tag the columns with scopes.
Derive each face with `bases=()` so projections are plain pydantic DTOs, not
tables.

```python
from typing import Annotated
from decimal import Decimal

from sqlmodel import Field as Col, SQLModel

from pydantic_prism import Scope, ScopedModel, ref, scoped


class Api(Scope): ...
class Internal(Api): ...
class Update(Internal, partial=True): ...


class Order(SQLModel, ScopedModel, table=True):
    id: Annotated[int | None, scoped(Api)] = Col(default=None, primary_key=True)
    total: Annotated[Decimal, scoped(Api)] = Col()
    internal_note: Annotated[str, scoped(Internal)] = Col(default="")


OrderApi = Order.scope(Api, bases=())        # public response: id, total
OrderAdmin = Order.scope(Internal, bases=())  # adds internal_note
OrderPatch = Order.scope(Update, bases=())    # all-optional PATCH body
```

Build a face from a persisted row with `OrderApi.from_canonical(order)`, and
apply a PATCH delta with `order.with_updates(patch)`.

> [!WARNING]
> Two SQLModel-specific boundaries:
> - **Projections must be plain DTOs.** Carrying a `SQLModel` base onto a
>   projection makes SQLAlchemy try to map the derived class and fail — always
>   pass `bases=()`.
> - **SQLModel's metaclass swallows prism's class keywords.** `default_scope=`,
>   `projection_bases=`, and `projection_name_template=` never reach
>   `ScopedModel` on a `table=True` model. Tag every field explicitly and use
>   the per-call `scope(..., bases=...)` form.

## SQLAlchemy — mirror the row

A raw SQLAlchemy row is not a pydantic model, so it can't be a canonical or a
carried base. Mirror its columns in a `ScopedModel` that reads the live row via
`from_attributes`:

```python
from pydantic import ConfigDict


class Order(ScopedModel):
    model_config = ConfigDict(from_attributes=True)
    id: Annotated[int, scoped(Api)]
    total: Annotated[Decimal, scoped(Api)]
    internal_note: Annotated[str, scoped(Internal)]


# order = Order.model_validate(row)   # read a live ORM row into the canonical
# api = Order.scope(Api).from_canonical(order)
```

The bridge is a **mirror**, not a merge: prism projects the shape, the ORM owns
the database. Runnable: [`examples/sqlmodel_bridge`](../../examples/sqlmodel_bridge),
[`examples/sqlalchemy_orm`](../../examples/sqlalchemy_orm).
