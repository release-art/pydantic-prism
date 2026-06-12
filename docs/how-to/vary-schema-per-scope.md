# Vary a field's schema per projection

**Goal:** make the *same* field read — and *validate* — differently in different
projections, without parallel classes. Scope membership filters fields;
`scoped(..., override=Field(...))` then varies anything a `FieldInfo` holds per
projection.

## Per-field — `override=Field(...)` on the `scoped(...)` tag

Pass a `Field(...)` (one scope per override-bearing marker); its explicitly-set
attributes overlay the field in projections that select that scope:

```python
from typing import Annotated

from pydantic import Field

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope, description="Public-facing view"): ...
class Internal(Public): ...


class User(ScopedModel):
    email: Annotated[
        str,
        scoped(Public, override=Field(description="User contact (public-facing)")),
        scoped(Internal, override=Field(description="User identity, for internal audit")),
    ]


public = User.scope(Public).model_json_schema()
internal = User.scope(Internal).model_json_schema()

assert public["properties"]["email"]["description"] == "User contact (public-facing)"
assert internal["properties"]["email"]["description"] == "User identity, for internal audit"
```

`override=` spans the whole `FieldInfo` surface — `description` / `examples` /
`json_schema_extra` annotations, validation constraints, `alias`, `default`, … —
so one mechanism covers every per-projection difference. For the common case you
can pass the kwargs as a plain mapping instead of building a `Field`:
`scoped(Public, override={"description": "User contact (public-facing)"})`
(a `Field(...)` keeps full editor type-checking; the mapping is just terser).

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

## Vary validation *constraints* per projection

The same `override=Field(...)` carries *validation constraints*, not just
annotations — so a field can actually *accept* different values per projection
(a real `min_length` / `ge` / `pattern` difference):

```python
from pydantic import ValidationError


class Body(Scope): ...
class StorageScope(Scope): ...


class Card(ScopedModel):
    name: Annotated[str, scoped(Body, StorageScope)]
    image_description: Annotated[
        str,
        scoped(Body, override=Field(min_length=200)),          # rich LLM prompt
        scoped(StorageScope, override=Field(min_length=10)),   # human may trim it
        Field(max_length=5000),                                # shared by both
    ]


storage = Card.scope(StorageScope)
body = Card.scope(Body)

# Same field, different acceptance: storage takes a 50-char value Body rejects.
short = "c" * 50
assert storage(name="x", image_description=short).image_description == short
try:
    body(name="x", image_description=short)
    raise AssertionError("Body should reject a 50-char value")
except ValidationError:
    pass

# The difference lands in the JSON schema too.
assert body.model_json_schema()["properties"]["image_description"]["minLength"] == 200
assert storage.model_json_schema()["properties"]["image_description"]["minLength"] == 10
```

**Merge, not replace.** The overlay merges with the canonical `Field(...)`: each
constraint *kind* you name (`min_length` here) overrides the canonical's; every
other constraint (`max_length=5000`) inherits. The override is unrestricted —
including *loosening*, as `StorageScope` does above.

> [!WARNING]
> A loosened projection accepts values the canonical would reject, so **the
> canonical is no longer a superset of its projections.** That is the point of
> the feature, but it means you cannot assume "valid in projection ⇒ valid in
> canonical." An `override=`-bearing `scoped()` must name exactly one scope.
