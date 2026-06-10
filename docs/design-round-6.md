# Design memo — round 6 (`with_updates` patch API)

Phase 1 output, 2026-06-10. `partial=True` projections are PATCH-shaped, but
applying one back onto a canonical instance is unhelped boilerplate:
`canonical.model_copy(update=patch.model_dump(exclude_unset=True))`, rewritten
at every consumer. Make it `canonical.with_updates(patch)` and the partial story
is complete. (Name `with_updates` is the feedback's; kept.)

## The boilerplate is subtly wrong — which decides the core question

`model_copy(update=...)` does **no validation**, and `model_dump` turns nested
models into plain dicts. Verified: patching a field whose value is a nested
model leaves the canonical instance holding a `dict` where a model belongs
(`o.inner` becomes `{'label': 'y'}`, not `Inner(...)`). Re-validating the merged
data reconstructs it correctly and runs the canonical's coercion/validators. So
the library method should not encapsulate the bug — it should re-validate.

## Q1. Validate the result, or mirror `model_copy`?

Options: always re-validate (recommended) / re-validate by default with a
`validate=False` escape / `model_copy` (no validation, matches today's
boilerplate).
**Recommend always re-validate.** Merge the canonical's current data with the
patch's set fields and `model_validate` the result → a fully valid `Self`, with
nested models reconstructed and field validators / `@scoped_validator`s run. It
is strictly more correct than the one-liner it replaces (which silently
corrupts nested fields). The raw-copy path stays available as the manual
one-liner for anyone who genuinely wants it; baking a footgun into the method,
even behind a flag, is not worth the surface.

## Q2. What counts as an update?

Options: explicitly-set fields only — `exclude_unset=True` (recommended) /
all non-`None` fields.
**Recommend `exclude_unset`.** That is the PATCH contract: absent means "don't
touch," and an explicitly-set `None` *is* an update (clearing an optional
canonical field). `exclude_none` would make it impossible to patch a value to
`None` and would write back every defaulted field. `exclude_unset` is exactly
what a directly-constructed `Update(name="x")` carries.

## Q3. What may be passed, and provenance?

Options: a `Projection` of this model, provenance-checked (recommended) / also
accept a plain `Mapping` / any `BaseModel`.
**Recommend a `Projection` of this model.** Check `isinstance(self,
patch.__prism_source__)` and raise `TypeError` otherwise — patching with a
projection of a *different* model is a mistake that would otherwise merge
mismatched keys or fail with a confusing validation error. The typed partial
projection is the whole point; a raw `Mapping` escape can be added later if real
demand appears, but it undercuts the typed story and skips provenance.

## Mechanics

```python
def with_updates(self, patch: Projection, /) -> Self:
    if not isinstance(self, patch.__prism_source__):
        raise TypeError(...)
    base = self.model_dump(by_alias=True)
    updates = patch.model_dump(by_alias=True, exclude_unset=True)
    return type(self).model_validate({**base, **updates})
```

Both dumps use `by_alias=True` so keys live in one space and `model_validate`
accepts them (mirrors `from_projection`). Returns a new instance — `self` is
untouched. Pairs naturally with `from_canonical` (canonical → partial) and
`from_projection` (projection → canonical with extras).

## Settled by fiat / notes

- Accepts **any** projection of the model, not only partial ones (`exclude_unset`
  generalizes); partial is just the typical source.
- A patched field must satisfy the **canonical's** validation — patching a
  nested field with a narrower projected value that omits required canonical
  subfields raises a clear `ValidationError` (inherent to PATCH-with-less-data).
- Bad input (not a projection / wrong source) → `TypeError` at the call,
  consistent with the rest of the API.
