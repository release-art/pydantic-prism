# Design memo — round 2 (adoption feedback)

Phase 1 output, 2026-06-10. Covers the four items with real judgment calls
from the SiteCompliance adoption assessment: custom-base composition (1),
dict-keyed refs (3), embedded ref-record projections (4), and
optional-on-projection (5). Items 2, 6, 7 have one reasonable shape each and
go straight to implementation.

Context that constrains everything below: scopes in prism are **classes**,
not strings (decision 5), cardinality is **inferred from the annotation**
(decision 10), and untagged fields belong to **no** scope (decision 2). The
feedback's `.scope("update")` spellings translate to scope classes here.

---

## 1. Custom-base composition

**Today.** `_project` builds every projection on a fresh `(Projection,)`
base ([_model.py:325-340]). A canonical `class Row(CustomBase, ScopedModel)`
loses, on projection: `@model_validator` / `@model_serializer` declared on
`CustomBase`, overridden `model_dump` / `model_validate`, plain methods, and
class identity — `isinstance(projection_instance, CustomBase)` is `False`,
so typed helpers like `Binding[T: CustomBase]` reject projections outright.

### Options

**A. Carry by default.** Projection bases = the canonical's `__bases__`
with the `ScopedModel`-derived entry replaced by `Projection`, order
preserved: `Row(CustomBase, ScopedModel)` → projection bases
`(CustomBase, Projection)`. Pydantic merges decorators and config across
bases natively, so validators/serializers/dump overrides and `isinstance`
identity all come back with zero ceremony, for every existing user, without
a spelling change. The cost is a real hazard: *fields declared on the
carried base* are inherited by every projection and **cannot be removed**
(pydantic subclasses cannot unset inherited fields) — they bypass scope
filtering. And model validators defined on the base run against narrow
projections whose field set they never anticipated (usually fine — a base
written for reuse doesn't know the concrete fields — but not guaranteed).

**B. `bases=` kwarg on `.scope()`.** `Row.scope(Storage, bases=(CustomBase,))`.
Maximum control, including per-projection choices (storage carries the
Azure envelope, public doesn't). But the silently-broken default stays the
default; the kwarg must be repeated at every call site; forgetting it
reintroduces precisely the bug this round exists to fix; and `bases` must
join the cache key and the auto-naming scheme.

**C. Class-level opt-in plus a `.scope()`-time warning.**
`class Row(CustomBase, ScopedModel, carry_bases=True)`; without the flag,
`.scope()` warns when it detects dropped behavior. Declared once, explicit.
But the warning nags every legitimate plain-mixin user, and the default
remains wrong for the case that motivated the feature.

### Recommendation

**A — carry by default**, with `bases=` accepted on `.scope()` as the
per-call escape hatch (default sentinel = "inherit the canonical's chain";
`bases=()` opts out entirely). Round 1's principle was explicit-over-implicit
*unless ergonomics demand the trade*: there is no scenario where dropping a
custom `model_dump` was the desired outcome, so the implicit choice is the
only non-broken one. `bases=` joins the cache key, so distinct base tuples
yield distinct cached classes.

Sub-decision to settle in phase 2 — **base-declared fields**. They will
appear on every projection (inheritance; not removable). Honest rule
candidates: (a) document loudly: "fields declared on carried bases are
infrastructure, present in every projection; scope-governed fields belong on
the ScopedModel side"; (b) additionally raise at `.scope()` time if a
base-declared field carries a `scoped()` tag that the requested expression
does *not* select (a narrowing we cannot honor — fail instead of leak).
I lean (a)+(b): permissive where we can be honest, loud where we cannot.

---

## 3. Dict-keyed-by-id collections as a ref primitive

**Today.** `cardinality()` ([_refs.py:47]) only recognizes
sequences/sets — `dict[UUID, Highlight]` infers `many=False`. The shape the
consumer uses everywhere is not just unsupported, it is quietly wrong.

**Independent of spelling**, the cardinality model must get richer:
`RefInfo` grows `shape: RefShape` with `SCALAR | COLLECTION | KEYED_DICT`
(plus `key_type` for keyed dicts; `optional` stays as-is). `many` survives
as a derived property (`shape is not SCALAR`) so round-1 code keeps working.

### Options

**A. One `ref()` that inspects the annotation.**
`Annotated[dict[UUID, Highlight], ref(Highlight)]` — a `Mapping` origin
flips the shape to `KEYED_DICT`, the key type is recorded, and the key type
is checked against the target id field's annotation lazily, at `__refs__`
resolution (consistent with decision 13: eager structure, lazy resolution).
This is decision 10 applied again: the annotation *is* the storage shape.
Cost: `ref()` no longer always means "this field holds ids" — on a keyed
dict it means "the keys are ids of target; the values are embedded payloads".
One marker, two postures.

**B. A distinct `dict_ref(target, ...)` marker.** Each marker keeps a single
meaning, and the field declaration announces its storage shape without
reading the annotation. But the annotation already says `dict[...]` —
the marker name repeats information that can now *disagree* with the
annotation (`dict_ref` on a `list` field becomes a new error case to define,
detect, and document), and it's a second marker to learn for a shape
difference the type system already expresses.

### Recommendation

**A — one `ref()`**, annotation-driven. The inference principle is already
load-bearing in this library and the type-inference cost is one
`get_origin` check. Notes for phase 2: (i) values need not be the target —
`dict[UUID, ArbitraryPayload]` with `ref(Highlight)` is legal (keys are ids;
the value is opaque payload), which also covers the realistic
`FoundHighlight`-with-back-pointer case; (ii) key-type mismatch
(`dict[int, X]` against a `UUID` id) raises `RefResolutionError` on first
`__refs__` access.

---

## 4. Embedded ref-records as projection-aware ref targets

**Today.** `SnapshotRef = Snapshot.scope(RefScope)` used as
`refs: Annotated[list[SnapshotRef], scoped(...)]` is an opaque nested model:
`__refs__` knows nothing, although `SnapshotRef.__prism_source__` carries
full provenance. (Mechanically the field already survives projection — a
`Projection` class is not a `ScopedModel`, so `_rewrite` leaves it alone as
a fixed-shape carrier. The missing part is purely the ref graph.)

### Options

**A. Auto-register, same kind as FK refs.** Any field whose annotation
(possibly under `list` / `dict[K, ...]` / `Optional`) is a `Projection`
class registers an edge to `__prism_source__` with `kind="ref"`. Zero
ceremony, matches the feedback's lean. But it conflates id-valued FK fields
with embedded-carrier fields in every consumer of `.outgoing`, and an
id-ref and a carrier-ref need different resolution code on the user's side.

**B. Explicit no-arg `ref()`.**
`refs: Annotated[list[SnapshotRef], ref(), scoped(...)]` — target inferred
from provenance, never repeated (DRY), and the relationship is declared, not
detected. But forgetting the marker silently yields not-a-ref — exactly the
silent-degradation class of bug this round is eliminating — and the
feedback's required form was "no explicit `ref()` needed".

**C. Auto-register as a distinct kind.** Like A, but the edge gets
`kind="embedded"` and `RefInfo` grows `scope` (the carrier's
`__prism_scope__`). `.outgoing` keeps meaning id-style FK edges; a new
`.embedded` accessor exposes carrier edges; `targets()` / `walk()` see both.

### Recommendation

**C — auto-register as `kind="embedded"`.** The explicit-over-implicit
principle is satisfied because the declaration *is* explicit: the field's
type names a projection of a specific canonical — nothing is registered
that isn't written in the annotation; auto-detection just refuses to make
the user say it twice. Keeping the kind distinct preserves the invariant
that `kind="ref"` edges hold ids, which both shapes of user code (resolve
by id vs. read embedded record) need to distinguish anyway. Composes with
item 3: `dict[UUID, SnapshotRef]` is `shape=KEYED_DICT, kind="embedded"`,
key checked against `Snapshot`'s id.

Sub-decision for phase 2: do embedded *canonical* `ScopedModel` fields
(today: pure composition with scope propagation, e.g. `Address` in
`Shipment`) also register `embedded` edges, for uniformity? Lean **no**:
a canonical annotation reshapes per outer scope (it is structure, not a
fixed carrier record), and round 1 shipped it as composition — silently
promoting every nested model to a graph edge is churn without a requester.

---

## 5. Optional-on-projection (the Update model)

### Options

**A. Call-site flag — `.scope(Update, optional=True)`.** Maximally flexible,
no new declaration surface. But "what is `RowUpdate`" now depends on the
call site: the same scope expression yields structurally different classes
at different calls, the flag joins the cache key and naming scheme, and two
modules disagreeing on the flag silently get two classes.

**B. Model-level — `optional_scopes: ClassVar = {Update}`.** Declared once
per model. But it must be repeated on every model, and it composes poorly
with scope algebra (is `Update | Public` optional? the model-level set has
no principled answer; it also can't be consulted for expressions built from
scopes the model never listed).

**C. Per-field — `scoped(Public, Update, optional_in={Update})`.** Maximum
control; covers exotic "optional here, required there" fields. Far too
heavy for the dominant case ("the canonical row with every field optional"),
which would repeat `optional_in=` on every field of every table model.

**D. Scope-class property — `class Update(Storage, partial=True)`.**
Optionality is a property *of the scope itself*, declared once, at the same
place the scope graph already lives. Every model projected to `Update` is
partial; `Row.scope(Update)` reads exactly like every other projection; no
cache/name complexity (the scope is the key, as before). Needs one algebra
rule: an expression is partial iff **all** its atoms are partial
(conservative — mixing a partial and a regular scope yields a regular
projection), and the flag inherits down the scope graph like everything
else unless re-declared.

### Recommendation

**D — `partial=True` as a `Scope` subclass keyword.** It is the only option
where the semantics travel with the scope name everywhere it is used, which
is how every other property in this library already works. The keyword is
`partial` (TS `Partial<T>` precedent), not `optional`, to avoid colliding
with `Optional[T]`-the-annotation. Per-field exceptions (option C) can be
layered on later if real demand appears; nothing in D blocks it.

Mechanics (settle the default-values question in phase 2):

- Surviving field `T` → `T | None` (unchanged if already optional), and the
  field gets `default=None` so omitting it validates cleanly.
- **Open:** fields that carry a canonical default — keep it, or force
  `None`? Lean **force `None` for everything**: an update model's contract
  is "absent means don't touch", and a surviving canonical default would be
  silently *written back* on every update built from sparse input. True
  PATCH semantics need absent ≠ default.
- JSON schema: nothing required, fields nullable — falls out of the two
  rules above for free.
- `from_canonical` round-trip is trivially fine (all fields present on the
  canonical side); `from_projection` keeps requiring `**extra` for what the
  projection holds as `None` only if the canonical lacks defaults — same
  rule as today.

---

## Not in this memo (straight to implementation)

- **Item 2** — `from_canonical(instance, *, mode=..., by_alias=True,
  context=..., exclude_none=...)` forwarding to `model_dump`; current
  behavior documented as the explicit default.
- **Item 6** — README truthfulness work; "what `ref()` does/doesn't model",
  full API reference table, prior-art table refresh.
- **Item 7** — error messages list defined scopes; `Model.scopes()`
  classmethod; recursive-model test (`dict[str, Self]` + `tuple[Self, ...]`
  + projection).
