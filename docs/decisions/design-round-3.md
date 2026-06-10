# Design memo — round 3 (class-level default scope)

Phase 1 output, 2026-06-10. One feature: let a model declare a default scope
once at class level so fields in the dominant scope need no per-line
`scoped(...)` marker, while explicit markers keep working as deviations.

Context that constrains everything below: scopes are **classes**, not strings
(decision 5); untagged fields belong to **no** scope today (decision 2);
`__field_scopes__` is the resolved selection map every projection reads
(`_collect` in [_model.py:331]); class keywords (`projection_bases=`) are set
in `__init_subclass__` and inherited as plain class attributes (decision 17).

The mechanism is small: today `_collect` only writes a field into
`__field_scopes__` when it carries a `Scoped` marker. The whole feature is
"for a field with no marker, fall back to the class default if one is
declared." Everything downstream — projection, partial, refs, FastAPI —
reads `__field_scopes__` and is unchanged. The design work is entirely in the
*surface* and the *edge semantics*, not the engine.

---

## 1. Spelling

Options: `default_scope=` (singular) / `default_scopes=` (always tuple) /
`field_scope=` / `implicit_scope=`.

**Recommend `default_scope=` (singular).** It mirrors the two nouns already on
the surface — the `scoped()` marker and `Model.scope()` — and reads exactly as
the feature behaves: "this model's default scope." `field_scope=` invites the
misreading "the scope of *a* field"; `implicit_scope=` names the mechanism
(implicitness) rather than the thing, and the Zen tilts against advertising
implicitness in the keyword itself. `default_scopes=` presumes the tuple answer
to Q2 and clashes with the singular `.scope()`. Singular wins on consistency.

## 2. Multiple defaults

Options: single `ScopeLike` only, `|` for unions / accept a tuple
(`default_scope=(Public, Internal)`) as union sugar.

**Recommend single `ScopeLike` (a `Scope` class or a `ScopeExpr`); use `|` for
multiple.** "In both Public and Internal" is already spelled `Public | Internal`
everywhere else in the library — the union operator is load-bearing in tags and
in `.scope()`, so reusing it keeps one mental model. A tuple would be a *third*
spelling of union (varargs in `scoped()`, `|` in expressions, tuple here) and
would make `default_scope=(A, B)` look like `projection_bases=(A, B)` while
meaning something algebraically different. The singular keyword and a single
expression value reinforce each other.

## 3. Inheritance

A subclass's untagged fields, and the role of `projection_bases=`.

**Recommend: `default_scope=` inherits like `projection_bases=` — a subclass
without its own declaration uses the nearest ancestor's; re-declaring
overrides.** This is free: the value is a class attribute set only when the
keyword is given, so attribute lookup walks the MRO. `_collect` resolves every
field of the class (inherited fields included) against the class's *effective*
default, so an inherited untagged field re-defaults to a subclass's new
default. That is the one-step-obvious reading of "this model's fields default
to X" and keeps `__field_scopes__` a pure function of the class. `projection_bases=`
interaction is a non-issue: carried bases are *plain pydantic* classes, which
cannot carry a `default_scope` (it is a `ScopedModel` keyword) — the default
comes only from the `ScopedModel` MRO. Tradeoff: a subclass that overrides the
default silently re-scopes inherited untagged fields; acceptable, since untagged
means "I didn't pin this," and the resolved map is introspectable (Q6).

## 4. Merge vs replace

Explicit `scoped(Public)` on a field of a `default_scope=Storage` model →
`{Public}` or `{Public, Storage}`?

**Recommend replace: explicit wins, no merge → `{Public}`.** The default exists
to fill the *blank* lines; a line that already says `scoped(...)` is not blank.
Merging would make `scoped(Public)` mean different things on different classes
(silently widened by whatever the class default is), which is exactly the
non-local surprise the explicit-over-implicit principle guards against. "Default
applies iff no marker" is the only rule that keeps an explicit tag's meaning
self-contained. If a user genuinely wants both, `scoped(Public, Storage)` says
so on the line.

## 5. EmptyProjectionError / backward compat

**Confirm: the error stays for genuinely untagged fields on classes *without*
`default_scope=`.** The feature is purely additive — `default_scope` only
changes classes that opt in. On those, formerly-untagged fields now resolve to
the default and no longer trip `EmptyProjectionError`; on every other class the
behavior (untagged → no scope → empty projection raises) is byte-for-byte
unchanged. A model with neither markers nor a default still raises on `.scope()`,
which is the desired safety net (a forgotten tag must not silently vanish). The
feedback's "inferred-base (`Scope` root)" concern resolves the same way: nothing
about the root scope changes; only the opted-in class gains a fallback.

## 6. Introspection

Does `__field_scopes__[field]` return the *resolved* scope (with the class
default folded in) or only what the line annotated?

**Recommend resolved, and additionally expose the class default verbatim.**
`__field_scopes__` is the engine's selection map; if it did *not* fold in the
default, it would disagree with what projection actually does, and debugging
"why did this field survive?" would require mentally re-running the fallback.
Resolved keeps one source of truth. Truthfulness is preserved by a second,
honest read: a new `Model.__prism_default_scope__` ClassVar (the `ScopeExpr` or
`None`) exposes the default itself, so a reader can always reconstruct
"explicit vs defaulted" by comparing. Resolved-for-behavior, raw-for-provenance
— both available, neither lossy.

## 7. `partial=True` interaction

**Confirm: partial flows through default-scoped fields identically.** Once a
field is in `__field_scopes__` — whether via a marker or the class default —
nothing downstream can tell how it got there. `is_partial()`, the
`T | None` / `default=None` rewrite, and scope propagation all key off the
resolved expression, so a `default_scope=Internal` model projected to a partial
`Update` (which extends `Internal`) makes its default-scoped fields optional
exactly as it would explicit ones. No code path special-cases the origin; the
test exists to nail the invariant, not to drive new logic.

## 8. Error: bad `default_scope=` value

**Recommend class-definition time, `TypeError`.** Because scopes are classes, an
"undefined scope" is a `NameError` at the point of writing `default_scope=Foo` —
Python raises before prism runs. The reachable misuse is a *wrong-typed* value
(`default_scope="storage"`, `default_scope=42`, a non-`Scope` class), and
`as_expr()` already raises a clear `TypeError` for exactly that. Calling it
eagerly in `__init_subclass__` surfaces the error at class definition, matching
decision 13 (eager structure, lazy resolution) and the rule that API-misuse is
`TypeError`, not a `PrismError`. No new error class is needed.

---

## Sub-decisions to confirm in phase 2

- **Uniform fallback.** The default fills the scope of *any* field lacking a
  `scoped()` marker, including `ref()`/`backref()` fields (which today stay out
  of every projection per decision 15). Lean: uniform — "all my untagged fields
  default to X" should not carve out ref fields; a user who wants a backref out
  of the default tags it `scoped(...)` explicitly, or splits it onto a class
  without the default. Cheap to test, one-step obvious.
- **Value type.** `default_scope` accepts a `ScopeLike` (`type[Scope]` or
  `ScopeExpr`), coerced via the existing `as_expr`. No new coercion surface.
