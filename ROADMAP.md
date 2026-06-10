# Roadmap

What is shipped, what is planned, and what is deliberately out of scope.
This consolidates the strategy notes that used to live in `docs/use-case-*.md`.
The honest boundaries are kept on purpose — they describe where prism stops.

## Shipped

Each of these is importable from `pydantic_prism`, exercised by a test, and
documented. Links go to the how-to guide.

| Capability | What it gives you | Guide |
|---|---|---|
| Scoped projections | One canonical model → real `BaseModel` subclasses per scope, cached and identity-stable | [Tutorial](docs/tutorial/first-scoped-model.md) |
| Scope algebra | `\| & - ~` over user-defined `Scope` classes, in tags and at the call site | [Explanation](docs/explanation/scopes-and-the-algebra.md) |
| Relationship graph | `ref()` / `backref()` markers, `__refs__`, survives projection | [Explanation](docs/explanation/what-ref-models.md) |
| Partial / PATCH views | `partial=True` scopes (`MISSING`-sentinel), `with_updates` to apply a delta | [Build a PATCH model](docs/how-to/partial-update.md) |
| PII classification & redaction | `Classification` axis, `Model.redacted(...)` audit views | [Redact PII](docs/how-to/redact-pii.md) |
| Data-flow reports | `Model.classified_flow()` → `FlowReport`, `prism flow` CLI | [Trace data flow](docs/how-to/trace-data-flow.md) |
| Diagram export | scope / projection / ref graphs → Mermaid, DOT, D2, JSON; `prism diagram` | [Export diagrams](docs/how-to/export-diagrams.md) |
| Editor stubs + drift guard | `prism gen` / `prism check`, `StaleProjectionStubError` | [Generate editor stubs](docs/how-to/generate-editor-stubs.md) |
| Custom pydantic bases | `projection_bases=` / `bases=`, `isinstance`-true projections | [Carry a custom base](docs/how-to/carry-a-custom-base.md) |
| FastAPI integration | Projections as `response_model=`; one object, many documented shapes | [Use with FastAPI](docs/how-to/use-with-fastapi.md) |
| ORM / SQLModel bridge | Make a SQLModel table or SQLAlchemy row the canonical; derive the DTO faces | [Bridge an ORM](docs/how-to/bridge-an-orm.md) |
| Per-projection schema metadata | Per-scope `description` / `examples` / `json_schema_extra` | [Vary a field's schema](docs/how-to/vary-schema-per-scope.md) |

## Planned

Bets with real demand, listed with the honest boundary that gates each one.

- **A first-class LLM tool-schema scope.** The mechanism — a field-filtering
  scope plus per-scope `description`/`examples` — already works. What is
  missing is a blessed convention and possibly a thin `tool_schema()` helper
  that normalizes the schema for OpenAI/Anthropic strict modes.
- **Read-only / write-only field convention.** `In` / `Out` scopes prevent
  mass-assignment *by shape, not a runtime check*. The one open decision:
  whether input projections should default to `extra="forbid"` or expose it
  on `.scope(...)`.
- **Entitlement / plan-tier gating docs.** Scope inheritance models a
  Free < Pro < Enterprise ladder cleanly. Boundary: prism gates field
  **presence** only — never numeric limits ("max 5 projects"), rate limits,
  or boolean feature toggles. That is the entitlement-config layer's job.
- **Data-contract framing + emitter.** `prism check` / `StaleProjectionStubError`
  already enforce shape-vs-source drift, which is contract enforcement. A thin
  per-projection JSON-Schema/Avro emitter is the open build. Boundary: no
  serialization formats, no schema-registry client, **no** backward/forward
  compatibility checking.
- **Per-projection TypeScript codegen.** Extend `prism gen` with a `--ts`
  target, one interface per projection, reusing the staleness guard. The
  cheapest path composes `model_json_schema()` per projection with an existing
  JSON-Schema → TS tool rather than writing an emitter from scratch. Gated on
  the projection vocabulary stabilizing first.
- **PII overlay on diagrams + a `prism graph` alias.** The renderer is done;
  a classification overlay (`--pii`) is gated on the governance work, which
  has now landed.
- **API-versioning docs (add/remove slice only).** Scope difference models
  "removed in v2". Boundary: **field rename / type change across versions is
  out of scope** — prism filters fields, it never rewrites them.
- **CQRS / read-model docs note.** Lowest priority; pursue only on concrete
  demand. Boundary below.

## Considered & declined

Deliberately out of scope. These read as maturity, not gaps.

- **Field-level transformations between scopes** (rename, type change,
  upcasting). Prism filters fields; it never rewrites them. This recurs
  across API-versioning, data-contracts, and CQRS.
- **Denormalized / multi-aggregate read models.** Prism narrows *one* model;
  it does not join or combine several. A read model flattening Order +
  Customer + Line-items is not a prism projection.
- **Ref resolution, lazy loading, query builders, sessions, storage of any
  kind.** `__refs__` is introspection; turning ids into instances is your
  code. No sqlalchemy/sqlmodel/ormar imports ever ship in core. "Storage is
  your problem."
- **Referential-integrity enforcement on data.** Prism checks declaration
  consistency (`via=` line-up, keyed-dict key types), never data: a `UUID`
  pointing nowhere validates fine.
- **Carrying a `SQLModel` base onto a projection.** SQLAlchemy would try to
  map the derived class and fail. The bridge derives plain DTOs (`bases=()`);
  it is a mirror, not a merge.
- **Runtime sparse fieldsets** (GraphQL-style `?fields=...`). A different axis
  from prism's compile-time, statically-typed scopes; revisit only on real
  demand.
- **Computed fields on projections.** They are methods that may reference
  dropped fields; not copied.
- **`@model_validator` carryover from the canonical's own body.** Use
  [`@scoped_validator`](docs/reference/api.md#validators) or a carried base.
- **Typing the `Model.scope(...)` call site itself.** `prism gen` generates a
  referenceable class with real fields; it does not retrofit a precise return
  type onto the dynamic `.scope()` call.
