# Prevent mass-assignment with read-only / write-only fields

**Goal:** stop a client from over-posting a server-controlled field (`id`,
`created_at`, `is_admin`) and stop a write-only field (a password) from leaking
back in responses — *by shape*, without writing parallel `UserIn` / `UserOut`
classes that drift from the canonical.

Direction is an axis *orthogonal* to visibility, exactly like classification: a
field is read-only, write-only, or — the common case — read-write. You annotate
only the exceptions (the DRF / Marshmallow model): tag a **read-only** field
with `Out`, a **write-only** field with `In`, and leave read-write fields with
just their visibility scope.

```python
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import ValidationError

from pydantic_prism import In, Out, Scope, ScopedModel, scoped


class Public(Scope): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public, Out)]        # read-only  (server-set)
    created_at: Annotated[str, scoped(Public, Out)]  # read-only
    email: Annotated[str, scoped(Public)]            # read-write
    password: Annotated[str, scoped(Public, In)]     # write-only
```

`input()` is the write side — the visibility view *minus* read-only fields — and
`output()` is the read side — *minus* write-only fields:

```python
UserIn = User.input(Public)     # what a request body validates against
UserOut = User.output(Public)   # what a response serializes

assert set(UserIn.model_fields) == {"email", "password"}   # no id / created_at
assert set(UserOut.model_fields) == {"id", "created_at", "email"}  # no password
```

The names are exactly the ones you would have hand-written — `UserIn` /
`UserOut` — and `User.input(Public) is User.input(Public)`, so FastAPI response
models and OpenAPI component schemas stay stable. A plain `User.scope(Public)`
is still the *full* schema (all four fields); `input()` / `output()` are the
directional filters.

## Why this is mass-assignment protection

A read-only field is simply **absent** from the input projection, so it can
never be set from a request body — there is nothing to over-post:

```python
body = {"email": "a@b.c", "password": "pw", "id": str(uuid4())}
created = UserIn(**{k: v for k, v in body.items() if k != "id"})
assert not hasattr(created, "id")  # id is not even a field here
```

`input()` also defaults to `extra="forbid"`, so an *unknown* key is rejected
outright (a loud 422) rather than silently dropped — and that is the only thing
that closes the hole when the canonical model itself declares `extra="allow"`:

```python
try:
    UserIn(email="a@b.c", password="pw", is_admin=True)
    raise AssertionError("unreachable")
except ValidationError:
    pass  # 'is_admin' rejected
```

Pass `extra="ignore"` / `"allow"` to opt out per view. `output()` leaves the
config untouched — over-posting does not apply server→client.

## It is deep, and it composes

The directional subtraction propagates into nested `ScopedModel` fields, so
read-only fields drop at every level (the top-level `extra="forbid"` is
top-level only — nest `input()` on a field's model for deep rejection). And
because `input()` / `output()` return ordinary projections, they compose: an
`input()` of a `partial=True` scope is the PATCH-input shape that *also* drops
read-only fields.

```python
class Update(Scope, partial=True): ...


class Article(ScopedModel):
    id: Annotated[UUID, scoped(Update, Out)]
    title: Annotated[str, scoped(Update)]


ArticleUpdate = Article.input(Update)
assert set(ArticleUpdate.model_fields) == {"title"}   # read-only id dropped
assert ArticleUpdate.__prism_scope__.is_partial()     # every field optional
```

## No visibility ladder? Use a neutral scope

If you only care about direction (no `Public < Internal` ladder), declare one
neutral visibility scope and make it the model's `default_scope`; then `input()`
/ `output()` need no argument. A read-write field is the one tagged with *just*
that scope — do **not** tag it `In | Out` (a field tagged `Out` is removed by
`input()`, so `In | Out` would be dropped too).

```python
class Api(Scope): ...


class Token(ScopedModel, default_scope=Api):
    id: Annotated[UUID, scoped(Api, Out)]      # read-only
    label: Annotated[str, scoped(Api)]         # read-write
    secret: Annotated[str, scoped(Api, In)]    # write-only


assert set(Token.input().model_fields) == {"label", "secret"}
assert set(Token.output().model_fields) == {"id", "label"}
```

> [!NOTE]
> This is protection *by shape*, not a per-request authorization check. prism
> decides which fields *exist* on the input model; it never decides whether
> *this* caller may write *this* field. Pair it with your auth layer.

**Next:** [use projections with FastAPI](use-with-fastapi.md) to wire `input()`
as the request body and `output()` as the `response_model`.
