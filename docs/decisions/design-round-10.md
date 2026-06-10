# Design memo — round 10 (diagram export)

Phase 1 output, 2026-06-10. Export prism's structure to graph formats —
"scope inheritance / generated models," Mermaid & DOT required, "anything else?"

No new runtime dependency: prism only emits *text* (the user pipes it to
mermaid-cli / Graphviz / D2 themselves). Everything is built from existing
introspection — the `Scope` hierarchy (`__bases__`, `__prism_partial__`),
`RefGraph.walk()`, and `Model.scopes()` / `.scope()`.

## Architecture

A small backend-agnostic IR — a `Diagram` value object holding nodes
(`id`, `label`, `kind` for styling) and directed edges (`src`, `dst`, `label`) —
with one renderer per format. Every graph type builds the same IR; every format
renders any IR. This is what makes "anything else?" cheap: a new format is one
render function, a new graph is one builder. Renderers handle id-sanitizing and
label-escaping per format.

## Q1. Which graphs?

Three distinct things are worth drawing; the "/" in the request names two of
them, and a third falls out:

- **Scope inheritance** (asked) — nodes = `Scope` classes, edges = `Derived
  --extends--> Base`; partial scopes styled (`«partial»`). Given scopes, pull in
  their ancestors (via `__bases__`) so the graph is connected.
- **Model relationship graph** — nodes = models reachable from one model's
  `__refs__.walk()`, edges labeled by field + kind (`ref`/`backref`/`embedded`)
  and cardinality. This is the cross-model "what references what."
- **Projection landscape** — nodes = a canonical model and the projections it
  generates (one per scope in `.scopes()`), edges = `Canonical --Public-->
  CanonicalPublic`. This is the most literal reading of "generated models."

**Recommend all three.** They answer different questions (the scope algebra; the
data graph; the projection fan-out) and share the IR, so the marginal cost of
each builder is small. "Generated models" most literally means the projection
landscape, but the relationship graph is the one people usually mean by "model
diagram" — hence both, plus scopes.

## Q2. Formats beyond Mermaid + DOT?

Mermaid (`graph TD` flowchart — uniform across all three graph types, labeled
edges, node classes) and DOT (`digraph`) are the musts.

**Recommend also: D2 and `as_dict()`.** D2 (terrastruct) is the modern, clean
diagram language with growing tooling — a natural third. `as_dict()` exposes the
IR itself (JSON-serializable), so anyone can feed a tool prism doesn't target,
and it makes the renderers trivially testable. PlantUML / GraphML are more niche;
the IR makes them a later one-function add if demand appears — I'd leave them
out now rather than carry renderers nobody asked for.

## Q3. API surface

**Recommend:** every builder returns a `Diagram`; `Diagram` carries
`.to_mermaid()`, `.to_dot()`, `.to_d2()`, `.as_dict()`.

- `RefGraph.diagram()` — method on the existing object (discoverable):
  `Order.__refs__.diagram().to_mermaid()`.
- `scope_diagram(*scopes)` — top-level; scopes (or a model, whose `.scopes()` is
  used) → the hierarchy. With no args, recursively discovers `Scope` subclasses.
- `projection_diagram(Model)` — top-level; canonical → its projections.

`Diagram` is exported so the return type is nameable; the three formats are
methods (not free functions) so they're discoverable from the value.

## Q4. Node detail

**Recommend names-only nodes with labeled edges** for v1 — readable and format-
portable. An opt-in `fields=True` (list surviving fields in projection nodes /
the id field on ref edges) can layer on later via node sublabels; defaulting to
it makes large graphs unreadable. Confirm.

## Phase-2 questions

1. Graphs: all three (scope / relationship / projection) — rec — or a subset.
2. Formats: Mermaid + DOT + **D2 + `as_dict()`** (rec), or just the two musts,
   or add PlantUML/GraphML.
3. API: `Diagram` IR + `.to_mermaid()/.to_dot()/.to_d2()/.as_dict()`, builders
   `RefGraph.diagram()` / `scope_diagram()` / `projection_diagram()` (rec).
4. Detail: names-only nodes for v1 (rec) vs include fields.
