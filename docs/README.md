# pydantic-prism documentation

One canonical pydantic model, many scoped projections — with a relationship
graph that survives them. These docs follow the
[Diátaxis](https://diataxis.fr) framework: four kinds of page, each doing one
job. Pick the column that matches what you need right now.

| | |
|---|---|
| **[Tutorial](tutorial/first-scoped-model.md)** — learning | One hand-held lesson: take a single model from definition to two working projections. Start here. |
| **[How-to guides](how-to/README.md)** — tasks | Short, goal-shaped recipes for a capability you already know you want. |
| **[Reference](reference/README.md)** — information | Dry and complete: the [API](reference/api.md), the [`prism` CLI](reference/cli.md), the [error table](reference/errors.md). |
| **[Explanation](explanation/README.md)** — understanding | The "why": the [scope algebra](explanation/scopes-and-the-algebra.md), [projections vs inheritance](explanation/projections-not-inheritance.md), [what `ref()` models](explanation/what-ref-models.md), [vs prior art](explanation/vs-prior-art.md). |

## All pages

### Tutorial
- [Your first scoped model](tutorial/first-scoped-model.md)

### How-to guides
- [Redact PII for an audit view](how-to/redact-pii.md)
- [Trace where classified data flows](how-to/trace-data-flow.md)
- [Build a PATCH / partial-update model](how-to/partial-update.md)
- [Use projections with FastAPI](how-to/use-with-fastapi.md)
- [Bridge a SQLModel or SQLAlchemy ORM](how-to/bridge-an-orm.md)
- [Carry a custom pydantic base onto projections](how-to/carry-a-custom-base.md)
- [Generate editor stubs (`prism gen`)](how-to/generate-editor-stubs.md)
- [Export scope / projection / relationship diagrams](how-to/export-diagrams.md)
- [Vary a field's schema per projection](how-to/vary-schema-per-scope.md)

### Reference
- [API reference](reference/api.md)
- [CLI reference](reference/cli.md)
- [Errors](reference/errors.md)

### Explanation
- [Scopes and the algebra](explanation/scopes-and-the-algebra.md)
- [Projections, not inheritance](explanation/projections-not-inheritance.md)
- [What `ref()` models — and what it doesn't](explanation/what-ref-models.md)
- [Compared to prior art](explanation/vs-prior-art.md)

### Project
- [Roadmap](../ROADMAP.md) — shipped / planned / declined
- [Changelog](../CHANGELOG.md)
