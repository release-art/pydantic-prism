# How-to guides

Short, goal-shaped recipes. Each assumes you already know you want the result
and shows the shortest correct way to get it. New to prism? Start with the
[tutorial](../tutorial/first-scoped-model.md) first.

## Governance

- [Redact PII for an audit view](redact-pii.md) — strip every classification
  from a view with `Model.redacted(...)`.
- [Trace where classified data flows](trace-data-flow.md) — produce a
  compliance artifact with `classified_flow()` and `prism flow`.

## Shapes & round-trips

- [Prevent mass-assignment with read-only / write-only fields](prevent-mass-assignment.md)
  — `input()` / `output()` and the `In` / `Out` direction axis.
- [Build a PATCH / partial-update model](partial-update.md) — all-optional
  views with `partial=True` and `with_updates`.
- [Vary a field's schema per projection](vary-schema-per-scope.md) — per-scope
  `description` / `examples`.

## Integration

- [Use projections with FastAPI](use-with-fastapi.md) — one object, many
  documented response shapes.
- [Bridge a SQLModel or SQLAlchemy ORM](bridge-an-orm.md) — make the table the
  canonical and derive the DTO faces.
- [Carry a custom pydantic base onto projections](carry-a-custom-base.md) —
  keep base behavior and `isinstance` identity.

## Tooling

- [Generate editor stubs](generate-editor-stubs.md) — make projections
  visible to pyright/Pylance/mypy with `prism gen`.
- [Export scope / projection / relationship diagrams](export-diagrams.md) —
  Mermaid, DOT, D2, or JSON.

Every capability above is shipped and tested. For what's coming and what is
deliberately out of scope, see the [roadmap](../../ROADMAP.md).
