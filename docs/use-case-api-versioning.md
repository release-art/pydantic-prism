# Use case — scopes as API versions (field lifecycle)

Captured 2026-06-10 (second dive). Positioning + feature note, parked for the
docs restructure. **Moderate conviction** — promising mapping, but the lifecycle
semantics need design work before committing.

## The pain

Maintaining `/v1`, `/v2`, `/v3` of an API means tracking which fields exist in
which version — added, renamed, deprecated, removed. The common practice is
**separate hand-written V1/V2/V3 models per version** with version-prefixed
routers, plus `Field(deprecated=True)` for soft deprecation
([FastAPI field deprecation guide](https://www.getorchestra.io/guides/fast-api-field-deprecation-a-comprehensive-guide)).
Same drift problem prism addresses, on the time axis instead of the role axis.

## The mapping

A version is a scope; "added in v2" is scope membership:

```python
class V1(Scope): ...
class V2(V1): ...        # V2 is a superset-in-time of V1

class Product(ScopedModel):
    id:    Annotated[UUID, scoped(V1)]
    name:  Annotated[str, scoped(V1)]
    slug:  Annotated[str, scoped(V2)]      # added in v2
    sku:   Annotated[str, scoped(V1 - V2)] # present in v1, removed in v2

ProductV1 = Product.scope(V1)
ProductV2 = Product.scope(V2)
```

`V1 - V2` (the difference operator) expressing "removed in v2" is the kind of
thing prism's algebra does that hand-written version models cannot.

## Why only moderate conviction

- **Inheritance direction is ambiguous.** Roles broaden by sensitivity; versions
  broaden by time — but real APIs both *add* and *remove* fields across
  versions, so a clean `V2(V1)` ladder breaks down (the `V1 - V2` hack above
  hints at the strain). Deprecation, rename, and type-change-across-version are
  not pure membership.
- **Field rename / type change across versions is out of scope** — prism filters
  fields, it never rewrites them (see README "Not yet"). Versioning often *does*
  rewrite. A library like Cadwyn already targets API-version migrations head-on.
- So prism likely covers the **field add/remove** slice cleanly and should be
  honest that rename/transform is not its job.

## The bet (if pursued)

Probably a **docs page + example** showing the add/remove slice, plus possibly a
`deprecated` passthrough on `scoped(...)` that maps to `Field(deprecated=True)`
in the projected schema. Hold until the [read/write](use-case-readwrite-fields.md)
and [governance](use-case-pii-governance.md) wedges land — this is a "nice
adjacency", not a headline.
