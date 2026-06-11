# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
