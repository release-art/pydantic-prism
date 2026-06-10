# Use case — a first-class LLM tool-schema scope

Captured 2026-06-10 (market/feature dive). Positioning + feature note, parked
for the docs restructure. Related: [PII governance](use-case-pii-governance.md).

## The pain

Tool-calling / structured-output is a large and growing audience (pydantic-ai
~17k stars, Instructor, Outlines, the whole function-calling wave). The
canonical model is wrong for the LLM: it carries UUIDs, internal ids, storage
fields, and audit columns the model should never see or hallucinate. Today
people hand-tag [`SkipJsonSchema`](https://ai.pydantic.dev/tools/) field by
field, or hand-maintain a parallel "LLM input" model — the exact drift prism
exists to kill.

## Why prism is already most of the way there

An LLM view is just another scope — and prism already has the two pieces that
make it good rather than merely smaller:

- **Field filtering** — `class Llm(Scope)`; tag the fields the model should see.
  Drop ids/internal fields by simply not tagging them `Llm`.
- **Per-scope descriptions** — prism already supports per-scope field
  `description` / `examples` on the `scoped(...)` marker. The LLM *reads
  descriptions*; being able to write model-facing prose that differs from the
  API-facing prose, on one canonical field, is a real and underused advantage.

```python
class Ticket(ScopedModel):
    id: Annotated[UUID, scoped(Public)]                       # not Llm → invisible
    title: Annotated[str, scoped(Public, Llm,
                                 description="Short human summary of the issue")]
    severity: Annotated[str, scoped(Llm,
                                    description="One of: low, medium, high, critical")]

TicketTool = Ticket.scope(Llm)            # clean tool schema, model-facing prose
```

## The bet (ergonomics + a recipe)

The mechanism exists; what's missing is a blessed convention and the
last-mile glue:

| today | proposed |
|---|---|
| `Ticket.scope(Llm).model_json_schema()` + manual massaging | `Model.tool_schema(scope=Llm)` — emits a provider-clean JSON schema (no `$defs` cruft, additionalProperties handled) |
| copy/paste into pydantic-ai / Instructor | a documented recipe + example wiring `Model.scope(Llm)` straight into both |

## Open questions

- Whether this is just docs + an example (the scope already works) or warrants a
  thin `tool_schema()` helper that normalizes the schema for OpenAI/Anthropic
  strict modes.
- Validation of LLM *output* back into the canonical is just `from_projection` /
  `with_updates` — worth showing in the recipe as the round-trip.
