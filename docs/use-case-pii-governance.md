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

## Candidate library surface — **shipped in round 16**

Promoted into core with tests (decisions #68–#72, `docs/design-round-16.md`):

| prototype shim | shipped API | notes |
|---|---|---|
| `class Pii(Scope)` ad hoc | `Classification` base (a `Scope` subclass) | a classification *is* a scope, so the algebra is reused; the distinct base partitions the two axes |
| `pii_inventory` / `classifications_of` | `Model.classifications()` / `Model.classified_fields()` | read the classification atoms off each field's tag |
| `Model.scope(Internal - Pii - Secret)` | `Model.redacted(Internal)` | `strip=` defaults to *all* classifications on the model — new PII auto-redacts |
| `dataflow_report(Order)` | `Model.classified_flow()` → `FlowReport` + CLI `prism flow` | `.as_dict()` (JSON) / `.to_mermaid()` for compliance review |

The open question — classification vs visibility sharing one lattice — was
resolved by **decision #68**: `Classification(Scope)` keeps the axes honest by
*type* (so prism can auto-derive redaction and reports) while still reusing the
one expression engine. `scope(Pii)` stays legal ("all PII fields"); the
governance helpers are the ergonomic path.

## Adjacent Tier-1 bets from the same dive

- **Fix the `partial=True` nullable trap.** prism makes every field `T | None`
  with a `None` default — the exact "everything is nullable, OpenAPI is now
  wrong, can't distinguish absent from explicit-null" complaint the community
  keeps raising. Adopt optional-but-not-nullable (pydantic 2.12 `Missing`
  sentinel).
- **A first-class LLM tool-schema scope** — drop ids/internal fields, lean on
  the existing per-scope `description` metadata; ship a pydantic-ai / Instructor
  recipe.
