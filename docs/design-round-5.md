# Design memo — round 5 (`@scoped_validator`)

Phase 1 output, 2026-06-10. Today field validators carry to projections, model
validators do not (decision 14). The asymmetry is defensible by implementation
(a model validator assumes the full canonical field set) but surprising as
user-facing semantics, and it silently broke SiteCompliance's Update-scope
hostname-from-webpages coercion (a `@model_validator(mode="before")`). This
round adds an explicit, opt-in model validator that survives projection:
`@scoped_validator(*scopes, mode=...)`. (Direction already chosen: the explicit
marker, not carry-by-default-with-opt-out.)

Context: scopes are classes; the field carry rule is
`projection_expr.selects(field_tag)` (`_surviving_fields`, [_model.py]); plain
`@model_validator` stays dropped (decision 14) — this adds a sibling, it does
not change the default.

## Mechanics (settled by experiment)

`@model_validator` stores each decorator in
`cls.__pydantic_decorators__.model_validators`; `.func` is the raw function for
`mode="after"` and a *bound method* for `before`/`wrap` (no `__dict__`, so the
scope tag cannot live on it). So `scoped_validator` records the tag in a
module-level `WeakKeyDictionary` keyed by the *raw* function, and `_collect`
resolves that into a per-class `__prism_validator_scopes__` map. Carrying re-adds
the matching validators via `create_model(__validators__=...)` (re-wrapping the
classmethod for before/wrap, as `_carry_validators` already does for field
validators) — verified to run identically on the projection.

## Q1. Form

Options: `@scoped_validator(*scopes, mode=...)` decorator (recommended) /
`@model_validator(..., scopes=...)` wrapper-extension / carry-by-default + an
opt-out marker.
**Recommend the dedicated decorator.** It reads as a sibling of `@model_validator`
with one added duty — "this validator is meaningful for *these* projections" —
and it composes with prism's own vocabulary (`scoped()` / `.scope()`). Extending
pydantic's `@model_validator` signature means wrapping/shadowing a third-party
decorator we don't own (fragile across pydantic versions). Carry-by-default
would silently push every model validator onto narrow projections whose field
set it never anticipated — the exact failure decision 14 avoids, inverted.
Plain `@model_validator` is unchanged: still canonical-only.

## Q2. Carry rule

Options: same algebra as fields — carry onto projection `E` iff `E.selects(tag)`
(recommended) / the listed scopes are documentation only and it carries to every
projection.
**Recommend the field rule.** A validator tagged `scoped_validator(Update)`
carries exactly where a field tagged `scoped(Update)` would survive — one
membership rule across the whole library, reusing `ScopeExpr.selects`. Varargs
and expressions both work (`scoped_validator(Public | Internal)`,
`scoped_validator(~Llm)`), as in `scoped()`. "Documentation only / carries
everywhere" reintroduces the silent-leak problem for any projection narrower
than the validator's safe set.

## Q3. Zero scopes

Options: require ≥1 scope; wildcard is `scoped_validator(Scope)` (recommended) /
allow `scoped_validator()` meaning "all projections".
**Recommend require ≥1**, mirroring `scoped()` (which raises on no args). "Survives
every projection" is spelled `scoped_validator(Scope)` — the root scope is the
wildcard everywhere else, so there is no new convention to learn, and the common
real case is narrow anyway (the coercion belonged to Update, not to Public).

## Q4. Introspection

Options: expose `Model.__prism_validator_scopes__` (recommended) / none.
**Recommend exposing it** — `dict[str, ScopeExpr]` keyed by validator name,
the model-validator analogue of `__field_scopes__`. The whole reason for an
explicit marker over carry-by-default is that the resolved behavior should be
*obvious*; "which validators carry to this scope, and why" must be answerable
without reading prism internals. It is also where `_carry_validators` reads from
at projection time (registry → collected map → carry), so it is not extra
machinery, just a name on something that has to exist.

---

## Settled by fiat (stated, not asked)

- **`mode` is required and pass-through** (`"before" | "after" | "wrap"`),
  mirroring `@model_validator` exactly — same muscle memory, all three modes
  carried with their original mode.
- **Field-set safety is the user's responsibility.** A carried `mode="after"`
  validator that reads `self.dropped_field` raises at validation — the explicit
  scope list *is* the user's assertion "these projections keep the fields I
  touch." Prism cannot know which fields a `mode="before"` dict-coercion needs,
  so it does not try; documented loudly (parallels the decision-14 caveat for
  field validators reading dropped `info.data`).
- **Bad scope argument** (`scoped_validator("storage")`) raises `TypeError` at
  decoration via `as_expr`, consistent with `scoped()` and decision 13.
- **Inheritance / carried bases:** a `scoped_validator` on a base `ScopedModel`
  is inherited (it is in the subclass's `model_validators`, keyed by the same
  raw function in the registry) and carries to the subclass's projections.
  Carried-base model validators continue to ride along on the base itself.
