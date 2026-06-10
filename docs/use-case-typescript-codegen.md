# Use case — per-projection TypeScript codegen (single source of truth across the stack)

Captured 2026-06-10 (second dive). Positioning + feature note, parked for the
docs restructure. **Strong demand, bigger build, partial overlap with existing
tools** — scope it carefully.

## The pain

"Pydantic models should be a generated artifact, not a manually maintained
parallel type system" is the stated goal of the whole FastAPI→TS toolchain. The
frontend needs TypeScript types that match the backend, and keeping them in sync
is a perennial drift source. Tools exist —
[pydantic-to-typescript](https://github.com/phillipdupuis/pydantic-to-typescript),
[openapi-typescript](https://github.com/marketplace/actions/pydantic-to-typescript),
orval, openapi-generator,
[datamodel-code-generator](https://github.com/koxudaxi/datamodel-code-generator)
— but they operate on the **whole model** (or the OpenAPI doc), not on prism's
*projections*.

## The gap prism is uniquely placed to fill

prism already has `prism gen` emitting Python stubs per projection, and a
**drift guard** (`assert_fresh` / `StaleProjectionStubError`) — machinery the
generic TS tools lack. The novel offering is **TypeScript types per projection,
with the same drift discipline**:

```
prism gen --ts myapp/_prism.ts        # AccountIn, AccountOut, UserPublic, … as TS interfaces
```

So `AccountIn` / `AccountOut` (see [read/write](use-case-readwrite-fields.md))
show up on the frontend as exactly the shapes the API accepts/returns — not the
canonical superset that pydantic-to-typescript would emit. One source of truth,
every face, *both languages*, drift-checked in CI.

## Why "bigger build, scope carefully"

- Real TS type mapping (unions, `Optional`, enums, nested models, `dict`/record
  types, dates-as-strings) is non-trivial — but the existing tools prove the
  mapping is well-trodden; prism's value-add is *per-projection + drift guard*,
  not reinventing JSON-schema→TS.
- **Cheapest viable path:** lean on `model_json_schema()` per projection + an
  existing JSON-Schema→TS step, rather than writing a TS emitter from scratch.
  Evaluate whether `prism gen --ts` should shell out / depend on openapi-typescript
  vs. emit directly.
- Risk: this is the largest of the parked use cases. Sequence it **after** the
  projection vocabulary stabilizes (read/write, governance) — the value is "TS
  for the *projections*", so the projections must be worth typing first.

## The bet

A `--ts` (and plausibly other targets) mode for `prism gen` that emits one
interface per projection with the same staleness guard as the Python stubs,
ideally by composing an existing JSON-Schema→TS tool rather than hand-rolling.
High ceiling (cross-stack single-source-of-truth is a strong story), but gated
on the core projection story being solid.

## Other codegen targets (same machinery, lower priority)

The "emit per-projection types in language/framework X, drift-guarded" pattern
generalizes. Noted so they aren't re-discovered as separate features:

- **GraphQL / Strawberry.** Strawberry's pydantic integration is *experimental*,
  forces a second class per type, and the generated types **don't run pydantic
  validation** ([docs](https://strawberry.rocks/docs/integrations/pydantic)) —
  so per-projection GraphQL types (one prism projection → one GraphQL type) is a
  real gap. Same emitter pattern as `--ts`.
- **MCP tool schemas** fold into the [LLM tool-schema](use-case-llm-tool-schema.md)
  note — an MCP tool input *is* a JSON-Schema projection; no separate work.

Each is "another target for the same per-projection + drift-guard engine", not a
new concept. Sequence all of them after the core projection vocabulary is solid.
