# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **`pydantic-prism check` is immune to formatter churn.** The generated stub is
  now compared by **AST** rather than byte-for-byte, so a `ruff format` (or any
  formatter) pass that only reshuffles layout — quotes, wrapping, trailing
  commas, blank lines — no longer reports the stub stale. Only a change in
  *meaning* (a model edit the stub doesn't reflect) fails the check; a stub that
  no longer parses is treated as stale. You no longer need to exclude the
  generated module from your formatter. The README, being Markdown, is still
  compared exactly.

## [0.6.2] - 2026-06-17

### Fixed

- **`src/`-layout discovery without a prior install.** `pydantic-prism gen` /
  `check` (and `diagram` / `flow`) resolve the configured paths with
  `importlib`, but only the `pyproject.toml` directory was put on `sys.path`, so
  a package under `src/` was unimportable unless an editable install had already
  added `src/` — breaking fresh CI checkouts and isolated runners
  (`pipx`/`uvx`/`pre-commit`) with `cannot import module`. prism now adds
  `<root>/src` to `sys.path` automatically when that directory exists.

### Added

- **`[tool.pydantic-prism] sys-path`** — list extra import roots (resolved
  relative to the `pyproject.toml` directory) to prepend to `sys.path` before
  discovery, for layouts other than flat or `src/`. Pure addition.

### Changed

- **Generated-stub banner names the real console script.** The do-not-edit
  header now reads `pydantic-prism gen` / `pydantic-prism check` instead of the
  bare `prism` (which is not an installed entry point and collides with `pyenv`
  shims). Docs use the same canonical spelling. The banner is a comment, so the
  now-AST-based `check` ignores it — upgrading needs no regeneration.

## [0.3.0] - 2026-06-10

### Added

- **`ScopedModel.run_inherited_before(data)`** (also on `Projection`) — run a
  model's inherited `@model_validator(mode="before")` hooks explicitly, in
  pydantic order (nearest ancestor first). Call it inside a
  `@scoped_validator(mode="before")` whose logic depends on a base hook's
  transformation; it replaces the brittle `Base.hook.__func__(cls, data)`
  descriptor dance and works on projections too. Pure addition. See
  [before-validator ordering](docs/how-to/carry-a-custom-base.md#before-validator-ordering-with-scoped_validator).
- **`parent_ordering="acknowledged"` on `@scoped_validator`** — assert a
  `before` validator does *not* depend on an inherited base hook, silencing the
  new ordering warning. Pure addition.
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
  Otherwise call `run_inherited_before` at the top of the validator, or silence
  with `parent_ordering="acknowledged"`. **Migration:** anyone using
  the `@scoped_validator(mode="before")` + custom-base pattern should review
  whether their child validators depend on the parent's transformation — and
  prefer `mode="after"` where the derivation allows it.

### Removed

- **Runtime stub-drift guard, and `StaleProjectionStubError`.** Generated stub
  modules no longer emit per-projection `assert_fresh(...)` calls, and the
  `StaleProjectionStubError` exception is removed. The runtime alias
  (`X = Model.scope(...)`) is recomputed live on every import, so it is never
  stale; only the static `TYPE_CHECKING` stub the type checker reads can drift,
  and `prism check` already catches that by regenerating the module and
  byte-diffing it. The runtime check guarded a consumer that doesn't exist at
  runtime, at the cost of per-projection work at every startup and an
  app-won't-boot failure mode for what is a CI/static-typing concern.
  **Migration:** ensure `prism check` runs in CI (it was already the
  recommended gate); no application code change is needed.

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
