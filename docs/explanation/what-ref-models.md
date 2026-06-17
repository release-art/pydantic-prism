# What `ref()` models — and what it doesn't

`ref()` and `backref()` declare that a field's *values* (or, for keyed dicts,
its *keys*) are identifiers of another model, and record that fact for
introspection through `__prism__.refs`. That sentence is the whole feature. This page
explains the deliberate line it draws.

## Introspection only

`__prism__.refs` is a `RefGraph`: a mapping from field name to a `RefInfo`, plus
`.outgoing` / `.incoming` / `.embedded` accessors, `.targets()`, and a
cycle-safe `.walk()` BFS over reachable models. That is the ceiling. Prism
**never fetches anything.** There is no session, no lazy loading, no query
builder. `info.target` is a *class*; turning ids into instances is your code.
Backref fields are real, validated data fields with an empty default that *you*
populate from your own resolvers — prism never resolves them.

This is the same discipline that runs through the whole library: **storage is
your problem.** Against an ORM, refs run over the foreign keys as pure
introspection; a SQLAlchemy `Relationship()` is not a pydantic field, so prism
never even sees it. The pitch is "stop hand-writing the DTO zoo around your ORM
model", not "replace your ORM".

## No registry, no import-order magic

Back-references are *explicitly declared* — `backref(Order, via="customer_id")`
— rather than auto-reversed from forward refs. An auto-reversing global registry
would reintroduce exactly the import-order coupling prism is trying to avoid. So
there is no registry: the reverse edge names its forward counterpart, and that
declaration is checked at resolution time.

## What it *does* enforce — consistency, not integrity

Prism validates *declarations*, never *data*. A keyed-dict `ref()`'s key type is
checked against the target id field's annotation, and a `backref(via=...)` is
checked against the matching forward `ref` on its target. These checks run
**lazily**, on first `__prism__.refs` access (eager structure, lazy resolution), and
raise `RefResolutionError` — but they never touch a single instance. (A scalar
or collection `ref()` records its target without comparing field types, and a
`UUID` that points nowhere validates fine.) Referential integrity is a
database's job, not a schema library's.

Cardinality follows the same "report, don't act" stance: it is *inferred from
the annotation* and merely recorded. `UUID` is `SCALAR`, `list[UUID]` is
`COLLECTION`, `dict[UUID, T]` is `KEYED_DICT` — the annotation *is* the
cardinality. Prism tells you the shape; what you do with it is up to you.

## Deliberately not modeled

- **Resolution / lazy loading / query building** — your code (see
  [`examples/graph`](../../examples/graph) for a minimal resolver over
  `RefInfo`).
- **Referential integrity on data** — declaration consistency only.
- **Conditional / polymorphic refs** (`ref(A) | ref(B)`) — one target per field.

A string target resolves lazily: a bare `ref("Customer")` against the owning
model's module, and a fully-qualified `ref("pkg.mod:Customer")` /
`ref("pkg.mod.Customer")` against the named module (via `importlib`) for a target
that lives elsewhere — the same `"module:Name"` grammar the `pydantic-prism gen` spec uses.

Because the ref graph is pure metadata that *survives projection*, higher-level
features compose on top of it without prism ever doing I/O — most notably the
[data-flow report](../how-to/trace-data-flow.md), which walks the same forward
edges to find where classified data can travel.
