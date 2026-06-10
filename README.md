# pydantic-prism

![Tests](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/tests.svg)
![Coverage](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/coverage.svg)
![Skipped](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/skipped.svg)
![XFailed](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/xfailed.svg)
![Warnings](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/warnings.svg)
![Duration](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/duration.svg)
![Last run](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/last-run.svg)

One canonical pydantic model, many scoped projections — with relationships
that survive them.

## The problem

One logical entity usually needs several shapes: the API response, the
storage row, the LLM tool input, the audit log. Today you either hand-write
parallel pydantic classes that drift apart, or build them with `create_model`
boilerplate that loses constraints and confuses every tool downstream.
And when models reference each other by id, those parallel classes have no
idea the references exist.

pydantic-prism solves both, together:

1. **Scoped projections** — tag fields on *one* canonical model with scopes
   via `Annotated` metadata; derive real `pydantic.BaseModel` subclasses per
   scope, with working validation, serialization, JSON schema, and FastAPI
   integration.
2. **A storage-agnostic relationship graph** — declare FK-style references
   in the same `Annotated` metadata; introspect them via `__refs__`; the
   graph survives projection. No ORM, no storage backend — storage stays
   your problem.

All prism metadata lives in `Annotated[...]`. Field defaults stay reserved
for actual default values, and marker order inside one `Annotated` is
insignificant.

## 30 seconds

```python
from typing import Annotated
from uuid import UUID

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...
class Internal(Public): ...   # Internal sees everything Public sees
class Storage(Internal): ...  # Storage sees everything Internal sees


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    password_hash: Annotated[str, scoped(Storage)]
    display_name: Annotated[str, scoped(Public)]


UserPublic = User.scope(Public)      # fields: id, display_name
UserInternal = User.scope(Internal)  # fields: id, email, display_name
UserStorage = User.scope(Storage)    # all four fields
```

`UserPublic` is a real, cached `BaseModel` subclass named `"UserPublic"` —
`User.scope(Public) is User.scope(Public)`, so FastAPI response models and
OpenAPI schemas stay stable.

## Scopes are classes

Scopes are declared as subclasses of `Scope`; **inheritance forms the scope
graph**. A subclass is a *broader* scope: `class Internal(Public)` means a
field tagged `scoped(Public)` also appears in `Internal` projections. The
membership rule is one line: a field tagged `T` is in projection `S` iff
`issubclass(S, T)`.

Because every scope subclasses the root, `scoped(Scope)` is the wildcard —
the field appears in every scope. Untagged fields belong to **no** scope:
they exist only on the canonical model and can never leak into a projection
by omission.

Scopes compose with set operators, both in tags and at the call site:

```python
class Llm(Scope): ...

class Document(ScopedModel):
    body: Annotated[str, scoped(Scope)]            # wildcard: every scope
    owner_email: Annotated[str, scoped(Scope - Llm)]  # everywhere except Llm
    embedding: Annotated[list[float], scoped(Internal & Llm)]  # only scopes that are both
    note: str                                      # untagged: no scope, canonical only


Document.scope(Llm)                  # body
Document.scope(Public | Internal)   # union; same as Document.scope(Public, Internal)
Document.scope(~Llm)                # every field NOT visible to Llm
```

| operator | meaning |
|---|---|
| `A \| B` | union — in either |
| `A & B`  | intersection — in both |
| `A - B`  | difference — in A and not in B |
| `~A`     | complement — not in A |

`A - B` and `~A` propagate through scope inheritance: a field tagged
`scoped(Scope - Llm)` is excluded from `Llm` *and every scope that extends
`Llm`*.

## Relationships

```python
from pydantic_prism import backref, ref


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    order_ids: Annotated[list[UUID], backref("Order", via="customer_id"), scoped(Internal)]


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
    total: Annotated[str, scoped(Internal)]
```

- `ref(Customer)` declares a forward, FK-style reference. String targets
  (`ref("Customer")`) are allowed for cycles and resolve lazily against the
  owning model's module (module-level models only — for models defined inside
  functions, pass the class object).
- `backref(Order, via="customer_id")` declares the reverse edge explicitly —
  no global registry, no import-order magic. The marked field is a real,
  validated field (an empty default is implied) and `via=` is checked
  against the target's forward `ref` at resolution time.
- Shape is inferred from the annotation: `UUID` → scalar, `list[UUID]` →
  collection, `dict[UUID, ...]` → keyed dict (below), `UUID | None` →
  optional. `RefInfo.shape` is a `RefShape` (`SCALAR | COLLECTION |
  KEYED_DICT`); `RefInfo.many` remains as a derived convenience.

Introspect via `__refs__`, a `Mapping[str, RefInfo]`:

```python
info = Order.__refs__["customer_id"]
# info.target is Customer, info.target_field == "id"
# info.shape is RefShape.SCALAR, info.optional is False, info.kind == "ref"

Order.__refs__.outgoing          # forward id-valued edges only
Customer.__refs__.incoming       # declared backrefs only
Order.__refs__.embedded          # embedded-model edges only (see below)
Order.__refs__.targets()         # {Customer}
list(Order.__refs__.walk())      # BFS over reachable forward + embedded edges
```

Refs survive projection — this is the point:

```python
OrderPublic = Order.scope(Public)
OrderPublic.__refs__["customer_id"].target is Customer  # True
```

### Dict-keyed refs

When the relationship primitive is a dict whose **key is the foreign id**
and whose value is an embedded record, the same `ref()` marker applies —
the annotation is the shape:

```python
class Page(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    highlights: Annotated[dict[UUID, Highlight], ref(Highlight), scoped(Public)]


info = Page.__refs__["highlights"]
# info.shape is RefShape.KEYED_DICT, info.key_type is UUID, info.target is Highlight
```

The dict key type is checked against the target's id field type lazily, on
first `__refs__` access (`RefResolutionError` on mismatch). The value type
is **not** required to be the target — `dict[UUID, ScorePayload]` with
`ref(Highlight)` is legal: keys are `Highlight` ids, the value is opaque
payload.

### Embedded models and carrier records

A field whose type *is* a model — a nested canonical `ScopedModel`, or a
projection used as a hand-rolled "ref record" (`{id, timestamp}`-style
carriers) — registers an `embedded` edge automatically. No marker needed:
the annotation already names the model.

```python
class CarrierScope(Scope): ...

SnapshotRef = Snapshot.scope(CarrierScope)     # e.g. id + taken_at only


class Document(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    history: Annotated[list[SnapshotRef], scoped(Public)] = []
    by_id: Annotated[dict[UUID, SnapshotRef], scoped(Public)] = {}


info = Document.__refs__["history"]
# info.kind == "embedded", info.target is Snapshot (the canonical!),
# info.scope == SnapshotRef.__prism_scope__, info.shape is RefShape.COLLECTION
```

- `info.target` always resolves to the **canonical** model — the ref graph
  connects canonicals; the carrier's scope is recorded in `info.scope`.
- A nested canonical (`destination: Address | None`) registers the same way
  with `scope=None`, meaning "reshapes with the outer projection". A
  projection-typed field is a *fixed* carrier: it does not reshape.
- Embedded edges appear in `.embedded`, `.targets()`, and `.walk()` — but
  not in `.outgoing`, which keeps meaning id-valued FK edges.
- Keys of embedded keyed dicts are recorded (`key_type`) but never
  validated against the target id — composition may be keyed by anything
  (`dict[str, Self]` is structure, not identity).
- An annotation mixing several distinct models (`A | B`) registers nothing.

## Nested models

If a field's type is itself a `ScopedModel`, projecting the outer model
propagates the scope into it — through `Optional`, unions, `list`, `set`,
`tuple` and `dict` annotations, with cycles handled:

```python
class Address(ScopedModel):
    city: Annotated[str, scoped(Public)]
    plus_code: Annotated[str, scoped(Internal)] = ""


class Shipment(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    destination: Annotated[Address | None, scoped(Public)] = None


ShipmentPublic = Shipment.scope(Public)
# ShipmentPublic.destination is typed Optional[AddressPublic]
```

## Round trips

```python
user = UserStorage(
    id="00000000-0000-0000-0000-000000000001",
    email="ada@example.com",
    password_hash="…",
    display_name="Ada",
)

pub = UserPublic.from_canonical(user)        # narrow: drop non-Public fields
back = User.from_projection(                 # widen: supply what's missing
    pub, email="ada@example.com", password_hash="…"
)
```

`from_canonical` lives on every projection class; `from_projection` lives on
the canonical model. Both are thin wrappers over `model_validate` — there is
no hidden state.

`from_canonical` forwards `mode`, `by_alias` (default `True`, so alias
generators round-trip), `context`, `exclude_none`, `exclude_unset` and
`exclude_defaults` to the instance's own `model_dump`; `context` is also
passed to `model_validate`. By default the dump is recursively *narrowed*
to the projection's fields (safe under `extra="forbid"`) — unless the
instance's class **overrides** `model_dump`, in which case the dump is
passed through verbatim (prism cannot understand a custom wire shape; your
carried base's validators can). `narrow=` overrides the auto-detection.

## Custom pydantic bases

If your canonical model inherits a custom base — an Azure Table row class
with an overridden `model_dump` and a `@model_validator(mode="before")`,
say — projections do **not** inherit it by default (they are built on a
fresh `Projection` base). Declare which bases projections carry:

```python
class Row(AzureTableBase, ScopedModel, projection_bases=(AzureTableBase,)):
    id: Annotated[UUID, scoped(Public)]
    ...

RowPublic = Row.scope(Public)        # isinstance(RowPublic(...), AzureTableBase)
```

- `projection_bases=` (class keyword) sets the default for every `.scope()`
  call and is inherited by subclasses; `Model.scope(..., bases=(...,))`
  overrides per call, `bases=()` opts out. `bases` participates in the
  cache key — same expression with different bases is a different class
  (pass `name=` to disambiguate the auto-generated name).
- Carried bases restore custom `model_dump`/`model_validate`, base-declared
  model validators/serializers, plain methods, and `isinstance` identity —
  so typed helpers like `Binding[T: AzureTableBase]` accept projections.
- Calling `.scope()` on a model whose base defines such behavior *without*
  any declaration warns once per model. Declare `projection_bases=()` to
  silence it.
- **Fields declared on a carried base are inherited by every projection**
  — pydantic cannot remove inherited fields, so they bypass scope
  filtering. Treat them as infrastructure fields. If a base-declared field
  carries a `scoped()` tag the expression does not select, `.scope()`
  raises `ProjectionBaseError` instead of leaking it.

## Partial scopes — the Update model

Declaring a scope with `partial=True` makes every projection to it
all-optional, with `None` defaults — the classic PATCH/Update shape:

```python
class Update(Storage, partial=True): ...


RowUpdate = CanonicalRow.scope(Update)
RowUpdate()                            # valid: every field defaults to None
RowUpdate(name="new").model_dump(exclude_none=True)   # {"name": "new"}
```

- Every surviving field becomes `T | None` with `default=None`. Canonical
  defaults are **dropped**: an update model's contract is "absent means
  don't touch", and a surviving default would be silently written back.
- JSON schema reflects it: no `required`, fields nullable.
- The flag inherits down the scope graph; an expression is partial iff
  **all** its atoms are partial (mixing `Update | Public` yields a regular
  projection).
- Scope propagation applies: nested models inside a partial projection are
  partial too.

## Validators

`@field_validator`s carry over to projections for the fields that survive
(re-targeted to the surviving subset). `@model_validator`s declared on the
canonical model's own body do **not** — they assume the full canonical
field set. Model validators declared on a *carried base* (see "Custom
pydantic bases") **are** inherited by the projection, through the base
itself. Validators and constraints declared in `Annotated` metadata
(`Field(gt=0)`, `AfterValidator`, …) survive automatically, because
annotations are copied.

Caveat: a carried field validator that reads `info.data` of a dropped field
will fail at validation time.

## Errors

| situation | error | when |
|---|---|---|
| marker used as a field default | `TypeError` | class definition |
| marker nested below the field's top-level `Annotated` | `TypeError` | class definition |
| `ref()` target neither ScopedModel nor str | `TypeError` | marker construction |
| two `ref`/`backref` markers on one field | `TypeError` | class definition |
| projection selects zero fields (message lists the scopes the model defines) | `EmptyProjectionError` | `.scope()` call |
| one projection name for two different expressions (or bases) | `ProjectionNameError` | `.scope()` call |
| `bases=`/`projection_bases=` entry invalid (not a BaseModel, a ScopedModel, or not an ancestor) | `TypeError` | `.scope()` call / class definition |
| carried-base field tagged with a scope the expression does not select | `ProjectionBaseError` | `.scope()` call |
| string target doesn't resolve (or model is function-local) | `RefResolutionError` | `__refs__` access |
| `backref(via=...)` doesn't match a forward ref | `RefResolutionError` | `__refs__` access |
| keyed-dict `ref()` key type doesn't match the target id type | `RefResolutionError` | `__refs__` access |

`EmptyProjectionError`, `ProjectionNameError`, `ProjectionBaseError` and
`RefResolutionError` subclass `PrismError` (and `ValueError`). Models whose annotations were
forward references at definition time are handled: `.scope()` resolves them
(or raises pydantic's clear error), and an explicit `model_rebuild()`
refreshes marker collection too.

## FastAPI

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/users/{user_id}", response_model=User.scope(Public))
def get_user_public(user_id: UUID): ...

@app.get("/admin/users/{user_id}", response_model=User.scope(Internal))
def get_user_internal(user_id: UUID): ...
```

Both routes serve the same canonical object; each response is shaped and
documented by its scope. See [examples/fastapi_app](examples/fastapi_app)
and [examples/graph](examples/graph) for runnable versions.

## What `ref()` does — and does not — model

`ref()` declares that a field's *values* (or, for keyed dicts, *keys*) are
identifiers of another model, and records that fact for introspection.
Nothing more. Concretely:

Modeled (this release):

- `customer_id: Annotated[UUID, ref(Customer)]` — scalar FK.
- `product_ids: Annotated[list[UUID], ref(Product)]` — id collection.
- `highlights: Annotated[dict[UUID, Highlight], ref(Highlight)]` — keyed
  dict; *new in this release* (in v0.1 this inferred `many=False`, quietly
  wrong).
- `history: list[SnapshotRef]` where `SnapshotRef = Snapshot.scope(...)` —
  embedded carrier records; *new in this release*, auto-registered as
  `kind="embedded"` with no marker (v0.1 treated these as opaque nested
  models).
- `order_ids: Annotated[list[UUID], backref(Order, via="customer_id")]` —
  declared reverse edge.

Still rejected / not modeled (deliberately):

- **Resolution.** `__refs__` never fetches anything; there is no session,
  no lazy loading, no query builder. `info.target` is a class, and turning
  ids into instances is your code (see `examples/graph`).
- **Referential integrity.** Prism checks declaration consistency
  (`via=` line-up, keyed-dict key types), never data: a `UUID` that points
  nowhere validates fine.
- **Cross-module string resolution.** `ref("Customer")` resolves in the
  owning model's module only; pass the class object otherwise.
- **Conditional/polymorphic refs** (`ref(A) | ref(B)` style) — one target
  per field.

## API reference

Everything prism adds, with exact spellings. Markers and functions:

| name | kind | summary |
|---|---|---|
| `Scope` | class | Subclass to declare a scope; subclass a scope to broaden it. Root = wildcard. Never instantiated. `class Update(Storage, partial=True)` declares a partial scope. |
| `ScopeExpr` | class | Scope expression; built with `\|`, `&`, `-`, `~`. Methods: `.matches(scope)`, `.selects(tag)`, `.atoms()`, `.is_partial()`. |
| `ScopedModel` | class | Base for canonical models. Class keyword: `projection_bases=(...)`. |
| `Projection` | class | Base of every derived projection class. |
| `scoped(*scopes)` | marker | Tags a field with scopes / a scope expression. Varargs union. |
| `ref(target, *, field="id")` | marker | Forward FK-style reference. `target`: ScopedModel subclass or string. Keyed-dict shape inferred from a `dict[...]` annotation. |
| `backref(target, *, via, field="id")` | marker | Declared reverse reference; `via` names the forward-ref field on `target`. |
| `RefShape` | StrEnum | `SCALAR`, `COLLECTION`, `KEYED_DICT` — also comparable to their lowercase strings. |

Methods and attributes on canonical models:

| name | kind | summary |
|---|---|---|
| `Model.scope(*scopes, name=None, bases=None)` | classmethod | Derive/fetch the cached projection class. `name` and `bases` join the cache key. |
| `Model.scopes()` | classmethod | `frozenset[type[Scope]]` of the atom scopes used in field tags. |
| `Model.from_projection(proj, **extra)` | classmethod | Projected instance → canonical instance. |
| `Model.__refs__` | ClassVar | The model's `RefGraph`. |
| `Model.__field_scopes__` | ClassVar | `dict[str, ScopeExpr]`: each tagged field's scope expression. |

Methods and attributes on projection classes:

| name | kind | summary |
|---|---|---|
| `Projection.from_canonical(instance, *, mode, by_alias, context, exclude_none, exclude_unset, exclude_defaults, narrow)` | classmethod | Canonical instance → projected instance; kwargs forwarded to `model_dump`. |
| `Projection.__prism_source__` | ClassVar | The canonical `ScopedModel` class this projection derives from. |
| `Projection.__prism_scope__` | ClassVar | The `ScopeExpr` the projection was built for. |
| `Projection.__prism_bases__` | ClassVar | The carried bases tuple (`()` when none). |
| `Projection.__refs__` | ClassVar | The surviving slice of the canonical's `RefGraph`. |

The relationship graph:

| name | kind | summary |
|---|---|---|
| `RefGraph` | class | `Mapping[str, RefInfo]` keyed by field name; `.owner`, `.outgoing`, `.incoming`, `.embedded`, `.targets()`, `.walk()`. |
| `RefInfo` | dataclass | `.field_name`, `.target`, `.target_field`, `.shape`, `.optional`, `.kind` (`"ref" \| "backref" \| "embedded"`), `.via`, `.key_type`, `.scope`, `.many` (derived). |

## vs. prior art

Honest overlap: the projection half of this library has real precedent;
the combination with a relationship graph does not.

| | pydantic-prism | [pydantic-extension](https://github.com/humblemat810/pydantic-extension) | [pydantic-views](https://pydantic-views.readthedocs.io) |
|---|---|---|---|
| scope vocabulary | user-defined `Scope` classes, inheritance graph | 4 built-in modes + runtime `register_mode()` | fixed 6-value CRUD enum |
| composition | full set algebra (`\| & - ~`) | union + exclusion grammar in subscripts | one builder per view |
| derived models | real BaseModel, cached, deterministic names | real BaseModel, cached | real BaseModel |
| relationships | `ref`/`backref` markers, `RefGraph`, survive projection | — | — |
| dict-keyed refs (`dict[UUID, T]`, key = foreign id) | first-class (`RefShape.KEYED_DICT`) | — | — |
| embedded "ref record" projections | auto-registered `embedded` edges with provenance | — | — |
| all-optional Update views | any scope: `partial=True` | — | fixed `Update`/`UpdateOptional` views |
| custom pydantic bases on derived models | `projection_bases=`/`bases=`, isinstance-true | — | — |
| validators on derived models | field validators carried; carried bases keep model validators | lost | lost |
| implicit behavior | none | call-stack sniffing can switch modes; `model_validate` may return a different class | registry monkey-patched onto your class |
| Python | 3.12+ | 3.9+ (claimed) | 3.13+ |

## Not yet (deliberately out of scope)

- **Async resolvers, lazy loading, query builders** — `__refs__` is
  introspection; resolution is your code.
- **Storage backends** of any kind. No sqlalchemy/sqlmodel/ormar imports,
  ever.
- **Migration tooling.**
- **Field-level transformations between scopes** — projection filters
  fields, it never rewrites them.
- **Computed fields on projections** — they are methods that may reference
  dropped fields; not copied.
- **`@model_validator` carryover from the canonical's own body** — see
  Validators above (model validators on *carried bases* do carry).
- **Static type-checker visibility of derived models.** `User.scope(Public)`
  is opaque to mypy/pyright (they cannot see its fields) — the same
  limitation pydantic core cited when declining to build Pick/Omit into
  pydantic itself. Runtime, JSON schema, and FastAPI behavior are fully
  correct; IDE completion on projected *instances* is not. If you need a
  statically-typed shape, hand-write that one class.

## Install & develop

```sh
pip install pydantic-prism        # pydantic >= 2.7, Python >= 3.12
```

```sh
pdm install -G dev
bin/test.sh                       # pytest with coverage
bin/autoformat.sh                 # ruff format + ruff check --fix
pdm run pyright                   # strict, src/
```
