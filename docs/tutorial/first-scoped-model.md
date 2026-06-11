# Your first scoped model

This lesson takes one model from definition to two working projections, then
adds a relationship and watches it survive the projection. Every code block
runs; paste them in order into one file or a REPL and follow along.

By the end you will have written one canonical model and derived a
public-facing view and an internal view from it — no parallel classes.

## 1. Declare your scopes

A **scope** is a named audience for your fields. You declare scopes as
subclasses of `Scope`. Subclassing *broadens*: `Internal` will see everything
`Public` sees.

```python
from pydantic_prism import Scope


class Public(Scope): ...
class Internal(Public): ...
```

## 2. Tag one canonical model

Write the entity once. Tag each field with the narrowest scope that should
see it, using `scoped(...)` inside `Annotated[...]`.

```python
from typing import Annotated
from uuid import UUID

from pydantic_prism import ScopedModel, scoped


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    display_name: Annotated[str, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
```

`User` is an ordinary `pydantic.BaseModel` you can instantiate and validate as
usual. The `scoped(...)` tags are inert metadata — pydantic ignores them.

## 3. Project to a scope

Ask the model for a projection with `.scope(...)`. You get back a real, cached
`BaseModel` subclass.

```python
UserPublic = User.scope(Public)
UserInternal = User.scope(Internal)

assert list(UserPublic.model_fields) == ["id", "display_name"]
assert list(UserInternal.model_fields) == ["id", "display_name", "email"]
```

`UserPublic` keeps only `Public` fields. `UserInternal` keeps everything
`Public` and `Internal` see, because `Internal` subclasses `Public`. That is
the whole membership rule: a field tagged `T` survives in projection `S` when
`issubclass(S, T)`.

The result is stable — the same expression always returns the same class:

```python
assert User.scope(Public) is User.scope(Public)
assert UserPublic.__name__ == "UserPublic"
```

That identity is what keeps FastAPI response models and OpenAPI component
names from churning.

## 4. Move data between the shapes

Narrow a full instance down to a projection with `from_canonical`, and widen a
projection back to the canonical with `from_projection` (supplying whatever the
projection dropped):

```python
user = UserInternal(
    id="00000000-0000-0000-0000-000000000001",
    display_name="Ada",
    email="ada@example.com",
)

public = UserPublic.from_canonical(user)
assert set(public.model_dump()) == {"id", "display_name"}

full = User.from_projection(public, email="ada@example.com")
assert full.email == "ada@example.com"
```

## 5. Add a relationship that survives projection

Here is what hand-written `UserIn`/`UserOut` classes cannot do. Declare an
FK-style reference with `ref(...)`; it is recorded in `__refs__` and stays
introspectable on every projection.

```python
from pydantic_prism import ref


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    user_id: Annotated[UUID, ref(User), scoped(Public)]


# the edge is there on the canonical...
assert Order.__refs__["user_id"].target is User

# ...and it is still there after projecting
OrderPublic = Order.scope(Public)
assert OrderPublic.__refs__["user_id"].target is User
```

The projection forgot the fields it doesn't need, but it did not forget that
`user_id` points at `User`.

## What you learned

- Scopes are classes; inheritance forms the scope graph.
- A field survives projection `S` iff `issubclass(S, T)` for its tag `T`.
- `.scope(...)` returns real, cached, identity-stable model classes.
- `from_canonical` narrows, `from_projection` widens.
- `ref(...)` relationships survive projection.

## Where to next

- A task in hand? Go to the **[how-to guides](../how-to/README.md)** — PATCH
  models, FastAPI, ORM bridges, PII redaction, diagrams.
- Want the full vocabulary? The **[API reference](../reference/api.md)** lists
  every symbol.
- Curious *why* it works this way? Read
  **[scopes and the algebra](../explanation/scopes-and-the-algebra.md)**.
