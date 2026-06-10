# Design memo — round 7 (projection naming + scope schema metadata)

Phase 1 output, 2026-06-10. Two ergonomics from adoption feedback:

4. **Class-level projection naming** — `name=` on `.scope()` is call-site only;
   a class default would clean up OpenAPI/swagger names without threading it
   through every consumer.
5. **Scope-attached JSON schema metadata** — scope membership only *filters*
   today; let scopes carry `description` / `examples` / `json_schema_extra` so
   the same field can read differently per projection (the email-in-Public vs
   email-in-Internal case) without parallel hand-written classes.

---

## Feature 4 — `projection_name_template`

A class keyword (sibling of `projection_bases=` / `default_scope=`) giving the
default auto-name for every projection of the model.

- **Spelling & placeholders.** `projection_name_template="{model}_{scope}"`,
  formatted with `model=cls.__name__` and `scope=expr.token()` (the CamelCase
  fragment already used for auto-names: `Public`, `InternalOrPublic`, `NotLlm`).
- **Precedence.** call-site `name=` > class template > built-in default
  (`f"{model}{scope}"`). All three feed the one name slot, so the cache and
  `ProjectionNameError` collision check are unchanged.
- **Must produce a valid identifier.** Verified: pydantic *accepts* a non-ident
  name like `User@Public` but sanitizes the OpenAPI `$ref` to `User_Public`, and
  — decisively — the round-4 `prism gen` codegen would emit
  `class User@Public(...)`, which is a syntax error. So the templated result is
  validated with `str.isidentifier()` (eagerly at class definition via a sample
  format, and at each `.scope()`); a non-identifier raises `TypeError`. The
  feedback's `{model}@{scope}` becomes `{model}_{scope}` or similar.
- **Inheritance & validation timing.** Inherited down the MRO like the other
  class keywords (a subclass may re-declare); bad placeholders (`{scop}`) raise
  `TypeError` at class definition. The name computation is factored into one
  helper used by both `_project` and the codegen's alias emitter (which today
  hardcodes the `{model}{scope}` formula — a small refactor to absorb this).

This one has a single reasonable shape; the only real choice is the identifier
restriction (recommended yes, for codegen + OpenAPI safety).

---

## Feature 5 — scope schema metadata

### The granularity fork (the central decision)

The literal proposal — "let a *scope* carry `description=` … that lands on the
*projected model's* schema" — is **model-level**: `class Public(Scope,
description=...)` annotates the whole `UserPublic` schema. But the motivating
example — email is "contact (public-facing)" in Public and "identity, for audit"
in Internal — is **field-level**: one field, different schema per projection.
Model-level alone does *not* solve the email case (a single scope description
can't differ per field). They are different mechanisms; the round can ship
either or both.

**Recommend both**, because they answer different needs and share one vocabulary:

- **Model-level** — schema on the **Scope class**:
  `class Public(Scope, description="Public-facing view of the record",
  examples=[...], json_schema_extra={...})`. When a projection's scope expression
  has that atom, the metadata merges into the projected model's top-level schema.
  Cheap; directly serves the OpenAPI-cleanliness motivation.
- **Field-level** — schema on the **field's `scoped(...)` tag**:
  `scoped(Public, description="User contact (public-facing)")`. This is what
  solves the email case and "the entire problem prism set out to solve."

### Field-level mechanism

**Recommend extending `scoped()`** rather than a new marker:
`scoped(*scopes, description=None, examples=None, json_schema_extra=None)`. It
reuses the *existing* multi-marker idiom — a field already unions membership
across several `scoped()` markers, so per-scope schema falls out naturally:

```python
email: Annotated[
    str,
    scoped(Public, description="User contact (public-facing)"),
    scoped(Internal, description="User identity, for internal audit"),
]
```

Membership is still `Public | Internal` (union across markers, unchanged). A
schema-carrying marker must name **exactly one** scope (so its metadata keys to
a single atom for precedence); `scoped(Public, Internal, description=...)`
raises. A new marker (`described(...)`) would duplicate the scope-membership
surface for no gain.

### Matching & precedence (field-level)

A field's `scoped(S, …schema…)` marker contributes in a projection to `E` iff
`E.selects(S)` — the same membership rule used for field survival and
`@scoped_validator` (one rule library-wide). When several markers match (a
broad projection selecting both `Public` and `Internal`), **the most-derived
scope wins** — the `S` that is a subclass of all other matching `S'` (in prism a
subclass is the *broader* scope, so `Internal` beats `Public` in an Internal/
Storage projection, which is what the email case wants). Matches with no
subclass relation between them (e.g. `Public` vs an unrelated `Other` in a
union projection) are **ambiguous → `TypeError`** at `.scope()`, naming the
field and the rival scopes. This is predictable and consistent with the rest of
the algebra; "last-declared wins" would make field order silently significant,
and "error on any multiple" would break the common hierarchy case.

### How it lands

- `json_schema_extra` is the keyword (matches pydantic's `Field` / `ConfigDict`;
  the feedback's `extra_json_schema` renamed for ecosystem consistency).
- **Field-level:** set the projected field's `FieldInfo.description` /
  `.examples` (replace) and merge `.json_schema_extra` — so the canonical
  field's own description is overridden *in that projection only*.
- **Model-level:** merge `{description, examples, **json_schema_extra}` into the
  projection's `model_config["json_schema_extra"]`, so the schema root gains
  `description`/`examples`/extra. Multiple annotated atoms in one expression
  merge in deterministic (sorted) order.
- Both are schema-only: zero effect on validation, projection membership, refs,
  or the runtime shape.

### Scope-class metadata is per-class (not inherited)

A scope's *model-level* schema applies to that scope only; `Internal(Public)`
does not inherit Public's model description (read from the class's own
declaration). Otherwise every broader scope would silently reuse a narrower
scope's prose.

---

## Open questions for phase 2

1. Feature 5 granularity: model-level / field-level / **both** (rec).
2. Field-level mechanism: **extend `scoped()`** (rec) / new marker.
3. Field-level precedence: **most-derived wins, unrelated→error** (rec) /
   last-wins / error-on-any-multiple.
4. Feature 4: `{model}`/`{scope}` placeholders, **identifier-restricted** (rec).

Fiat: keyword is `json_schema_extra`; schema-carrying `scoped()` takes one
scope; metadata is schema-only; scope-class schema is non-inherited.
