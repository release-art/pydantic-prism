# Build a PATCH / partial-update model

**Goal:** a model where every field is optional — a PATCH body — where *absent*
("don't touch") is genuinely distinct from an explicit `null`, then apply one
back onto an existing record.

Declare a scope with `partial=True`. Every projection to it makes each
surviving field optional, defaulting to the `MISSING` sentinel.

```python
from typing import Annotated
from uuid import UUID, uuid4

from pydantic_prism import MISSING, Scope, ScopedModel, scoped


class Public(Scope): ...
class Storage(Public): ...
class Update(Storage, partial=True): ...


class Account(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    status: Annotated[str, scoped(Storage)] = "active"


AccountUpdate = Account.scope(Update)

empty = AccountUpdate()                  # valid: every field absent
assert empty.name is MISSING             # absent reads as the sentinel
assert empty.model_dump() == {}          # MISSING is auto-omitted, no exclude_none needed

patch = AccountUpdate(name="ADA")
assert patch.model_dump() == {"name": "ADA"}
```

Canonical nullability is preserved: a required field stays non-nullable (a
patch can't set it to `null`), an `Optional[T]` field becomes
`T | None | MISSING` (so `null` and absent stay distinct), and the JSON schema
requires nothing.

## Apply a patch with `with_updates`

`with_updates` applies a partial projection's **explicitly-set** fields onto a
canonical instance and returns a new, re-validated one:

```python
account = Account(id=uuid4(), name="ada")    # status defaults to "active"
updated = account.with_updates(patch)

assert updated.name == "ADA"                 # patched
assert updated.status == "active"            # untouched
assert account.name == "ada"                 # original is unchanged
```

Absent means "don't touch"; an explicit `None` clears an optional field. The
result is re-validated, so nested models are reconstructed and validators run —
which is why this is a method and not a raw `model_copy(update=...)`.

> [!NOTE]
> Partial scopes require `pydantic >= 2.12` for the `MISSING` sentinel;
> `pydantic_prism.MISSING` re-exports it. A complete projection (not a delta)
> uses [`from_projection`](../reference/api.md#round-trips) instead.

See the runnable [`examples/partial_update`](../../examples/partial_update).
