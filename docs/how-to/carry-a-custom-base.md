# Carry a custom pydantic base onto projections

**Goal:** keep a custom base class's behavior — overridden `model_dump`, model
validators, helper methods, `isinstance` identity — on the derived projections.

By default a projection is built on a fresh `Projection` base and does **not**
inherit your canonical's custom base. Declare `projection_bases=` to carry it.

```python
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...
class Storage(Public): ...


class TableRowBase(BaseModel):
    def table_name(self) -> str:
        return type(self).__name__.lower()


class Row(TableRowBase, ScopedModel, projection_bases=(TableRowBase,)):
    id: Annotated[UUID, scoped(Public)]
    api_key: Annotated[str, scoped(Storage)]


RowPublic = Row.scope(Public)
row = RowPublic(id=uuid4())

assert isinstance(row, TableRowBase)          # identity preserved
assert row.table_name() == "rowpublic"        # base method works
assert "api_key" not in RowPublic.model_fields  # Storage-only field still dropped
```

`projection_bases=` sets the default for every `.scope()` call and is inherited
by subclasses. Override per call with `bases=`, or opt out with `bases=()`:

```python
RowFlat = Row.scope(Public, bases=(), name="RowFlat")
assert not issubclass(RowFlat, TableRowBase)  # plain projection, no base behavior
```

> [!WARNING]
> **Fields declared on a carried base are inherited by every projection** —
> pydantic cannot remove inherited fields. Treat them as infrastructure fields.
> If a base-declared field is tagged with a scope the expression doesn't
> select, `.scope()` raises
> [`ProjectionBaseError`](../reference/errors.md) rather than leak it.

Calling `.scope()` on a model whose base overrides `model_dump`/`model_validate`
*without* a declaration warns once; declare `projection_bases=()` to silence it.
Runnable: [`examples/custom_base`](../../examples/custom_base).
