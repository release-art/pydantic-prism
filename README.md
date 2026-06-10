# pydantic-prism

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
- Cardinality is inferred from the annotation: `UUID` → to-one,
  `list[UUID]` → to-many, `UUID | None` → optional.

Introspect via `__refs__`, a `Mapping[str, RefInfo]`:

```python
info = Order.__refs__["customer_id"]
# info.target is Customer, info.target_field == "id"
# info.many is False, info.optional is False, info.kind == "ref"

Order.__refs__.outgoing          # forward edges only
Customer.__refs__.incoming       # declared backrefs only
Order.__refs__.targets()         # {Customer}
list(Order.__refs__.walk())      # BFS over reachable forward edges
```

Refs survive projection — this is the point:

```python
OrderPublic = Order.scope(Public)
OrderPublic.__refs__["customer_id"].target is Customer  # True
```

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

## Validators

`@field_validator`s carry over to projections for the fields that survive
(re-targeted to the surviving subset). `@model_validator`s do **not** — they
assume the full canonical field set. Validators and constraints declared in
`Annotated` metadata (`Field(gt=0)`, `AfterValidator`, …) survive
automatically, because annotations are copied.

Caveat: a carried field validator that reads `info.data` of a dropped field
will fail at validation time.

## Errors

| situation | error | when |
|---|---|---|
| marker used as a field default | `TypeError` | class definition |
| marker nested below the field's top-level `Annotated` | `TypeError` | class definition |
| `ref()` target neither ScopedModel nor str | `TypeError` | marker construction |
| two `ref`/`backref` markers on one field | `TypeError` | class definition |
| projection selects zero fields | `EmptyProjectionError` | `.scope()` call |
| one projection name for two different expressions | `ProjectionNameError` | `.scope()` call |
| string target doesn't resolve (or model is function-local) | `RefResolutionError` | `__refs__` access |
| `backref(via=...)` doesn't match a forward ref | `RefResolutionError` | `__refs__` access |

`EmptyProjectionError`, `ProjectionNameError` and `RefResolutionError`
subclass `PrismError` (and `ValueError`). Models whose annotations were
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

## API reference

| name | kind | summary |
|---|---|---|
| `Scope` | class | Subclass to declare a scope; subclass a scope to broaden it. Root = wildcard. Never instantiated. |
| `ScopedModel` | class | Base for canonical models. |
| `scoped(*scopes)` | marker | Tags a field with scopes / a scope expression. Varargs union. |
| `ref(target, *, field="id")` | marker | Forward FK-style reference. `target`: ScopedModel subclass or string. |
| `backref(target, *, via, field="id")` | marker | Declared reverse reference; `via` names the forward-ref field on `target`. |
| `Model.scope(*scopes, name=None)` | classmethod | Derive/fetch the cached projection class. |
| `Model.from_projection(proj, **extra)` | classmethod | Projected instance → canonical instance. |
| `Projection.from_canonical(instance)` | classmethod | Canonical instance → projected instance. |
| `Model.__refs__` | attribute | `RefGraph`: mapping of field name → `RefInfo`, plus `.outgoing`, `.incoming`, `.targets()`, `.walk()`. |
| `RefInfo` | dataclass | `.field_name`, `.target`, `.target_field`, `.many`, `.optional`, `.kind`, `.via`. |

## vs. prior art

Honest overlap: the projection half of this library has real precedent;
the combination with a relationship graph does not.

| | pydantic-prism | [pydantic-extension](https://github.com/humblemat810/pydantic-extension) | [pydantic-views](https://pydantic-views.readthedocs.io) |
|---|---|---|---|
| scope vocabulary | user-defined `Scope` classes, inheritance graph | 4 built-in modes + runtime `register_mode()` | fixed 6-value CRUD enum |
| composition | full set algebra (`\| & - ~`) | union + exclusion grammar in subscripts | one builder per view |
| derived models | real BaseModel, cached, deterministic names | real BaseModel, cached | real BaseModel |
| relationships | `ref`/`backref` markers, `RefGraph`, survive projection | — | — |
| validators on derived models | field validators carried | lost | lost |
| implicit behavior | none | call-stack sniffing can switch modes; `model_validate` may return a different class | registry monkey-patched onto your class |
| Python | 3.12+ | 3.9+ (claimed) | 3.13+ |

If you want CRUD-shaped views (all-optional `Update` models and friends),
pydantic-views does that today and v0.1 of prism does not (see below).

## Not yet (deliberately out of v0.1)

- **Async resolvers, lazy loading, query builders** — `__refs__` is
  introspection; resolution is your code.
- **Storage backends** of any kind. No sqlalchemy/sqlmodel/ormar imports,
  ever.
- **Migration tooling.**
- **Field-level transformations between scopes** — projection filters
  fields, it never rewrites them.
- **Optional-on-projection / required-on-canonical asymmetry** (the
  all-optional `Update` model) — deferred to v0.2.
- **Computed fields on projections** — they are methods that may reference
  dropped fields; not copied in v0.1.
- **`@model_validator` carryover** — see Validators above.
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
