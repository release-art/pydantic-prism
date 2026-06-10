# Use case — data contracts (producer ↔ consumer schemas)

Captured 2026-06-10 (third dive). Positioning + feature note, parked for the
docs restructure. **Strong — and a new vertical** (data engineering, not just
web APIs).

## The pain

A *data contract* is an explicit, **versioned** agreement between a data
producer and its consumers about the shape and semantics of data — "treat data
like APIs". It was the hot data-engineering topic of 2023–24 and is now
mainstream (dlt schema contracts, dbt model contracts, Kafka schema registries).
The recurring practice from
[50 production implementations](https://medium.com/@reliabledataengineering/data-contracts-in-practice-what-50-production-implementations-actually-look-like-f1c953336bf2):
the *same* pydantic model validates the Kafka producer and the consumer, schema
versions are explicit and registry-tracked, and a **contract-test suite runs
before either side deploys** ([schema validation](https://medium.com/@brunouy/implementing-data-contracts-schema-validation-5aefa2b89332)).

The drift this fights — producer changes a field, consumer breaks silently — is
the exact problem prism's projections + drift guard already address, just on a
different surface than HTTP.

## Why prism fits — and the under-appreciated reuse

- **Producer / consumer as scopes.** One canonical event/record model; each
  consumer reads a subset → `Event.scope(BillingConsumer)`,
  `Event.scope(AnalyticsConsumer)`. A consumer that only needs three fields gets
  a projection with exactly those — and can't accidentally depend on fields
  outside its contract.
- **The drift guard *is* contract enforcement.** `prism check` /
  `StaleProjectionStubError` already detect "the model changed without
  regenerating the agreed shape". That is precisely the
  *contract-test-before-deploy* gate the data-contract literature prescribes —
  prism shipped the mechanism for a different reason and it transfers directly.
- **Refs model cross-dataset keys.** `ref()` / `__refs__` express "this column
  is a foreign id into that dataset" — lineage/joins between contracts, which
  schema-registry tooling does not capture.

## The bet

Mostly **framing + an example**, plus possibly a thin emitter:

- A `examples/data_contract/` showing a canonical event, per-consumer
  projections, and `prism check` wired as the contract-drift CI gate (Kafka
  producer/consumer validating with the same model).
- Position prism as "data contracts that don't drift, with a relationship graph"
  for the dbt/dlt/Kafka crowd.
- Possible: emit a JSON-Schema (or Avro-ish) artifact per projection for a schema
  registry — evaluate vs. just publishing `model_json_schema()`.

## Honest boundaries

- prism does **no** serialization formats (Avro/Protobuf), **no** schema-registry
  client, and **no** backward/forward **compatibility checking** (the "is v2 a
  safe successor to v1?" question). It owns the *shape + drift-vs-source* slice,
  not the wire format or the compatibility algebra.
- Schema *evolution/transform* (rename, type change) is out of scope, same as
  [API versioning](use-case-api-versioning.md) — prism filters, never rewrites.
