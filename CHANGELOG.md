# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
