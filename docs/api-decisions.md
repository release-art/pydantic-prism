# API decision record — pydantic-prism v0.1

Phase 2 output, 2026-06-10. Each entry: the question, options considered, the
chosen answer, and the reasoning given/implied. Decisions were made by the
project owner in a structured Q&A; recommendations that were overridden are
noted, since they mark deliberate departures.

A second round of decisions (adoption feedback) is appended at the end.

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

---

# API decision record — round 2 (adoption feedback)

Phase 2 output, 2026-06-10. Questions raised by the SiteCompliance adoption
assessment (see docs/design-round-2.md for the full option analysis).

## 16. Custom-base composition → explicit `bases=`, never implicit

Options: carry the canonical's non-ScopedModel bases by default
(recommended) / explicit `bases=` kwarg on `.scope()` / class-level opt-in
with warning.
**Chosen: explicit `bases=`** (override of recommendation).
`Row.scope(Storage, bases=(CustomBase,))` builds the projection on
`(CustomBase, Projection)`, restoring custom `model_dump`/`model_validate`,
base-declared validators/serializers, and `isinstance(p, CustomBase)`.
`bases` joins the cache key; same expression with different bases is a
different (cached) class.

## 17. Default bases → class-level declaration + per-call override

Options: per-call only / class-level default with per-call override
(recommended).
**Chosen: class-level default.**
`class Row(CustomBase, ScopedModel, projection_bases=(CustomBase,))` sets
the default for every `.scope()` on that model (inherited by subclasses);
`bases=` at the call site overrides, `bases=()` opts out. Spelling is a
class keyword (next to the inheritance it mirrors), not a dunder ClassVar.

## 18. Dropped-behavior signal → warn once per model

Options: warn once (recommended) / silent / error.
**Chosen: warn once per canonical model.** When `.scope()` runs without
carried bases on a model whose non-ScopedModel ancestry defines droppable
pydantic behavior (overridden `model_dump`/`model_validate`, model
validators/serializers), a `UserWarning` names the base and suggests
`bases=`/`projection_bases=`. Emitted once per canonical model.

## 19. Base-declared fields under carried bases → present, loudly documented

Fields declared on a carried base are inherited by every projection and
cannot be removed (pydantic cannot unset inherited fields). Rule: (a) they
are documented as infrastructure fields, present whenever the base is
carried; (b) if a base-declared field carries a `scoped()` tag that the
requested expression does **not** select, `.scope()` raises (a narrowing
prism cannot honor fails instead of leaking).

## 20. Dict-keyed refs → one `ref()`, annotation-driven

Options: one `ref()` inspecting the annotation (recommended) / distinct
`dict_ref()` marker.
**Chosen: one `ref()`.** `Annotated[dict[UUID, Highlight], ref(Highlight)]`:
a `Mapping` origin makes the ref keyed-dict-shaped — the dict key IS the
foreign id. Key type is recorded and checked lazily against the target id
field's type (`RefResolutionError` on mismatch, at `__refs__` access,
consistent with decision 13). Values need not be the target model
(`dict[UUID, AnyPayload]` is legal: keys are ids, value is opaque payload).

## 21. Ref shape introspection → `RefShape` StrEnum

Options: `RefShape` StrEnum (recommended) / `Literal` strings.
**Chosen: StrEnum.** `RefInfo.shape` is
`RefShape.SCALAR | COLLECTION | KEYED_DICT` (StrEnum, so string comparison
also works), plus `RefInfo.key_type` for keyed dicts. `RefInfo.many`
survives as a derived property (`shape is not SCALAR`) for v0.1 compat.

## 22. Embedded ref-records → auto-registered, distinct `kind="embedded"`

Options: auto with `kind="ref"` / auto with distinct kind (recommended) /
explicit no-arg `ref()`.
**Chosen: auto, distinct kind.** A field typed with a `Projection` class
(under `list`/`dict`/`Optional`/etc.) registers an edge to its
`__prism_source__` automatically — no marker. The edge has
`kind="embedded"` and `RefInfo.scope` records the carrier's scope
expression. `.outgoing` keeps meaning id-style FK edges; a new `.embedded`
accessor exposes carrier edges; `targets()`/`walk()` see both.

## 23. Embedded composition → uniform: canonical nesting registers too

Options: projections only (recommended) / uniform.
**Chosen: uniform** (override of recommendation). Plain canonical nesting
(`Address` inside `Shipment`) also auto-registers a `kind="embedded"` edge,
with `scope=None` meaning "reshapes with the outer projection". The whole
containment graph is introspectable through `__refs__`; behavior change for
v0.1 models that nest ScopedModels (noted in CHANGELOG). Key types of
keyed-dict *embedded* edges are recorded but never validated against the
target id (composition keys are arbitrary; only explicit `ref()` keyed
dicts validate).

## 24. Optional-on-projection → `partial=True` scope keyword

Options: call-site flag / model-level set / per-field `optional_in=` /
scope-class property (recommended).
**Chosen: scope-class property.** `class Update(Storage, partial=True)` —
optionality is a property of the scope itself, declared once where the
scope graph lives. The flag inherits down the scope graph unless
re-declared. An expression is partial iff **all** its atoms are partial
(conservative; mixing partial and regular scopes yields a regular
projection). Keyword is `partial` (TS `Partial<T>` precedent), not
`optional`.

## 25. Partial defaults → force `None` everywhere

Options: force `None` on every surviving field (recommended) / keep
canonical defaults where present.
**Chosen: force `None`.** Every surviving field becomes `T | None` with
`default=None`; canonical defaults are dropped. True PATCH semantics:
absent means "don't touch" — a surviving canonical default would be
silently written back on every sparse update. JSON schema (nothing
required, fields nullable) falls out.

## 26. `Model.scopes()` → returns scope classes

Options: scope classes (recommended) / scope names.
**Chosen: classes.** `frozenset[type[Scope]]` of the atom scopes appearing
in the model's field tags — scopes are classes everywhere else in the API,
and the result can be fed back into `.scope()`. Error messages format the
names themselves.

## Round-2 decisions made by fiat during implementation

- `from_canonical` forwards `mode`, `by_alias` (default `True`, as before),
  `context`, `exclude_none`, `exclude_unset`, `exclude_defaults` to
  `model_dump`.
- `from_canonical` narrowing is auto-detected: when the instance's class
  overrides `model_dump`, the dump is passed to the projection verbatim
  (prism cannot understand a custom wire shape; the user's own
  validators do); standard dumps are narrowed as in v0.1. A `narrow:
  bool | None = None` kwarg overrides the auto-detection in both directions.
- `bases=` entries must be classes the canonical model actually inherits
  from (`TypeError` otherwise) — carrying a base the canonical does not
  have would make the projection behaviorally unrelated to its source.

---

# API decision record — round 3 (class-level default scope)

Phase 2 output, 2026-06-10. One feature: a class-level default scope so fields
in the dominant scope need no per-line `scoped(...)` marker (see
docs/design-round-3.md for the full option analysis). All eight open questions
resolved on the recommendation.

## 27. Spelling → `default_scope=` (singular class keyword)

Options: `default_scope=` (recommended) / `default_scopes=` / `field_scope=` /
`implicit_scope=`.
**Chosen: `default_scope=`.** A class keyword (next to `projection_bases=`,
which it mirrors), singular to match the `scoped()` marker and `Model.scope()`.
Reads as "this model's default scope." `field_scope=` misreads as "the scope of
*a* field"; `implicit_scope=` advertises the mechanism rather than the thing;
`default_scopes=` presumes the tuple answer to #28 and clashes with singular
`.scope()`.

## 28. Multiple defaults → single `ScopeLike`, `|` for unions

Options: single value, `|` for multiple (recommended) / accept a tuple as union
sugar.
**Chosen: single `ScopeLike`** (`type[Scope]` or `ScopeExpr`, coerced via the
existing `as_expr`). "In both Public and Internal" is `default_scope=Public |
Internal` — the union operator is already load-bearing in tags and `.scope()`,
so no third spelling of union is introduced. A tuple would also collide visually
with `projection_bases=(A, B)` while meaning something algebraically different.

## 29. Inheritance → inherits down the MRO; subclass re-defaults its fields

Options: inherit and re-default inherited untagged fields (recommended) /
resolve each field's default at its declaring class.
**Chosen: inherit like `projection_bases=`.** The value is a class attribute set
only when the keyword is given, so MRO lookup supplies it; `default_scope=None`
clears an inherited default (symmetry with `bases=()`). `_collect` resolves
*every* field of the class (inherited included) against the class's effective
default, so a subclass that overrides the default re-scopes inherited *untagged*
fields too. `__field_scopes__` stays a pure function of the class.
`projection_bases=` interaction is moot: carried bases are plain pydantic
classes and cannot carry a `default_scope` (a `ScopedModel` keyword) — the
default comes only from the `ScopedModel` MRO.

## 30. Merge vs replace → replace (explicit wins, no merge)

Options: replace (recommended) / merge default on top of explicit tags.
**Chosen: replace.** The default fills *blank* lines only; a field with a
`scoped(...)` marker ignores it entirely. `scoped(Public)` on a
`default_scope=Storage` model is `{Public}`, never `{Public, Storage}` — so an
explicit tag's meaning is self-contained and never silently widened by the class
default. `scoped(Public, Storage)` is how you ask for both.

## 31. Backward compat → `EmptyProjectionError` unchanged off-feature

**Confirmed.** `default_scope` is purely additive; it changes only classes that
opt in. On those, formerly-untagged fields resolve to the default and no longer
trip `EmptyProjectionError`. On every other class — including a model with no
markers and no default — behavior is byte-for-byte unchanged: untagged → no
scope → `.scope()` raises `EmptyProjectionError` (the forgotten-tag safety net).

## 32. Introspection → resolved `__field_scopes__` + raw `__prism_default_scope__`

Options: resolved with the default folded in (recommended) / only line-level
tags.
**Chosen: resolved, plus expose the default itself.** `__field_scopes__` folds
in the default (it is the engine's selection map — it must agree with what
projection does). A new `Model.__prism_default_scope__` ClassVar holds the
default `ScopeExpr` (or `None`), so explicit-vs-defaulted is reconstructable.
Resolved-for-behavior, raw-for-provenance — both available.

## 33. `partial=True` interaction → flows through identically

**Confirmed.** Once a field is in `__field_scopes__`, nothing downstream can
tell whether a marker or the class default put it there. A `default_scope=`
model projected to a partial scope makes its default-scoped fields optional with
`None` defaults exactly as explicit ones — no code path special-cases the
origin.

## 34. Bad `default_scope=` value → `TypeError` at class definition

Options: class-definition time (recommended) / first `.scope()` call.
**Chosen: class definition.** Scopes are classes, so an undefined scope is a
`NameError` before prism runs; the reachable misuse is a wrong-typed value,
which `as_expr()` rejects with a clear `TypeError`. Called eagerly in
`__init_subclass__`, matching decision 13 (eager structure) and the convention
that API misuse is `TypeError`, not a `PrismError`. No new error class.

## Round-3 sub-decisions made by fiat

- **Uniform fallback.** The default fills the scope of *any* field lacking a
  `scoped()` marker, including `ref()`/`backref()` fields (which without a
  default stay out of every projection per decision 15). "All my untagged fields
  default to X" carves out nothing; tag a backref `scoped(...)` to exclude it.
- The default is resolved into `__field_scopes__` at collection time, fully
  upstream of projection — it is *not* part of the `.scope()` cache key and
  needs no change to the projection engine, naming, or refs.
