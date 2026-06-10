# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed — round 11 (preserve field metadata in derived objects)

- Diagram nodes preserve field metadata instead of bare names. `Node.fields` is
  now `tuple[NodeField, ...]` (`NodeField.name`/`.type`/`.description`), and
  `Node` gains `.description` (model/projection docstring, or a scope's round-7
  description). Visual renderers show `name: type` (+ DOT node tooltips);
  `as_dict()` is lossless (types + descriptions), so downstream tools keep
  everything. **Breaking:** `Node.fields` entries are `NodeField`, not `str`.
- `prism gen` now carries each field's `description` into the generated stub as
  an attribute docstring (surfaced by pyright/Pylance on hover), including
  per-scope descriptions from `scoped(Scope, description=...)`. Descriptions are
  part of the drift signature, so a doc change regenerates the stub.
- Audit note: the live projection objects (`.scope()`) and `RefInfo`/`RefGraph`
  already preserve field metadata — the flattening was only at the diagram and
  stub serialization boundaries, both now fixed.

### Added — round 10 (diagram export)

- Export prism structure to graph formats (text only — no Graphviz/Mermaid/D2
  dependency). Three builders return a `Diagram` that renders to `.to_mermaid()`,
  `.to_dot()`, `.to_d2()`, or `.as_dict()` (the JSON-serializable IR):
  - `scope_diagram(*scopes)` — the `Scope` inheritance graph (ancestors pulled
    in, partial scopes styled); no args = every declared scope.
  - `projection_diagram(Model)` — a canonical model and the projections it
    generates (one per scope), each node listing its surviving fields.
  - `RefGraph.diagram()` — the cross-model `ref`/`backref`/`embedded` graph
    reachable from a model.
  - All take `direction="TD"|"LR"`; `Diagram`, `scope_diagram`,
    `projection_diagram` are exported.

### Changed — round 9 (RefInfo discriminated by kind)

- `RefInfo` is now the **base** of three kind-discriminated variants:
  `IdRefInfo` (`kind="ref"`), `BackRefInfo` (adds `via: str`), and
  `EmbeddedRefInfo` (adds `scope: ScopeExpr | None`). `__refs__[name]` is typed
  as the base `RefInfo`; the `.outgoing` / `.incoming` / `.embedded` accessors
  now return the precise subtype (`dict[str, IdRefInfo]` etc.), so e.g.
  `incoming["x"].via` is a non-optional `str`. Narrow a base-typed edge with
  `isinstance` or `match info.kind`.
  - **Breaking:** `via` and `scope` have moved off the base `RefInfo` onto
    `BackRefInfo` / `EmbeddedRefInfo` respectively — reading them off a
    base-typed edge without narrowing is no longer valid (they were always
    `None` there anyway). `key_type` (shape-driven) and `.many` stay on the
    base. `RefInfo` and its variants are now keyword-only dataclasses.
  - Resolves the "RefInfo shape audit": committed to discriminated subtypes
    (the only clean axis is `kind`; `key_type` is shape-driven and stays on the
    base) rather than the bag-of-options.

### Changed — round 8 (partial round-trip story)

- `Model.from_projection()` now raises a clear `TypeError` when handed a
  **partial** projection (a delta, not a complete record), pointing to
  `with_updates` — previously it failed with a misleading `ValidationError`
  blaming an individual field. The partial → canonical round-trip is
  `baseline.with_updates(patch)` (round 6), which pulls the dropped fields from
  the baseline; `from_projection` remains the round-trip for *complete*
  projections (with `**extra` / defaults supplying what they dropped). README
  gains a "Which round-trip do I want?" table making this explicit.
- Doc-debt note: `projection_bases=`, `RefShape.KEYED_DICT`, `partial=True`, and
  `Model.scopes()` were already documented (README sections + API reference +
  earlier CHANGELOG entries); audited, no further changes needed.

### Added — round 7 (projection naming + scope schema metadata)

- `projection_name_template=` class keyword: set a house style for auto-named
  projections once (`"{model}_{scope}"` → `User_Public`) instead of threading
  `name=` through every `.scope()` call — cleaner OpenAPI/swagger component
  names. Placeholders `{model}`/`{scope}`; inherited down the MRO; call-site
  `name=` still wins. The result must be a valid Python identifier (validated at
  class definition — a non-identifier would break `prism gen` and OpenAPI refs).
- Scope-attached JSON-schema metadata (`description` / `examples` /
  `json_schema_extra`), so the same field can read differently per projection
  without parallel classes:
  - **Field-level** via `scoped(Scope, description=..., ...)` (one scope per
    schema-bearing marker; split membership across markers). Applies in
    projections that select the scope; on overlap the most-derived scope wins,
    unrelated overlaps raise.
  - **Model-level** via `Scope` class keywords (`class Public(Scope,
    description=...)`) → merged into the projected model's schema root; per-class
    (not inherited).
  - `Model.scope(...)` schema is purely additive: no effect on validation,
    membership, refs, or runtime shape; a pre-existing `json_schema_extra` (dict
    or callable) is preserved.

### Added — round 6 (`with_updates` patch API)

- `instance.with_updates(patch)` on `ScopedModel`: apply a (partial) projection
  as a PATCH and get back a new, re-validated canonical instance. Only the
  patch's explicitly-set fields apply (`exclude_unset` — absent means "don't
  touch", explicit `None` clears an optional field); the result is re-validated,
  so nested models are reconstructed and field/`@scoped_validator` validators
  run (unlike the bare `model_copy(update=patch.model_dump(exclude_unset=True))`
  boilerplate, which leaves nested fields as raw dicts). `patch` must be a
  projection of this model (any scope; partial `Update` is the usual source) —
  a projection of a different model raises `TypeError`. `self` is unchanged.

### Added — round 5 (`@scoped_validator`)

- `@scoped_validator(*scopes, mode=...)`: a model validator that survives
  projection. It is a normal `@model_validator` on the canonical model and also
  carries onto every projection whose scope expression selects one of `scopes`
  (the same membership rule as a `scoped(...)` field). Fixes the silent drop of
  `@model_validator` on projections (e.g. a `mode="before"` coercion that
  derives one field from another). Varargs/expressions allowed; root `Scope` is
  the wildcard; `mode` is required and pass-through (`before`/`after`/`wrap`).
  Plain `@model_validator` is unchanged (still canonical-only). Field-set safety
  is the user's: the scope list asserts the touched fields survive there.
- `Model.__prism_validator_scopes__` (`dict[str, ScopeExpr]`) exposes which
  model validators carry, and to what — the analogue of `__field_scopes__`.

### Added — round 4 (static-type visibility for projections)

- `prism gen` / `prism check` CLI (also `python -m pydantic_prism`): generates a
  module of checker-readable projection classes so pyright/Pylance (VSCode) and
  mypy see a projection's fields — `from myapp._prism import ScreenshotRef` is
  fully typed. Each projection is emitted as a `TYPE_CHECKING` shim class over
  the genuine `else: ScreenshotRef = Screenshot.scope(Ref)`, so the runtime
  object is the authentic cached projection (`ScreenshotRef is
  Screenshot.scope(Ref)`; validators, refs, carried bases, partial defaults,
  FastAPI all unchanged). Nested projections, partial scopes, and carried bases
  all render. Configured via `[tool.pydantic-prism]` (`output`, `modules` for
  per-atom discovery, optional `projections` list for unions / `name=`).
- Drift safety: every generated stub records a signature; `assert_fresh` (run at
  import of the generated module) raises the new `StaleProjectionStubError` if a
  model changed without regenerating, and `prism check` is a non-importing CI
  gate (exit 1 on drift).

### Added — round 3 (class-level default scope)

- Class-level default scope: `class Row(ScopedModel, default_scope=Storage)`
  makes every field with no `scoped(...)` marker fall back to `Storage`, so
  mostly-single-shape models annotate only the deviations. Takes one `Scope`
  class or a `ScopeExpr` (`default_scope=Public | Internal` for several); a
  non-`Scope` value raises `TypeError` at class definition. Explicit
  `scoped(...)` **replaces** the default (no merge). Inherited down the
  `ScopedModel` MRO like `projection_bases=` — a subclass that re-declares
  re-scopes inherited untagged fields; `default_scope=None` clears it. The
  fallback is uniform (it fills untagged `ref()`/`backref()` fields too).
- `Model.__prism_default_scope__` ClassVar exposes the resolved default
  (`ScopeExpr | None`) for introspection; `Model.__field_scopes__` now reports
  each field's **resolved** scope with the default folded in.

### Added — round 2 (adoption feedback)

- Custom-base composition: `class Row(CustomBase, ScopedModel,
  projection_bases=(CustomBase,))` carries the base onto every projection —
  custom `model_dump`/`model_validate`, base-declared model
  validators/serializers, methods, and `isinstance` identity all work on
  derived classes. Per-call override via `Model.scope(..., bases=(...))`
  (part of the cache key); calling `.scope()` without a declaration on a
  model whose base defines such behavior warns once per model
  (`projection_bases=()` silences). Carried-base fields that a scope tag
  cannot honor raise the new `ProjectionBaseError`.
- Dict-keyed refs: `Annotated[dict[UUID, Embedded], ref(Target)]` —
  the dict key is the foreign id. New `RefShape` StrEnum
  (`SCALAR | COLLECTION | KEYED_DICT`) on `RefInfo.shape` with
  `RefInfo.key_type`; key types are checked against the target id field at
  resolution time. `RefInfo.many` remains as a derived property.
- Embedded-model edges: fields typed as a projection
  (`list[Snapshot.scope(Carrier)]`) or a nested canonical model register
  `kind="embedded"` edges automatically — `RefInfo.target` resolves to the
  canonical, `RefInfo.scope` records the carrier's scope (`None` =
  reshapes with the outer projection). New `RefGraph.embedded` accessor;
  `targets()`/`walk()` include embedded edges.
- Partial scopes: `class Update(Storage, partial=True)` makes every
  projection to it all-optional with `None` defaults (canonical defaults
  dropped — PATCH semantics). An expression is partial iff all its atoms
  are; the flag inherits down the scope graph.
- `from_canonical` forwards `mode`, `by_alias`, `context`, `exclude_none`,
  `exclude_unset`, `exclude_defaults` to `model_dump`, and skips narrowing
  automatically when the instance's class overrides `model_dump`
  (`narrow=` overrides the auto-detection).
- `Model.scopes()` classmethod: the set of `Scope` classes used in field
  tags. `EmptyProjectionError` messages now list them.
- `ScopeExpr.atoms()` and `ScopeExpr.is_partial()`.
- Examples: custom-base composition, dict-keyed refs, embedded ref-records,
  partial Update models.

### Changed — round 2

- `__refs__` now includes auto-detected `embedded` edges for nested
  `ScopedModel`/projection fields; v0.1 models that nest models will see
  additional entries (`.outgoing`/`.incoming` are unaffected).
- `RefInfo` constructor signature changed: `many: bool` was replaced by
  `shape: RefShape` (+ `key_type`, `scope`); `info.many` still works as a
  read-only property.
- `dict[K, V]`-annotated ref fields now infer `KEYED_DICT` (v0.1 inferred
  `many=False`, which was quietly wrong).

### Added

- `ScopedModel` base class: tag fields on one canonical pydantic model with
  named scopes via `Annotated` metadata, derive real `BaseModel` subclasses
  per scope with `Model.scope(...)` — cached, deterministically named, with
  working validation, serialization, JSON schema, and FastAPI integration.
- Scopes as classes: `Scope` subclasses form the scope graph through Python
  inheritance (a subclass is a broader scope); the root `Scope` is the
  wildcard; untagged fields belong to no scope.
- Full scope algebra on classes and expressions: `|` (union), `&`
  (intersection), `-` (difference), `~` (complement), usable in `scoped(...)`
  tags and at `Model.scope(...)` call sites.
- Storage-agnostic relationship graph: `ref(Target)` forward references
  (string targets supported for cycles), explicit `backref(Target, via=...)`
  reverse references with `via=` validation, cardinality inferred from
  annotations, all introspectable through `Model.__refs__` (a `RefGraph`
  mapping with `.outgoing`, `.incoming`, `.targets()`, `.walk()`).
- Refs survive projection: `Order.scope(Public).__refs__` still knows
  `customer_id` points at `Customer`.
- Scope propagation into nested `ScopedModel` annotations (through
  `Optional`, unions, containers, `Callable`, and cyclic models).
- Round-trip helpers: `Projection.from_canonical(instance)` (alias-aware,
  recursively narrowed, safe under `extra="forbid"`) and
  `Model.from_projection(proj, **extra)`.
- `@field_validator`s carry over to projections for surviving fields;
  `@model_validator`s deliberately do not.
- Eager-structure / lazy-resolution error model: `TypeError` for marker
  misuse at class definition (markers as defaults, nested-`Annotated`
  markers, multiple ref markers), `EmptyProjectionError` /
  `ProjectionNameError` at `.scope()` time, `RefResolutionError` at
  `__refs__` access; all domain errors subclass `PrismError`.
- Marker collection refreshes after `model_rebuild()`, so models using
  `from __future__ import annotations` / forward references keep their tags.
- Thread-safe projection cache: builds commit only after forward-reference
  resolution, so the same expression always yields the same class object,
  including under free-threaded Python.
- Examples: a FastAPI app serving one model at public/internal shapes on
  different routes, and a three-model relationship graph with a minimal
  resolver built on `RefInfo`.

[Unreleased]: https://github.com/release-art/pydantic-prism/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/release-art/pydantic-prism/releases/tag/v0.1.0
