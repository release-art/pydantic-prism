# Design memo — round 8 (partial round-trip story + doc-debt audit)

Phase 1 output, 2026-06-10. Two items, both doc-centred.

## Item 7 — doc debt: already paid (audit)

The feedback ("README/CHANGELOG still don't mention `projection_bases=`,
`KEYED_DICT`, `partial=True`, `Model.scopes()`") predates this branch's round-2/3
documentation work. Current state, audited:

| topic | README | CHANGELOG |
|---|---|---|
| `projection_bases=` | "Custom pydantic bases" section + API-ref row (7 mentions) | round-2 Added entry |
| `KEYED_DICT` / `RefShape` | "Dict-keyed refs" section + `RefShape` API-ref row (4 mentions) | round-2 Added + Changed |
| `partial=True` | "Partial scopes — the Update model" section (4 mentions) | round-2 Added entry |
| `Model.scopes()` | API-ref row + error-message note (2 mentions) | round-2 Added entry |

All four have substantive coverage (dedicated sections, not passing mentions).
**No new work is warranted beyond a light consistency pass.** Manufacturing
redundant doc edits would be dishonest churn; the honest deliverable here is to
report that it is done and verify it stays done (a README example test covers
each).

## Item 6 — partial projection → canonical round-trip

Symmetric to the partial story. `from_canonical` (canonical → projection) works.
The reverse for a **partial** projection had "no good story" *when the feedback
was written* — but round 6 shipped exactly it: `baseline.with_updates(patch)`
overlays a partial's set fields onto an existing canonical instance, pulling the
**dropped/unset fields from the baseline**. So the answer to "what happens to
the dropped fields? Pull from a baseline?" is **yes — that is `with_updates`.**

The two reverse round-trips, made explicit:

| you have | you want | use | dropped fields come from |
|---|---|---|---|
| a **full** projection + the rest | a fresh canonical | `Model.from_projection(proj, **extra)` | `**extra` / canonical defaults |
| a **partial** patch + an existing record | the updated canonical | `baseline.with_updates(patch)` | the **baseline** instance |

### The remaining sharp edge: `from_projection` on a partial

Verified: `from_projection(partial)` dumps the partial *including its unset
fields as `None`* (no `exclude_unset`) and validates that as a canonical — which
fails with a **misleading** `ValidationError` ("id: Input should be a valid
integer") that blames a field instead of naming the misuse. A partial projection
is a *delta*, not a complete record; building a standalone canonical from a delta
is conceptually wrong without a baseline.

**Recommend a guard:** when `from_projection` receives a partial prism projection,
raise a clear error pointing to `with_updates` (and to building from a non-partial
projection), instead of the confusing validation failure. This matches the
library's fail-loud-with-guidance ethos (decision 13). It removes one unusual
ability — `from_projection` on a *fully-populated* partial plus extras — but that
is a misuse of `partial` (such a caller should use the non-partial scope), so
pushing them to the right tool is correct. Plain (non-prism) `BaseModel` inputs
are unaffected; the guard only fires for a `Projection` whose scope `is_partial()`.

Open question for phase 2: **guard (error) vs docs-only** (the feedback's floor
was "Document, even if you don't add code"). Recommend the guard — the current
error is actively misleading, and a delta-without-baseline has no correct
meaning.

## Deliverables

- Docs: a "Round-trips & PATCH" clarification (the table above) wiring
  `from_canonical` / `from_projection` / `with_updates` together and stating
  where dropped fields come from; `from_projection` docstring note.
- (If approved) the partial guard in `from_projection` + test.
- CHANGELOG entry; report item 7 as already-paid (audited), no churn.
