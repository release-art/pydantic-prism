# Use case — CQRS commands & read models

Captured 2026-06-10 (third dive). Positioning + feature note, parked for the
docs restructure. **Moderate conviction** — clean for the field-shape slice, but
the hard parts of CQRS/event-sourcing are outside prism's boundary; record
honestly.

## The pain

CQRS separates the **command/write** model (optimized for updates) from the
**read model** (denormalized, "designed around questions"), and event-sourced
systems additionally **version events** and **upcast** old ones to the latest
shape ([Azure CQRS](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs),
[read models](https://www.cqrs.com/event-driven-architecture/read-models/),
[upcasting](https://artium.ai/insights/event-sourcing-what-is-upcasting-a-deep-dive)).
Each is a different shape of the same domain entity — the multi-face problem
again, for a DDD audience.

## Where prism helps

- **Command shape** as a scope: `Order.scope(PlaceOrder)` — only the fields a
  command carries (often also `partial=True` for partial commands; see
  [partial update](use-case-partial-update.md)).
- **Read-model field selection** as a scope, when the read model is a *subset*
  of the canonical entity (a focused query view).

## Where prism does NOT help (the honest part)

- **Upcasting** is a *transform* (old event version → new), and prism filters,
  never rewrites — same boundary as [API versioning](use-case-api-versioning.md).
  The `eventsourcing` library and per-slice upcasters own this.
- **Denormalized read models** are usually *joins/combinations* of multiple
  aggregates. prism narrows one model; it does not combine several. A read model
  that flattens Order + Customer + Line-items is not a prism projection.

So prism covers the *single-entity field-shape* slice of CQRS (command bodies,
subset read views) and should not over-claim the projection/upcasting machinery
that defines the pattern.

## The bet

A small docs note / example showing command-scope and subset-read-model-scope,
explicitly scoping out upcasting and denormalization. **Lowest priority of the
dive** — the audience is real but the slice prism owns is narrow; pursue only if
a concrete user asks.
