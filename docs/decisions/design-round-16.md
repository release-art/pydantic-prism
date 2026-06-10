# Design memo — round 16 (classification axis + data-flow governance)

Phase 1 output, 2026-06-10. Promotes the `examples/pii_dataflow/main.py`
prototype (and [`docs/use-case-pii-governance.md`](use-case-pii-governance.md))
into first-class API. The prototype proved the wedge: a ~40-line governance
layer — classification inventory, redacted views, PII data-flow over the
`RefGraph` — sits on the **unmodified** public API. This round decides which
parts become library surface, and resolves the one architectural question the
note flagged: *is classification a distinct axis, or just another `Scope`?*

## The bet (restated, for the decision record)

Two orthogonal axes on one field: **visibility** (`Public < Internal < Storage`,
a lattice) and **classification** (`Pii`, `Secret`, set-like tags). Today the
prototype models both as plain `Scope` subclasses and unions them onto the field
(`scoped(Internal), scoped(Pii)`). That works for `expr.matches(Pii)` and for
redaction-as-set-difference (`Internal - Pii`), but nothing stops a careless
`Model.scope(Pii)` being treated as a *visibility request*, and prism cannot tell
the two axes apart to auto-derive a redacted view or a report.

## Open questions

### 1. Classification: distinct type, or scope convention? *(the core question)*

- **(A, recommended) `Classification(Scope)` base** — classifications subclass a
  new `Classification` marker that itself subclasses `Scope`. The entire
  expression engine, `scoped(...)`, `matches`/`selects`, and `Internal - Pii`
  algebra keep working **unchanged** (a `Classification` *is* a `Scope`). The
  distinct base is what lets prism partition a field's atoms into
  visibility-vs-classification (`issubclass(atom, Classification)`), auto-derive
  "strip every classification" redaction, and drive reports.
- (B) Keep classifications as plain `Scope`s; add only helper functions. Zero new
  machinery, but the axes stay blurred and `redacted()`/reports must be handed an
  explicit classification list every call.
- (C) A wholly separate `Classification` type *not* backed by `Scope`, with its
  own parallel expression engine. Honest separation, but doubles the algebra and
  breaks the elegant `Internal - Pii` difference.

  *Tradeoff:* (A) buys axis-awareness for one tiny base class while reusing 100%
  of the engine — the note's "still backed by the same expression engine" wish.
  Cost: `Model.scope(Pii)` stays *legal* (a classification is a valid scope
  expression — and "give me the PII view" is genuinely useful), so the axes are
  distinguishable by *type* but not *forbidden* from mixing. I think that is
  correct: enforce nothing, but make the clean path ergonomic (Q2–Q3).

### 2. Redaction ergonomics — `Model.redacted(...)`

- **(A, recommended) `Model.redacted(*visible, strip=None, name=None)`** →
  `Model.scope(union(visible) - union(strip))`, where `strip` **defaults to every
  classification declared on the model**. So `User.redacted(Internal)` strips all
  PII+Secret with no list to maintain; `User.redacted(Internal, strip=Secret)`
  keeps PII but drops secrets. Refs survive (it is just a projection).
- (B) Require `strip=` explicitly. (C) Ship nothing; keep raw `scope(A - B - C)`.

  *Tradeoff:* (A)'s defaulting is the whole ergonomic win and is only possible
  under Q1=A (prism must know which atoms are classifications). Tiny risk: the
  default silently widens when a new classification is added to the model —
  which is exactly the safe direction (new PII auto-redacted).

### 3. Inventory + data-flow report — the compliance artifact

Three read-only introspection methods on `ScopedModel`, mirroring `scopes()`:

- `Model.classifications()` → `frozenset[type[Classification]]` (atoms used).
- `Model.classified_fields()` → `dict[str, frozenset[type[Classification]]]`
  (per-model inventory; the prototype's `pii_inventory`).
- **`Model.classified_flow()`** → a structured `FlowReport` spanning the ref
  graph (the prototype's `dataflow_report`): every model classified data reaches
  from this entry point, via which edges.

  *Return type:* **(recommended)** a small frozen `FlowReport` dataclass with
  `.as_dict()` (JSON) and `.to_mermaid()`, mirroring the `Diagram` IR so it slots
  into the CLI and README tooling. Alternative: return bare dicts (less surface,
  but no rendering, and inconsistent with `Diagram`). The note explicitly asks
  for "JSON/Mermaid for compliance review," so the IR earns its keep.

### 4. CLI `prism flow`

- **(recommended)** Add a `flow` subcommand beside `diagram`:
  `prism flow module:Model --format json|mermaid [--output FILE]`, reusing the
  existing resolve/render plumbing in `_cli.py`. *Tradeoff:* ~20 lines; the
  alternative (fold into `diagram`) conflates structure with governance.

### 5. Does prism ship concrete `Pii`/`Secret` classes?

- **(recommended) Base-only.** Ship `Classification`; users declare
  `class Pii(Classification): ...`. Shipping a concrete taxonomy invites "is this
  *the* canonical PII set?" debate and locks naming. *Tradeoff:* marginally less
  batteries-included; could add `Pii`/`Secret` convenience exports later without
  commitment. Lean base-only for 1.0.

## Surface summary (if all recommendations land)

| new export | kind | replaces prototype shim |
|---|---|---|
| `Classification` | marker base (`Scope` subclass) | `class Pii(Scope)` |
| `Model.classifications()` | classmethod | — |
| `Model.classified_fields()` | classmethod | `pii_inventory` |
| `Model.classified_flow()` → `FlowReport` | classmethod + IR | `dataflow_report` |
| `Model.redacted(*visible, strip=)` | classmethod | `scope(Internal - Pii - Secret)` |
| `prism flow` | CLI subcommand | the demo's print loop |

All additive — no behavior change to existing projections. Quality bar unchanged
(ruff, ruff-format, pyright-strict on `src/`, pytest at 100% coverage), plus a
new `examples/pii_dataflow` README and decision records continuing from #67.
