# Vary a field's schema per projection

**Goal:** make the *same* field read differently in different projections — a
public-facing description here, an audit description there — without parallel
classes. Scope membership filters fields; scopes can also carry JSON-schema
metadata.

## Per-field — on the `scoped(...)` tag

Attach `description` / `examples` / `json_schema_extra` to each scope marker
(one scope per schema-bearing marker):

```python
from typing import Annotated

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope, description="Public-facing view"): ...
class Internal(Public): ...


class User(ScopedModel):
    email: Annotated[
        str,
        scoped(Public, description="User contact (public-facing)"),
        scoped(Internal, description="User identity, for internal audit"),
    ]


public = User.scope(Public).model_json_schema()
internal = User.scope(Internal).model_json_schema()

assert public["properties"]["email"]["description"] == "User contact (public-facing)"
assert internal["properties"]["email"]["description"] == "User identity, for internal audit"
```

When several markers apply in a broad projection, the **most-derived** scope
wins (`Internal` beats `Public`). Two *unrelated* matches in a union projection
are ambiguous and raise `TypeError`.

## Per-model — on the `Scope` class

Metadata on the `Scope` class itself lands on the projected model's schema root:

```python
assert public["description"] == "Public-facing view"   # from class Public(Scope, description=...)
```

Scope-class metadata is **not** inherited — a broader subclass does not reuse a
narrower scope's prose.

> [!NOTE]
> Both levels are schema-only: no effect on validation, membership, refs, or
> runtime shape. A pre-existing `json_schema_extra` on the canonical is
> preserved and merged.
