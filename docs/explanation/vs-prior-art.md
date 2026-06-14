# Compared to prior art

Honest overlap: the *projection* half of prism has real precedent. The
combination of projection with an introspectable relationship graph does not.
This page says where prism stands on the shoulders of existing work and where it
is genuinely new.

## The honest overlap

Deriving a real, cached `BaseModel` subclass from `Annotated` markers is
well-trodden ground:

- **[pydantic-extension](https://github.com/humblemat810/pydantic-extension)**
  is the closest existing thing: per-field `Annotated` markers, subscript syntax
  (`User["dto"]`) that builds a cached real `BaseModel` subclass via
  `create_model`, with union composition and nested-model rewriting. Prism keeps
  its good ideas (cached real slices, markers in `Annotated`, union semantics)
  and drops its magic — it sniffs the call stack to detect framework frames and
  silently switch what `model_dump`/`model_validate` return, which prism refuses
  to do.
- **[pydantic-views](https://pydantic-views.readthedocs.io)** has genuinely good
  mechanics: it strips markers from derived metadata, keeps untagged fields in
  every view, builds all-optional Update models without polluting annotations
  with `| None`, and handles nested cycles with `ForwardRef` + `model_rebuild`.
  But its scope vocabulary is a fixed six-value CRUD enum, and views are built by
  imperative builder objects rather than asked of the model.
- Pydantic's own community has asked for Pick/Omit/Partial derivation since 2021
  (discussion #2547, issue #5293). Core **closed #5293 as won't-implement** —
  too much maintenance surface, and dynamically derived models are opaque to
  static checkers anyway. Prism fills an explicitly-vacated gap, builds on the
  public API only, and is upfront about the static-typing cost (and then
  addresses it with [generated stubs](../how-to/generate-editor-stubs.md)).

The naming lesson comes from outside Python: `@effect/sql`'s `Model.Class` is
the one true prior art for "tag fields once by role, derive variants by named
use case". Its variant set is fixed by the library; prism's key difference is
that *you* name the scopes.

## What is genuinely new

Two things, and they are the differentiators:

1. **User-defined scopes with a real algebra.** Every library surveyed leaves
   the scope vocabulary fixed — a CRUD enum, class-named modes, a fixed variant
   set. Prism lets you declare your own `Scope` classes and compose them with
   `| & - ~`, in tags and at the call site alike.
2. **A relationship graph on the fields, introspectable, that survives
   projection.** `ref()` / `backref()` / `__prism__.refs` — nothing surveyed does
   this. It is what turns "many faces of a model" into "a coherent model graph
   you can narrow", and what the [data-flow report](what-ref-models.md) is built
   on.

## At a glance

| | pydantic-prism | [pydantic-extension](https://github.com/humblemat810/pydantic-extension) | [pydantic-views](https://pydantic-views.readthedocs.io) |
|---|---|---|---|
| scope vocabulary | user-defined `Scope` classes, inheritance graph | 4 built-in modes + runtime `register_mode()` | fixed 6-value CRUD enum |
| composition | full set algebra (`\| & - ~`) | union + exclusion grammar in subscripts | one builder per view |
| derived models | real `BaseModel`, cached, deterministic names | real `BaseModel`, cached | real `BaseModel` |
| relationships | `ref` / `backref` markers, `RefGraph`, survive projection | — | — |
| dict-keyed refs (`dict[UUID, T]`, key = foreign id) | first-class (`RefShape.KEYED_DICT`) | — | — |
| embedded "ref record" projections | auto-registered `embedded` edges with provenance | — | — |
| all-optional Update views | any scope: `partial=True` | — | fixed `Update`/`UpdateOptional` views |
| custom pydantic bases on derived models | `projection_bases=` / `bases=`, `isinstance`-true | — | — |
| static typing of derived models | `pydantic-prism gen` stubs (pyright/Pylance/mypy) + `pydantic-prism check` CI drift gate | — | — |
| per-projection schema metadata | per-scope field & model `description` / `examples` / `json_schema_extra` | — | — |
| diagram export | scope / projection / relationship graphs → Mermaid, DOT, D2, JSON | — | — |
| classification & data-flow | `Classification` axis, `redacted()`, `data_flow()` | — | — |
| validators on derived models | field validators carried; model validators via `@scoped_validator` or carried bases [^ordering] | lost | lost |
| implicit behavior | none | call-stack sniffing can switch modes | registry monkey-patched onto your class |
| Python | 3.12+ | 3.9+ (claimed) | 3.13+ |

[^ordering]: pydantic runs `mode="before"` validators child-first, so a
    `@scoped_validator(mode="before")` runs before a `before`-hook inherited
    from a base. prism warns at class definition and ships
    `run_inherited_before` to invoke the inherited hooks explicitly — see
    [before-validator ordering](../how-to/carry-a-custom-base.md#before-validator-ordering-with-scoped_validator).
