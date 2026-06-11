# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`ScopedModel.run_inherited_before(data)`** (also on `Projection`) — run a
  model's inherited `@model_validator(mode="before")` hooks explicitly, in
  pydantic order (nearest ancestor first). Call it inside a
  `@scoped_validator(mode="before")` whose logic depends on a base hook's
  transformation; it replaces the brittle `Base.hook.__func__(cls, data)`
  descriptor dance and works on projections too. Pure addition. See
  [before-validator ordering](docs/how-to/carry-a-custom-base.md#before-validator-ordering-with-scoped_validator).
- **`parent_ordering=` on `@scoped_validator`** — `"after_parent"`
  (`mode="before"` only) wraps the validator to run the inherited before-hooks
  first, so its body sees transformed data with no manual call;
  `"acknowledged"` asserts a `before` validator does *not* depend on an inherited
  base hook. Both silence the new ordering warning. Pure addition.
- **`PrismWarning`** base class for prism's advisory warnings (a `UserWarning`
  subclass), with `PrismBaseDropWarning` (the existing carried-base drop
  warning, now a dedicated subclass) and `PrismOrderingWarning` under it. Filter
  on `PrismWarning` to manage all prism warnings at once.
- **Read-only / write-only fields** — a `Direction` axis (`In` / `Out`) for
  tagging read-only and write-only fields, with `Model.input()` / `Model.output()`
  helpers deriving the request / response faces. `input()` drops read-only fields
  (mass-assignment protection by shape) and defaults to `extra="forbid"`;
  `output()` drops write-only fields. See
  [prevent mass-assignment](docs/how-to/prevent-mass-assignment.md).

### Changed

- **Before-validator ordering warning (behavior change).** Defining a
  `@scoped_validator(mode="before")` on a model that inherits a plain
  `@model_validator(mode="before")` now emits a `PrismOrderingWarning` at class
  definition (one-shot per `(class, validator)`): pydantic runs the scoped
  validator *first*, so a child depending on the base hook's transformation sees
  untransformed data. **Best fix: use `mode="after"`** when the value derives
  from already-parsed fields — no ordering race, no double-run, no warning.
  Otherwise pass `parent_ordering="after_parent"` / call `run_inherited_before`,
  or silence with `parent_ordering="acknowledged"`. **Migration:** anyone using
  the `@scoped_validator(mode="before")` + custom-base pattern should review
  whether their child validators depend on the parent's transformation — and
  prefer `mode="after"` where the derivation allows it.

## [0.1.0] - 2026-06-10

First public release. Requires Python >= 3.12 and pydantic >= 2.12. See the
[documentation](docs/README.md) for the full feature set.

### Added

- **Scoped projections** — tag one canonical `ScopedModel`'s fields with scopes
  and derive real, cached `BaseModel` subclasses per scope. Scopes are classes
  composed with a full set algebra (`| & - ~`).
- **Relationship graph** — `ref()` / `backref()` markers introspectable through
  `__refs__`, surviving projection; cardinality-aware, including dict-keyed and
  embedded edges.
- **Round-trips** — `from_canonical` / `from_projection`, plus `partial=True`
  PATCH scopes (`MISSING` sentinel) applied with `with_updates`.
- **Data governance** — a `Classification` axis with `redacted()` audit views
  and `classified_flow()` data-flow reports.
- **Tooling** — the `prism` CLI (`gen`, `check`, `diagram`, `flow`), generated
  editor stubs with a startup drift guard, and diagram export to Mermaid / DOT /
  D2 / JSON.
- **Integration** — FastAPI response models, custom pydantic bases on
  projections, per-scope schema metadata, and SQLModel / SQLAlchemy bridges.

[0.1.0]: https://github.com/release-art/pydantic-prism/releases/tag/v0.1.0
