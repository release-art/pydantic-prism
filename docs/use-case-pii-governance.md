# Use case — schema governance (PII classification + data-flow)

Captured 2026-06-10 after a market/feature web-dive. This is a **positioning +
feature** note, not a design memo — parked here for the upcoming docs
restructure. Runnable prototype: [`examples/pii_dataflow/main.py`](../examples/pii_dataflow/main.py).

## The bet

Reposition prism from *"one model, many faces"* (crowded — pydantic-extension,
pydantic-views; and pydantic is absorbing field-filtering natively via
`exclude_if` and polymorphic serialization) to **schema governance**: *classify
once, project safely, prove where data flows.*

The differentiator is the `RefGraph`, not the projections. No competitor — nor
the PII-detection libraries (DataFog, pii-codex) — connects field classification
to a relationship graph. That connection is the compliance artifact people pay
for, and `__refs__.walk()` already computes it.

## The insight: classification is an orthogonal scope dimension

A field carries its **visibility** scope (`Public < Internal < Storage`) plus,
optionally, a **classification** scope (`Pii`, `Secret`) — two `scoped()`
markers, unioned. prism's existing primitives then do the governance work with
no new machinery:

- **Redaction is set difference.** `Model.scope(Internal - Pii - Secret)` is an
  audit-safe view — replaces hand-maintained `model_dump(exclude=...)` scatter.
  Refs survive it, so the graph stays intact.
- **Classification detection** is `field_scope.matches(Pii)` (already exists).
- **Data-flow** is `__refs__.walk()`: *given this entry point, where does
  personal data flow, through which references?*

```
Classified data reachable from Order:
  Order.user_id    -> User      ⮑ email [Pii], phone [Pii], password_hash [Secret]
  Order.ship_to_id -> Address   ⮑ line1 [Pii], postcode [Pii]
  User.address_id  -> Address   ⮑ line1 [Pii], postcode [Pii]
```

The entire governance layer is ~40 lines on top of the **unmodified** public API
(see the prototype). That is the proof: the wedge is real; only ergonomics are
missing.

## Candidate library surface (to promote into core, with tests)

| prototype shim | proposed API | rationale |
|---|---|---|
| `class Pii(Scope)` ad hoc | a `Classification` marker distinct from visibility `Scope` | keeps the two axes explicit; today nothing stops `scope(Pii)` being used as a visibility level, and it lets `prism gen` name views sanely |
| `Model.scope(Internal - Pii - Secret)` | `Model.redacted(strip=..., visible=...)` | the common "audit/log view" shouldn't require knowing the algebra |
| `dataflow_report(Order)` | `Model.classified_flow()` / CLI `prism flow` | emit JSON/Mermaid for compliance review |

Open design question: classification and visibility currently share one scope
lattice, so a careless `scope(Pii)` returns "all PII fields" — useful but it
blurs the axes. A dedicated `Classification` type (still backed by the same
expression engine) would keep them honest.

## Adjacent Tier-1 bets from the same dive

- **Fix the `partial=True` nullable trap.** prism makes every field `T | None`
  with a `None` default — the exact "everything is nullable, OpenAPI is now
  wrong, can't distinguish absent from explicit-null" complaint the community
  keeps raising. Adopt optional-but-not-nullable (pydantic 2.12 `Missing`
  sentinel).
- **A first-class LLM tool-schema scope** — drop ids/internal fields, lean on
  the existing per-scope `description` metadata; ship a pydantic-ai / Instructor
  recipe.
