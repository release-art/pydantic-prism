# Use projections with FastAPI

**Goal:** serve one canonical object at different shapes on different routes —
a public response and an internal/admin response — each documented separately
in `/docs`, with no hand-written DTOs.

A projection is a real `BaseModel` subclass, so it drops straight into
`response_model=`. Because `.scope(...)` is cached and identity-stable, the
OpenAPI component schema for each shape stays put.

```python
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...
class Internal(Public): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    display_name: Annotated[str, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    signup_ip: Annotated[str, scoped(Internal)]


UserPublic = User.scope(Public)
UserInternal = User.scope(Internal)

app = FastAPI()


@app.get("/users/{user_id}", response_model=UserPublic)
def get_user(user_id: UUID) -> User: ...


@app.get("/admin/users/{user_id}", response_model=UserInternal)
def get_user_admin(user_id: UUID) -> User: ...
```

Return a full canonical `User` from either handler; FastAPI shapes the response
to the route's `response_model`. `GET /users/...` serves `id` + `display_name`;
`GET /admin/users/...` adds `email` + `signup_ip`. `/docs` documents both
`UserPublic` and `UserInternal` schemas.

`response_model=list[UserPublic]` works for collection routes too.

## Request bodies, too

The same model gives you the **request** side. Tag server-controlled fields
read-only (`scoped(..., Out)`) and secrets write-only (`scoped(..., In)`), then
use `User.input(Public)` as the body type and `User.output(Public)` as the
`response_model` — `POST` accepts no `id`/`created_at` (mass-assignment-safe,
and unknown keys are rejected by the default `extra="forbid"`) and never echoes
the password back. See
[prevent mass-assignment](prevent-mass-assignment.md) for the full recipe.

See the runnable [`examples/fastapi_app`](../../examples/fastapi_app) and the
ref-graph variant in [`examples/graph`](../../examples/graph).
