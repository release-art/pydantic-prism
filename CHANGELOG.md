# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
