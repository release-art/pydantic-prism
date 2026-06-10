# Design memo — round 15 (partial scopes via the Missing sentinel)

Phase 1 output, 2026-06-10. The one finding that *changes* existing behavior.
Today `partial=True` rewrites every surviving field to `T | None` with
`default=None` (decisions 24–25). Two problems: it **forces nullability** on
fields the canonical never allowed to be null, and "absent" reads as `None` at
the attribute level — indistinguishable from a real null without
`exclude_unset`. pydantic 2.12's missing sentinel fixes both.

## Verified mechanism

`pydantic.experimental.missing_sentinel.MISSING` (a `typing_extensions.Sentinel`,
added in **pydantic 2.12**; installed here is 2.13.4). A field typed
`T | MISSING` with `default=MISSING`:

| input | non-nullable `T \| MISSING` | nullable `T \| None \| MISSING` |
|---|---|---|
| omitted | value is `MISSING`, **auto-excluded** from `model_dump()` | same |
| `null` | **ValidationError** (not nullable) | accepted; dumps `{f: None}`, distinct from absent |
| a value | set | set |

JSON schema: field **not required**, and **not nullable** unless the canonical
was (`{"type": "string"}`, no `anyOf: null`). Plain `model_dump()` already omits
absent fields — no `exclude_none` needed. Verified, plus dynamic construction
(`info.annotation | MISSING`) and `create_model` with it.

## Proposed change (projection builder)

In `_project`'s partial branch, replace

```python
info.annotation = Optional[info.annotation]   # force nullable
info.default = None
```

with

```python
info.annotation = info.annotation | MISSING    # preserve nullability, add absent
info.default = MISSING
```

— so a required canonical field becomes optional-not-nullable, an `Optional`
canonical field becomes optional-**and**-nullable-**and**-absent-distinct (the
full PATCH triad). This **changes** behavior; it is not additive.

## Impact (all need re-checking)

- **`with_updates`** *improves*: it already uses `exclude_unset` (absent omitted,
  set-incl-null included), so patching a nullable field to `null` now works
  *distinctly* from leaving it absent, and a non-nullable field can no longer be
  nulled by a patch (ValidationError at patch construction). Re-test round 6.
- **Nested partial propagation**: a nested partial model field becomes
  `NestedPartial | MISSING` (default MISSING) instead of `Optional[...]`/None.
- **Carried bases**: partial + `projection_bases=` — re-test.
- **Tests/examples that read `update.x is None` for absent** must become
  `update.x is MISSING`; JSON-schema tests asserting nullability/`default=None`
  flip to not-required/not-nullable; `examples/partial_update` + README "Partial
  scopes" prose (`T | None`) update.

## Costs — the real decision

1. **Breaking** for anyone relying on partial fields being `T | None`/`None`
   (attribute reads, nullable JSON schema, `model_dump(exclude_none=...)` habits).
   Pre-1.0, but notable; documented loudly.
2. **pydantic floor bump `>=2.7` → `>=2.12`** — drops support for 2.7–2.11.
3. **Depends on an `experimental` pydantic API.** `missing_sentinel` may change
   without a major bump — a stability liability for a library. Mitigations: it's
   ~3 lines isolated in `_project` (trivial to revert/swap), and a narrow
   import. But it is the honest sticking point.

## Open questions

1. **Adopt (replace) / keep current / opt-in.** Replace is the proposal's intent
   and the clean model; opt-in (a knob to choose MISSING vs None-default) keeps
   the stable default off the experimental API but adds awkward surface.
2. **Nullability:** preserve the canonical's (recommended — `Optional`→nullable,
   required→not-nullable) vs the proposal's flat "not-nullable always" (would
   wrongly reject `null` on an `Optional` canonical field).
3. **Accept the floor bump to 2.12 + the experimental dependency?**
