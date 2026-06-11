# Scopes and the algebra

A scope is a named audience for a field. Prism's whole engine rests on one
small set of decisions about how scopes are declared and combined. This page
explains them.

## Why scopes are classes, not strings

Every comparable library keys its views off strings or a fixed enum. Prism
makes scopes ordinary Python classes — `class Public(Scope): ...` — for three
concrete reasons. A typo becomes a `NameError` at the point you write it, not a
silently-new scope that quietly drops your field. Your editor autocompletes
scope names. And the tree semantics live where a Python reader already looks for
them: in the class hierarchy. The cost is one declaration line per scope, paid
once.

Because scopes are classes, a scope *expression* is type-checkable too. The
operators below are real methods on real objects, not string parsing.

## Why inheritance forms the graph

Scopes relate to each other by subclassing — and the direction is deliberately
counterintuitive: **a subclass is a *broader* scope, not a narrower one.**
`class Internal(Public)` reads as "Internal is a Public, and more": every field
visible in `Public` is also visible in `Internal`. You declare the narrowest
audience on each field, and broader audiences inherit the right to see it.

This gives the engine its single load-bearing primitive — the membership rule:

> A field tagged `T` is in projection `S` **iff** `issubclass(S, T)`.

That one rule decides field membership, which validators carry to a projection,
and which per-scope schema metadata applies. One rule, library-wide.

A corollary keeps you safe: **an untagged field belongs to no scope.** It lives
only on the canonical model and can never appear in any projection. A forgotten
tag cannot leak `password_hash` into a public view — the failure mode is a
missing field, not an exposed secret. (`default_scope=` is an explicit opt-in
that fills *blank* lines only; an explicit `scoped()` tag is never silently
widened.)

## Why a full set algebra

Scopes and expressions compose with four operators — `|` (union), `&`
(intersection), `-` (difference), `~` (complement) — usable identically inside a
`scoped(...)` tag and at a `Model.scope(...)` call site. Two ideas make this
worth the surface area.

First, **exclusion is structural, not a second marker.** Because the root
`Scope` matches everything, `scoped(Scope)` is the wildcard and
`scoped(Scope - Llm)` is "everywhere except the LLM view". There is no
marker-conflict policy to learn, because the exclusion lives inside the
expression. `A - B` and `~A` propagate through inheritance: exclude `Llm` and
you exclude every scope that extends `Llm` too.

Second, **expressions are reusable values.** `SAFE = Scope - Pii` is a name you
can put on a field tag and hand to `.scope()` alike. The projection methods
(`.scope()` / `.redacted()` / `.input()` / `.output()`) each take **one** scope
or expression — compose with the operators (`Model.scope(A | B)`) rather than
passing several arguments. (The `scoped(...)` field marker still unions its
varargs, since tagging a field with several scopes at once reads naturally:
`scoped(A, B)` is `scoped(A | B)`.)

## A second axis: classification

Visibility (`Public < Internal < Storage`) is a lattice. Data *classification*
(`Pii`, `Secret`) is a different question — not "who may see this" but "what
kind of sensitive thing is this" — and a single field often answers both: an
email is `Public` **and** `Pii`.

Prism models classification as `class Classification(Scope)`: a classification
*is* a scope, so it composes in the same algebra (`Internal - Pii`), tags fields
through the same `scoped(...)`, and obeys the same membership rule. 100% of the
engine is reused. The only new machinery is the distinct base, which lets prism
tell the two axes apart by *type* — `issubclass(atom, Classification)` partitions
a field's tags. That partition is what powers
[`redacted()`](../how-to/redact-pii.md) (strip the classification atoms, keep the
visibility view) and [`classified_flow()`](../how-to/trace-data-flow.md).

The axes are distinguishable by type but not *forbidden* from mixing:
`Model.scope(Pii)` stays legal ("give me the PII view" is genuinely useful),
while the governance helpers are the ergonomic, axis-explicit path. And because
`redacted()` defaults to stripping *every* classification the model declares, a
classification added later is auto-redacted — the safe direction.

## A third axis: direction

Read/write *direction* is the same move once more. A field is read-only,
write-only, or read-write — orthogonal to both visibility and classification.
Prism ships it as `class Direction(Scope)` with the two members `In` and `Out`
(a *closed* binary, so prism ships both members, unlike the open classification
taxonomy). Tag the exceptions: a read-only field unions `Out` onto its
visibility scope, a write-only field unions `In`; read-write fields carry no
direction tag.

Here the axis-awareness pays off as a *subtraction* rather than a partition.
[`input()`](../how-to/prevent-mass-assignment.md) is `union(visible) - Out` (the
write view drops read-only fields) and `output()` is `union(visible) - In` (the
read view drops write-only fields) — the same difference operator that powers
`redacted()`, aimed at the direction atoms. A read-only field is therefore
simply *absent* from the input projection, which is mass-assignment protection
by shape: there is no field to over-post. The membership rule does the rest — a
field tagged `Public | Out` still belongs to `Public`, so the *full*
`scope(Public)` keeps it; only the directional `input()` removes it.

The one wrinkle is that `input()` forks the projection's `model_config` to
`extra="forbid"` (a config-distinct class, separately named `{Model}In`), so an
unknown key is rejected rather than silently dropped — the only thing that
closes the over-posting hole when the canonical itself allows extra keys. That
is a deliberate strictness choice on the safety axis, overridable per view.
