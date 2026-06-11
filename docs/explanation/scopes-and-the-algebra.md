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
can put on a field tag and hand to `.scope()` alike. Varargs are just union
sugar: `scoped(A, B)` is `scoped(A | B)`, and `Model.scope(A, B)` is
`Model.scope(A | B)`.

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
