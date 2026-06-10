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

---

# API decision record — round 4 (static-type visibility for projections)

Phase 2 output, 2026-06-10. The biggest adoption blocker: in a pyright/Pylance
(VSCode) or mypy codebase, `Model.scope(...)` is `type[Projection]` with opaque
fields. See docs/design-round-4.md for the full analysis; the load-bearing
constraint is that scope selection runs the algebra at *runtime* and pyright has
no third-party plugin API, so the only **universal** fix is ordinary type
declarations every tool already reads. Direction taken: generate real classes
with a CLI; verify freshness at startup.

## 35. Mechanism → CLI-generated stubs, not a plugin

Options: pyright/mypy plugin / generated declarations.
**Chosen: code generation.** A plugin cannot be universal — Pylance (VSCode) has
no plugin API, and a mypy plugin never reaches a VSCode hover. `prism gen` emits
a real module of concrete classes the whole toolchain reads with zero config.

## 36. Generated-class realness → typed shim over the genuine projection

Options: typed shim + runtime alias (recommended) / fully materialized classes.
**Chosen: shim.** Per projection, `if TYPE_CHECKING: class ScreenshotRef(
Projection): ...` / `else: ScreenshotRef = Screenshot.scope(Ref)`. The checker
reads the class; the runtime object is the authentic `.scope()` result, so
validators, refs, carried bases, partial defaults and FastAPI all work for free
and `ScreenshotRef is Screenshot.scope(Ref)`. `_project` stays the single source
of runtime truth — the generator never reproduces behavior, only field
declarations. Residual: the `Model.scope(Ref)` *call site* still types as
`type[Projection]`; you get types by referencing the generated name (exact
parity with the hand-written class this replaces, minus the hand-writing).

## 37. Drift → per-projection signature, raise at import (startup)

Options: raise (recommended) / warn.
**Chosen: raise `StaleProjectionStubError`.** A stub that silently lies after a
model changes is worse than none. `prism gen` stamps each projection with a
signature (field names, annotation strings, required-ness, carried-base names);
`assert_fresh`, called once per projection at import of the generated module,
recomputes and compares, raising on mismatch. Per-projection direct-field
signatures suffice even for nested models: every referenced projection is itself
generated and asserted, so a nested change trips *its* guard. `prism check`
compares freshly generated output to the file on disk as a non-importing CI gate
(exit 1 on drift).

## 38. Discovery → per-atom auto + opt-in `projections` list

Options: auto per-atom + opt-in extras (recommended) / fully explicit list.
**Chosen: auto + opt-in.** For each module listed in `[tool.pydantic-prism]`,
generate one projection per scope in `Model.scopes()` (the atoms a model
actually uses — zero enumeration for the common case). A `[[…projections]]` list
adds non-atom unions and `name=` overrides; scopes in an entry union together
(like `scoped(A, B)`). Nested projections reachable from any planned one are
discovered transitively and emitted too.

## 39. Scope of slice → everything at once

Options: core + drift + flat models first / everything.
**Chosen: everything** — nested projections (referencing sibling generated
names), partial scopes (`T | None = None`), and carried bases (in the shim's
base list) all land in this round.

## Round-4 decisions made by fiat during implementation

- CLI is a `prism` console script (`[project.scripts]`) with
  `python -m pydantic_prism` equivalent; `gen` and `check` subcommands;
  `--config` defaults to `pyproject.toml`. Bad config/input → exit 2; drift →
  exit 1.
- Generated file carries `# ruff: noqa` and a do-not-edit banner; `from
  __future__ import annotations` makes all field annotations strings, so
  forward references to sibling stub classes need no ordering.
- Field defaults in the shim are rendered only when type-correct (`None`, simple
  literals, and the builtin `default_factory` set); any other default leaves the
  field looking required (conservative — the runtime object is authoritative, so
  the stub's constructor is never *wrong*, only occasionally over-strict).
- Annotation rendering supports concrete types, unions/`Optional`, `Literal`,
  and standard containers; `Annotated` metadata is dropped (typing-irrelevant).
  Anything else raises `CodegenError` at gen time rather than emitting broken
  source.

---

# API decision record — round 5 (`@scoped_validator`)

Phase 2 output, 2026-06-10. Field validators carry to projections, plain model
validators do not (decision 14) — defensible by implementation, surprising as
semantics, and it silently broke the SiteCompliance Update-scope hostname
coercion. See docs/design-round-5.md. The chosen fix is an explicit opt-in,
not carry-by-default.

## 40. Form → dedicated `@scoped_validator(*scopes, mode=...)` decorator

Options: dedicated decorator (recommended) / extend `@model_validator` with a
`scopes=` kwarg / carry-by-default with an opt-out.
**Chosen: dedicated decorator.** A sibling of `@model_validator` with one added
duty ("meaningful for *these* projections"), composing with prism's `scoped()`/
`.scope()` vocabulary. Extending pydantic's own decorator would mean shadowing a
third-party API (fragile across versions); carry-by-default inverts decision
14's safety (silently pushing validators onto field sets they never
anticipated). Plain `@model_validator` is unchanged — still canonical-only.

## 41. Carry rule → same algebra as fields (`projection_expr.selects(tag)`)

Options: field algebra (recommended) / scopes are advisory, carry everywhere.
**Chosen: field algebra.** A validator tagged `scoped_validator(Storage)` carries
exactly where a field tagged `scoped(Storage)` survives — one membership rule
library-wide, reusing `ScopeExpr.selects`. The tag should name the scope of the
fields the validator touches, so it lands wherever those fields do. Varargs and
expressions work (`scoped_validator(Public | Other)`), as in `scoped()`.

## 42. Zero scopes → require ≥1; wildcard is `scoped_validator(Scope)`

Options: require ≥1 (recommended) / zero = all projections.
**Chosen: require ≥1**, mirroring `scoped()`. "Every projection" is the root
`Scope`, the wildcard everywhere else — no new convention.

## 43. Introspection → `Model.__prism_validator_scopes__`

Options: expose (recommended) / internal only.
**Chosen: expose** a `dict[str, ScopeExpr]` keyed by validator name — the
model-validator analogue of `__field_scopes__`, and the very map `_carry_validators`
reads from at projection time. The point of an explicit marker is that carry
behavior is obvious; this makes "which validators carry here, and why"
answerable without reading internals.

## Round-5 decisions made by fiat during implementation

- `mode` is a required keyword (`"before" | "after" | "wrap"`), pass-through to
  `@model_validator` — same muscle memory, all three modes carry.
- **Field-set safety is the user's.** A carried `mode="after"` validator reading
  a dropped field raises at validation; the scope list *is* the assertion that
  the fields it touches survive there. Prism cannot inspect a `mode="before"`
  dict-coercion's needs, so it does not try (parallels decision 14's field-
  validator `info.data` caveat). Validators that may carry to a partial scope
  must guard against `None` (surviving fields are optional there).
- Bad scope argument raises `TypeError` at decoration (via `as_expr`), like
  `scoped()` / decision 13.
- The scope tag is recorded in a module-level `WeakKeyDictionary` keyed by the
  raw function (`before`/`wrap` validators are stored by pydantic as bound
  methods with no writable `__dict__`); `_collect` resolves it into
  `__prism_validator_scopes__`. Inherited automatically — a `scoped_validator`
  on a base `ScopedModel` keys by the same function and carries to subclass
  projections.

---

# API decision record — round 6 (`with_updates` patch API)

Phase 2 output, 2026-06-10. Partial projections are PATCH-shaped, but applying
one back onto a canonical instance was unhelped boilerplate
(`model_copy(update=patch.model_dump(exclude_unset=True))`). See
docs/design-round-6.md. `canonical.with_updates(patch)` completes the partial
story.

## 44. Validation → always re-validate (never raw `model_copy`)

Options: always re-validate (recommended) / re-validate with a `validate=False`
escape / `model_copy` (no validation).
**Chosen: always re-validate.** `with_updates` merges the canonical's current
data with the patch's set fields and calls `model_validate`. This is strictly
more correct than the boilerplate it replaces: `model_copy(update=model_dump())`
leaves nested models as **raw dicts** (verified) and skips coercion and
validators. Re-validation reconstructs nested models and runs field /
`@scoped_validator` validators, yielding a genuinely valid instance. No
`validate=False` escape — baking the footgun in behind a flag is not worth it;
the manual one-liner remains for anyone who truly wants a raw copy.

## 45. Applied fields → explicitly-set only (`exclude_unset`)

Options: `exclude_unset` (recommended) / all non-`None`.
**Chosen: `exclude_unset`.** The PATCH contract: absent means "don't touch," and
an explicitly-set `None` *is* an update (clearing an optional field).
`exclude_none` would forbid patching to `None` and would write back every
defaulted field the caller never set.

## 46. Accepted input → a `Projection` of this model, provenance-checked

Options: provenance-checked projection (recommended) / also a `Mapping` / any
`BaseModel`.
**Chosen: a projection of this model.** `isinstance(self, patch.__prism_source__)`
or `TypeError` — patching with another model's projection is a mistake that
would otherwise merge mismatched keys. Any scope is accepted (not only partial);
`exclude_unset` generalizes, and partial Update projections are just the typical
source. A raw-`Mapping` escape can be added later if demanded, but it skips
provenance and undercuts the typed-projection story.

## Round-6 notes

- Both dumps use `by_alias=True` so keys share one space and `model_validate`
  accepts them (mirrors `from_projection`). `self` is left unchanged; a new
  instance is returned.
- A patched field must satisfy the **canonical's** validation — patching a
  nested field with a narrower projected value that omits a required canonical
  subfield raises `ValidationError` (inherent to PATCH-with-less-data).
- A subclass instance accepts a base-model projection (`isinstance` is lenient
  by design); the result is validated as the subclass, preserving its own
  fields.

---

# API decision record — round 7 (projection naming + scope schema metadata)

Phase 2 output, 2026-06-10. Two ergonomics: a class-level projection-name
template, and scope-attached JSON-schema metadata. See docs/design-round-7.md.

## 47. Projection naming → `projection_name_template`, identifier-restricted

`projection_name_template="{model}_{scope}"` (class keyword, inherited down the
MRO) sets the default auto-name; `{model}` = class name, `{scope}` = the expr
token. Precedence: call-site `name=` > template > built-in `{model}{scope}`.
**The templated result must be a valid Python identifier** — verified that a
non-identifier (`User@Public`) breaks the round-4 `prism gen` codegen
(`class User@Public(...)` is a syntax error) and gets sanitized in OpenAPI
`$ref`s; so the feedback's `{model}@{scope}` becomes `{model}_{scope}`.
Validated eagerly at class definition (sample format + `str.isidentifier()`);
bad placeholders raise `TypeError`. One name helper now serves both `_project`
and the codegen alias emitter (which previously hardcoded the formula).

## 48. Scope schema granularity → both model-level and field-level

The literal proposal (scope carries metadata → projected *model* schema) is
model-level; the motivating email case (same field, different description per
projection) is field-level. **Both**, sharing one vocabulary:
- **Model-level:** schema on the `Scope` *class* —
  `class Public(Scope, description=..., examples=..., json_schema_extra=...)` —
  merges into the projected model's schema root for projections selecting that
  scope. Per-class, **not inherited** (a broader subclass does not reuse a
  narrower scope's prose).
- **Field-level:** schema on the field's `scoped(...)` tag (decision 49).

## 49. Field-level mechanism → extend `scoped()`, single scope per schema marker

`scoped(Scope, description=..., examples=..., json_schema_extra=...)` rather than
a new marker — it reuses the existing multi-marker idiom (a field already unions
membership across several `scoped()` markers, so per-scope schema falls out:
`scoped(Public, description=...)` + `scoped(Internal, description=...)`). A
schema-carrying marker must reference **exactly one** scope (one atom), so its
metadata keys to a single scope for precedence; `scoped(Public, Internal,
description=...)` raises `TypeError`. `json_schema_extra` is the keyword (matches
pydantic's `Field`/`ConfigDict`; the feedback's `extra_json_schema` renamed for
consistency).

## 50. Field-level precedence → most-derived wins; unrelated → error

A `scoped(S, …schema…)` marker applies in projection `E` iff `E.selects(S)` (the
library-wide membership rule). When several match (a broad projection selecting
both `Public` and `Internal`), the **most-derived** scope wins — the `S` that is
a subclass of all other matches (in prism a subclass is broader, so `Internal`
beats `Public` in Internal/Storage projections, which the email case wants).
Matches with no subclass relation (e.g. `Public` vs unrelated `Other` in a union
projection) are ambiguous → `TypeError` at `.scope()`, naming the field and
rival scopes. "Last-declared wins" would make annotation order silently
significant; "error on any multiple" would break the common hierarchy case.

## Round-7 decisions made by fiat

- How metadata lands: field-level sets `FieldInfo.description`/`.examples`
  (replacing the canonical's, in that projection only) and merges
  `.json_schema_extra`; model-level merges `{description, examples,
  **json_schema_extra}` into the projection's `model_config["json_schema_extra"]`
  (multiple annotated atoms merge in sorted order). A pre-existing dict *or
  callable* `json_schema_extra` is preserved (the callable is wrapped).
- All of this is schema-only: zero effect on validation, membership, refs, or
  runtime shape.
- The scope-class metadata is read via `vars(scope)` so it stays strictly
  per-class (non-inherited), unlike `partial=` which inherits.

---

# API decision record — round 8 (partial round-trip story)

Phase 2 output, 2026-06-10. See docs/design-round-8.md.

## 51. `from_projection` on a partial projection → raise, point to `with_updates`

Options: raise a guiding error (recommended) / docs only / warn.
**Chosen: raise `TypeError`.** A partial (`partial=True`) projection is a delta,
not a complete record; building a standalone canonical from it is meaningless
without a baseline. Previously `from_projection(partial)` dumped the unset fields
as `None` and failed with a misleading `ValidationError` blaming a field.
`from_projection` now detects a partial `Projection` (`__prism_scope__.is_partial()`)
and raises a clear error pointing to `baseline.with_updates(patch)` (the round-6
partial → canonical round-trip, which pulls dropped fields from the baseline) or
to building from a non-partial projection. This removes one unusual ability —
`from_projection` on a fully-populated partial plus `**extra` — but that is a
misuse of `partial`; the guard only fires for prism `Projection`s, so plain
`BaseModel` inputs are unaffected.

## 52. The two reverse round-trips, documented

`from_projection(proj, **extra)` reconstructs a canonical from a **complete**
projection (dropped fields from `**extra`/defaults); `baseline.with_updates(patch)`
applies a **partial** delta onto a baseline (dropped fields from the baseline).
README states this as a table — the symmetric counterpart to `from_canonical`.

## Item 7 (doc debt) — reported already-paid

The feedback predated this branch's round-2/3 documentation. Audited:
`projection_bases=`, `RefShape.KEYED_DICT`, `partial=True`, and `Model.scopes()`
all have substantive README coverage (dedicated sections + API-reference rows)
and CHANGELOG entries. **No redundant edits made** — manufacturing churn on
already-covered docs would be dishonest; the honest deliverable was the audit
and this record.

---

# API decision record — round 9 (RefInfo shape audit)

Phase 2 output, 2026-06-10. See docs/design-round-9.md. The mandate was to
*commit* one way (the drift between shapes is the failure mode).

## 53. RefInfo → split by `kind` into discriminated subtypes

Options: commit to the single dataclass (recommended in the memo) / split by
`kind`.
**Chosen: split** (owner's call, against the memo's lean — consistent with the
codebase's structural/introspection-first bent). `RefInfo` becomes the base of
`IdRefInfo` (`kind="ref"`), `BackRefInfo` (`+ via: str`), and `EmbeddedRefInfo`
(`+ scope: ScopeExpr | None`). The audit corrected two things the feedback got
wrong: it is **3** conditional fields (not ~8), and the proposed
`Id`/`Embedded`/`KeyedDict` split mixed axes — `kind` and `shape` are
orthogonal. The **only clean discriminant is `kind`**; `key_type` is shape-driven
and therefore stays on the base (a kind split would not capture it). So the
split moves exactly `via` and `scope` onto their variants.

## 54. RefInfo stays the importable base class

Options: base class (recommended) / union alias.
**Chosen: base class.** `RefInfo` remains a real class the three variants
subclass, so `isinstance(x, RefInfo)` and existing imports keep working;
`__refs__[name]` is typed `RefInfo`. The kind-typed accessors (`.outgoing`
`dict[str, IdRefInfo]`, `.incoming` `dict[str, BackRefInfo]`, `.embedded`
`dict[str, EmbeddedRefInfo]`) deliver the precise types where the partition is
already by kind.

## Round-9 notes

- **Breaking (pre-1.0, feedback-invited):** `via`/`scope` left the base, so a
  base-typed read must narrow first (they were always `None` there). `RefInfo`
  and variants are now keyword-only dataclasses (`kw_only=True`) — required so a
  variant can add a mandatory field (`BackRefInfo.via`) after the base's
  defaulted `key_type`. Nothing in the project constructs `RefInfo` positionally
  (only `_resolve` does, by keyword).
- `.many` kept on the base (cheap, documented, shape-derived).
- Runtime-safe for existing readers: `.via` is only read on backref edges,
  `.scope` only on embedded edges, `.key_type`/`.many` on the base — verified
  across tests and examples before the change.

---

# API decision record — round 10 (diagram export)

Phase 2 output, 2026-06-10. Export prism structure to graph formats. See
docs/design-round-10.md.

## 55. Graphs → all three (scope / projection / relationship)

Options: all three (recommended) / a subset.
**Chosen: all three.** `scope_diagram(*scopes)` (the `Scope` hierarchy,
ancestors pulled in, partial scopes styled), `projection_diagram(model)` (a
canonical and its generated projections, with surviving fields), and
`RefGraph.diagram()` (cross-model `ref`/`backref`/`embedded` edges, reachable via
`walk()`). They answer different questions and share one IR, so each builder is
cheap. "Generated models" is most literally the projection landscape; the
relationship graph is what people usually mean by a model diagram — hence both.

## 56. Formats → Mermaid + DOT + D2 + `as_dict()`

Options: + D2 and `as_dict()` (recommended) / just the two musts / + PlantUML.
**Chosen: Mermaid, DOT, D2, and `as_dict()`.** Mermaid (`graph TD` flowchart) and
DOT (`digraph`) are the musts; D2 (modern, clean) is a natural third; `as_dict()`
exposes the JSON-serializable IR so any other tool/format is reachable without a
prism renderer (and makes the renderers trivially testable). PlantUML/GraphML are
niche — a one-function add via the IR later if asked, not carried now.

## 57. API → `Diagram` IR + builders + `.to_<fmt>()`

Options: `Diagram` value object (recommended) / free functions per (graph,
format).
**Chosen: the IR.** A backend-agnostic `Diagram` (nodes + directed edges) with
`.to_mermaid()` / `.to_dot()` / `.to_d2()` / `.as_dict()`. Builders:
`RefGraph.diagram()` (method, discoverable on the existing object),
`scope_diagram()` / `projection_diagram()` (top-level). One renderer per format
× one builder per graph beats a combinatorial grid of free functions, and the IR
is the seam that keeps "anything else?" cheap.

## 58. Detail → fields in nodes

Options: names-only (memo's lean) / include fields.
**Chosen: include fields** (owner's call). Model/projection nodes list their
fields (Mermaid `<br/>` lines, DOT `record`, D2 `shape: class`), so the
narrowing is visible (`OrderPublic` shows it dropped the Update-only field).
Scope nodes have no fields. Edges are labelled (`extends`, the scope name, or
`field (kind)`).

## Round-10 notes

- **No new dependency:** prism emits text only; the user pipes it to
  mermaid-cli / Graphviz / D2. Renderers handle id-sanitizing (`_Ids`, unique
  `[A-Za-z0-9_]`) and per-format label escaping.
- `direction` is `"TD"` or `"LR"`, mapped per format (`TD`→DOT `TB`→D2 `down`);
  an unknown direction raises `ValueError` at the builder.
- `RefGraph.diagram()` local-imports the builder to avoid a module cycle
  (`_diagram` imports `_refs`/`_scopes`/`_model` for its builders).

---

# API decision record — round 11 (preserve field metadata in derived objects)

Phase 2 output, 2026-06-10. "`Node.fields` — don't make them plain str … same
stands for most other prism-derived objects." See docs/design-round-11.md. The
audit found the *live* projection objects already preserve `FieldInfo`
(descriptions/annotations survive `_project`); the loss happens at two
serialization boundaries — the diagram IR (fixed here) and the codegen stubs
(also fixed, per the owner's call).

## 59. Diagram fields → structured `NodeField`, plus `Node.description`

`Node.fields` is now `tuple[NodeField, ...]` where `NodeField` carries `name`,
`type` (a display label off the annotation), and `description`
(`FieldInfo.description`). `Node` gains `description` (the model/projection
`__doc__`, or a scope's round-7 description). Visual renderers show `name: type`
(D2 class-native; Mermaid/DOT append) and the DOT node `tooltip`; **`as_dict()`
is lossless** — types and descriptions are always there, which is the point
("preserve metadata," not necessarily paint it into every format). Examples/
constraints stay out of the node (read the live model for more).

## 60. Codegen stubs → carry field descriptions as attribute docstrings

`prism gen` now emits each described field's `description` as an attribute
docstring (`field: T = …` then a `repr`'d string literal on the next line),
surfaced by pyright/Pylance on hover. Attribute docstrings were chosen over
`Field(description=...)` because they need no `Field()` call (so the type-correct
default rendering is untouched) and pyright shows them. The description is now
part of the drift `projection_signature`, so a doc change regenerates the stub —
and because round-7 per-scope descriptions live on the projection's `FieldInfo`,
each generated projection shows its scope-appropriate doc for free.

## Round-11 notes

- The two **non-lossy** derived objects were confirmed and left alone:
  projections (deep-copy `FieldInfo`) and `RefInfo`/`RefGraph` (structured).
- `_type_label` strips module paths for readable diagram labels
  (`list[uuid.UUID]` → `list[UUID]`); best-effort, display-only.

---

# API decision record — round 12 (diagram CLI + generated README)

Phase 2 output, 2026-06-10. See docs/design-round-12.md.

## 61. `prism diagram` → one verb, kind argument

`prism diagram {scope|projection|refs} [module:Name ...]
--format {mermaid,dot,d2,json} --output FILE --direction {TD,LR}`. `scope` takes
optional scope paths (none = all declared); `projection`/`refs` take exactly one
model path. Defaults: `mermaid`, stdout (`--output` writes a file), `TD`. `json`
emits the lossless `as_dict()` IR. Wrong-kind paths (a Scope where a model is
wanted, or vice versa) and a bad path-count raise `CodegenError` (exit 2). The
cwd is pushed onto `sys.path` so the target package imports under a console
script (which, unlike `python -m`, doesn't add cwd).

## 62. Generated README → config `readme=` + `--readme`, verified by `check`

`[tool.pydantic-prism] readme = "GENERATED.md"` (and/or `prism gen --readme PATH`
override) makes `gen` write a GitHub-flavoured markdown doc beside the stub, and
`prism check` verifies its freshness too — a stale README fails CI, mirroring the
stub's drift discipline exactly. No README is written unless configured.

## 63. README content → diagrams + field/description tables, by source

The README documents the generated workset grouped by `__prism_source__`: a
top-level scope-hierarchy Mermaid diagram, then per source model a
projection-fan-out Mermaid diagram, per-projection field tables
(name / type / description), and a relationship Mermaid diagram when the model
has edges. Diagrams are **Mermaid only** — the one format GitHub renders inline;
the round-11 `NodeField` metadata feeds both the diagrams and the tables (so
per-scope `scoped(..., description=...)` docs appear per projection).

## Round-12 notes

- `generate_readme(config)` recomputes the workset (cached projections, cheap)
  rather than threading it out of `generate()`; keeps stub and README rendering
  independent.
- Both new outputs carry do-not-edit banners; README cells escape `|`/newlines.

---

# API decision record — round 13 (auto-generated example READMEs)

Phase 2 output, 2026-06-10. Repo tooling, not a library API change. See
docs/design-round-13.md.

## 64. Example READMEs → script + subprocess freshness gate

`bin/gen_example_readmes.py` renders `examples/<name>/README.md` from each
example's scoped models via `build_readme`; `tests/test_example_readmes.py`
runs it `--check` in a **subprocess** so importing the example modules (with
their unrun `demo()`/`__main__` lines) never drops the 100% src-coverage gate.
A stale README fails CI, like `prism check`.

## 65. `build_readme` gained `regen_hint`; relationships gated on edges

The do-not-edit banner now names the producing command (`regen_hint`) — `prism
gen` for stubs, `python bin/gen_example_readmes.py` for examples — so the
"regenerate with" instruction is correct per artifact. The relationship section
is emitted only when the model's ref diagram has edges, so a backref-only model
(forward `walk()` empty) no longer renders a lone-node section.
