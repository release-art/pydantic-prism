# API decision record — pydantic-prism v0.1

Phase 2 output, 2026-06-10. Each entry: the question, options considered, the
chosen answer, and the reasoning given/implied. Decisions were made by the
project owner in a structured Q&A; recommendations that were overridden are
noted, since they mark deliberate departures.

## 1. Marker name → `scoped(...)`

Options: `scoped`, `scopes`, `views`, prism-themed names.
**Chosen: `scoped(...)`** — reads as an adjective on the field
("this field, scoped to ..."), pairs with `Model.scope(...)`, no ORM/CRUD
baggage.

## 2. Untagged fields → in **no** scope

Options: no scope / every scope / definition-time error.
**Chosen: no scope.** Untagged fields exist only on the canonical model and
never appear in projections. Safe by default: a forgotten tag cannot leak
`password_hash` into a public projection. The wildcard (`scoped(Scope)`)
covers "shared everywhere" fields explicitly.

## 3. Exclusion → wildcard + exclusion, via scope algebra

Options: positive-only (recommended) / `excluded_from()` marker / wildcard+exclusion.
**Chosen: wildcard + exclusion** (override of recommendation). Realized through
decision 4's algebra rather than a second marker: `scoped(Scope)` is the
wildcard (root scope matches everything), `scoped(Scope - Sensitive)` is
wildcard-minus-exclusion. No marker-conflict policy is needed because
exclusion is structural inside the expression.

## 4. Scope hierarchies → first-class tree-like Scope objects

Options: out-of-scope (recommended) / model-level declaration / marker-level objects.
**Chosen (owner's own design): scopes are classes** — independent `Scope`
subclasses whose *Python inheritance* forms the dependency graph, plus a
set-like operator protocol for composition/exclusion. `class Internal(Public)`
means Internal is broader: every field tagged `Public` also appears in
`Internal` projections. Membership rule: a field tagged `T` is in projection
`S` iff `issubclass(S, T)`.

## 5. Scope identity → classes only, no strings

Options: classes only / strings as sugar / both with name resolution.
**Chosen: classes only.** Typos are `NameError`s instead of silently new
scopes, IDEs autocomplete scope names, and the tree semantics live where
Python users expect them. Cost accepted: one declaration line per scope.

## 6. Scope algebra → full: `|`, `&`, `-`, `~`

Options: `|`/`-` only (recommended) / full algebra / `exclude=` kwarg.
**Chosen: full algebra** (override of recommendation). `A | B` union,
`A & B` intersection, `A - B` difference, `~A` complement — usable both in
`scoped(...)` tags and in `Model.scope(...)`. Varargs remain union sugar:
`scoped(A, B) == scoped(A | B)`. Expressions are reusable values
(`SAFE = Scope - Sensitive`).

## 7. `Model.scope(...)` → cached + auto-named

Options: cached/auto-named / cached with mandatory names for expressions / fresh class per call.
**Chosen: cached + auto-named.** Same expression returns the same class object
(`User.scope(Public) is User.scope(Public)`) — required for FastAPI/OpenAPI
identity. Names derive from the expression (`UserPublic`,
`UserInternalOrPublic`, `UserScopeNotSensitive`); `name=` kwarg overrides and
participates in the cache key.

## 8. Nested ScopedModels → scope propagates

Options: propagate / keep canonical / propagate with opt-out marker.
**Chosen: propagate.** Projecting `Order` to `Public` rewrites a nested
`Address` field's annotation to `Address.scope(Public)`, recursing through
`Optional`/`Union`/`list`/`set`/`tuple`/`dict`. A public projection embedding
unprojected nested models would leak fields and defeat the point.

## 9. Ref direction → forward `ref()` AND explicit `backref()` marker

Options: forward-only (recommended) / explicit backref marker / auto-reverse registry.
**Chosen: explicit back-ref marker** (override of recommendation).
`customer_id: Annotated[UUID, ref(Customer)]` forward;
`order_ids: Annotated[list[UUID], backref(Order, via="customer_id")]` declared
reverse. No global registry, no import-order magic; the `via=` link is
validated against the target's forward ref at resolution time. String targets
(`ref("Customer")`) supported for cycles, resolved lazily against the owning
class's module.

## 10. Ref cardinality → inferred from the annotation

Options: inferred / `many=True` kwarg / per-kind markers.
**Chosen: inferred.** `UUID` → to-one, `list[UUID]` → to-many,
`UUID | None` → optional. The annotation *is* the cardinality; `RefInfo`
exposes the result as `.many` / `.optional`.

## 11. `__refs__` → graph object

Options: mapping of small RefInfo (recommended) / minimal dict / graph object.
**Chosen: graph object** (override of recommendation). `Model.__refs__` is a
`RefGraph`: a `Mapping[str, RefInfo]` keyed by field name, plus `.outgoing`,
`.incoming` (declared backrefs), `.targets()`, and `.walk()` BFS edge
traversal across reachable models. Still introspection-only — no resolvers or
query building.

## 12. Round-trip → thin helpers

Options: plain-pydantic pattern only (recommended) / thin helpers / instance `.project()`.
**Chosen: thin helpers** (override of recommendation). Projected classes get
`Projected.from_canonical(instance)`; `ScopedModel` gets
`Canonical.from_projection(proj, **rest)`. Both are documented one-liners over
`model_validate`; no instance-level methods (keeps the field-name collision
surface minimal).

## 13. Error timing → eager structure, lazy resolution

Options: eager structure + lazy resolution / all eager / all lazy.
**Chosen: eager structure, lazy resolution.** At class definition: markers
used as field defaults, `ref()` targets that are neither `ScopedModel`
subclass nor `str`, malformed marker arguments. At first resolution
(`.scope()` call or `__refs__` access): unresolvable string targets,
`backref(via=...)` mismatches, projections selecting zero fields. Eager-only
is impossible with forward references; lazy-only would hide the #1 misuse.

## 14. Validators on projections → field validators yes, model validators no

Options: field-yes/model-no / nothing copied / everything copied.
**Chosen: field validators carry over** for fields that survive the
projection (re-targeted to the surviving subset when a validator covers
several fields); `@model_validator` is never copied (it assumes the full
field set) — documented loudly. `Annotated`-level validators survive
automatically because annotations are copied. Documented caveat: field
validators reading `info.data` of dropped fields fail at validation time.

## 15. Backref field shape → real field, default empty

Options: real field with implied empty default / phantom declaration / required field.
**Chosen: real data field.** A `backref`-marked `list[UUID]` field is a
normal validated field with an implied `default_factory=list`; users may
populate it from their own resolvers. Under decision 2 it stays out of every
projection unless explicitly `scoped(...)`.

## Decisions made by fiat during implementation (not user-facing API)

- Derived classes subclass a shared `Projection(BaseModel)` base (carries
  `from_canonical`, `__prism_source__`, `__prism_scope__`, `__refs__`) — not
  the canonical class, since pydantic subclasses cannot remove required fields.
- Prism markers are stripped from projected models' field metadata; projected
  `__refs__` is rebuilt from the canonical graph filtered to surviving fields,
  with targets pointing at canonical classes (per the spec: projected `Order`
  still knows `customer_id` → `Customer`).
- `model_config` is deep-copied from canonical to projection.
- Computed fields are not copied to projections in v0.1 (they are methods that
  may reference dropped fields) — listed under "not yet".
- Scope classes are never instantiated; `Scope.__init__` raises.
- Marker order inside `Annotated` is insignificant; multiple `scoped()`
  markers on one field union together.
