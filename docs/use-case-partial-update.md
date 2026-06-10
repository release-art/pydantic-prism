# Use case — best-in-class PATCH / partial-update views

Captured 2026-06-10 (market/feature dive). Positioning + feature note, parked
for the docs restructure. Related: [PII governance](use-case-pii-governance.md).

## The pain (well-documented, recurring)

"Make every field optional for a PATCH body" is one of the most repeated
pydantic/FastAPI questions — pydantic discussions
[#3089](https://github.com/pydantic/pydantic/discussions/3089),
[#12397](https://github.com/pydantic/pydantic/discussions/12397), a whole
dedicated library ([pydantic-strict-partial](https://pypi.org/project/pydantic-strict-partial/)),
and countless tutorials. prism already wins the **apply** half decisively:
`partial=True` scopes + `with_updates` (re-validating, nested-aware) are better
than anything in the ecosystem.

## The gap

prism's partial makes every surviving field `T | None` with `default=None`.
That is exactly the **"everything is nullable"** complaint the community keeps
raising:

- OpenAPI marks every field nullable → the schema lies about the contract.
- You cannot distinguish *absent* ("don't touch") from *explicit null* ("clear
  this field") — yet `with_updates` already relies on `exclude_unset` to mean
  the former. The type says `None` is a legal value; the semantics say it
  sometimes means "unset". That mismatch is the sharp edge.

pydantic 2.12 shipped the `Missing` sentinel precisely for this:
**optional-but-not-nullable** — a field that may be absent without becoming
`T | None`.

## The bet

Adopt the `Missing`-sentinel shape for `partial=True` so a partial projection
is *optional, not nullable*:

- absent → not in `model_dump(exclude_unset=True)` → "don't touch" (today's
  behavior, now type-honest)
- explicit `None` → only legal where the canonical field is itself `T | None` →
  "clear it"
- OpenAPI shows fields as not-required rather than nullable.

This makes prism's Update view strictly the best available — it already owns the
apply side; this fixes the build side. Also a correctness win for our own
codebases.

## Scope / open questions

- Gate on pydantic >= 2.12 for the sentinel; decide the fallback story for
  older pins (keep the `T | None` shape, or require 2.12 for `partial=True`).
- `with_updates` semantics are mostly unchanged but should be re-checked against
  the absent-vs-null distinction now that the type encodes it.
- Interaction with carried bases and nested partial propagation needs a test
  pass (100% cov + pyright-strict bar).
