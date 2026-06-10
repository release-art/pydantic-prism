# Design memo — round 11 (preserve field metadata in derived objects)

Phase 1 output, 2026-06-10. `Diagram.Node.fields` is `tuple[str, ...]` — bare
names, dropping type and description. The note "same stands for most other
prism-derived objects" asks for a broader look. Audit first, then fix.

## Audit — where prism keeps vs. drops field metadata

| derived object | field metadata | verdict |
|---|---|---|
| **Projection classes** (`.scope()`) | `_project` deep-copies `FieldInfo`, so `description`, annotation, examples, constraints all survive; round 7 even *adds* per-scope descriptions | **preserved** — not lossy |
| `RefInfo` / `RefGraph` | structured (round 9 split); carries target/shape/kind/key_type | preserved |
| **`Diagram.Node.fields`** | flattened to `tuple[str, ...]` — type and description gone | **lossy (this round)** |
| **Codegen stubs** (`prism gen`) | shim renders `name: Type` only; field `description`s dropped | lossy (separate, bigger — flag) |

So the live model objects already preserve metadata (confirmed: a projected
field keeps its `Field(description=...)` / attribute-docstring). The flattening
happens at the two *rendering/serialization* boundaries — diagrams (now) and
generated stubs (a larger change to a generated artifact; recommend a later
round, noted below).

## Proposal — structured field + node metadata in the Diagram IR

Replace `Node.fields: tuple[str, ...]` with `tuple[NodeField, ...]`:

```python
@dataclass(frozen=True)
class NodeField:
    name: str
    type: str | None = None          # display label, e.g. "UUID", "str | None"
    description: str | None = None    # FieldInfo.description (Field(...) or docstring)
```

and add node-level metadata, since "docstrings" live at the class/scope level too:

```python
Node.description: str | None         # model/projection __doc__, or a scope's
                                     # round-7 description
```

Populate from the live objects: `NodeField` from each `model_fields[name]`
(`.description`, a label off `.annotation`); `Node.description` from the class
docstring (projections carry one) or a scope's `__prism_model_schema__`
description. **`as_dict()` carries all of it** — that is the core of "preserve
meaningful metadata": the IR is lossless, so any downstream tool gets the
descriptions even if a given visual format can't show them.

## Q1. `NodeField` content

Options: `name` + `type` + `description` (recommended) / `name` + `description`
only.
**Recommend name + type + description.** Type is one cheap label off the
annotation and is the natural class-diagram row (`name: type`); description is
the "docstring" the feedback wants. (Examples/constraints stay out — they bloat a
node; `as_dict` consumers can read the live model for more.)

## Q2. Node-level description

Options: add `Node.description` (recommended) / fields only.
**Recommend adding it.** Docstrings are class-level; projection classes already
have a `__doc__`, models may, and scopes can carry a round-7 `description`.
Carrying it on the node (and in `as_dict`) is the same principle one level up and
nearly free.

## Q3. How much do renderers *show*?

Options: visual shows `name: type`, descriptions live in `as_dict` only
(recommended) / also render descriptions visually (tooltips where the format
supports them).
**Recommend `name: type` in the visual, descriptions in the IR.** D2 class rows
are literally `name: type`; Mermaid/DOT append the type. There is no clean,
cross-format way to show per-field descriptions inline without noise — and the
feedback's ask is to *preserve* metadata (which `as_dict` does), not necessarily
to paint it into every diagram. DOT node `tooltip=` for `Node.description` is a
cheap extra we can include.

## Q4. Scope — diagrams now, codegen later?

Options: Diagram metadata this round + report on codegen (recommended) / also
enrich codegen stubs with field descriptions now.
**Recommend Diagram now, codegen as a flagged follow-up.** The stub generator
would need to emit `field: T = Field(description=...)` (or docstrings) and keep
that lossless through drift signatures — a real change to a generated artifact,
worth its own round. This round closes the diagram gap and records the codegen
one.

## Phase-2 questions

1. `NodeField` = name + type + description (rec) vs name + description.
2. Add `Node.description` (rec) vs fields only.
3. Visual = `name: type`, descriptions in `as_dict` (rec) vs render descriptions.
4. Diagram now + flag codegen (rec) vs also do codegen this round.
