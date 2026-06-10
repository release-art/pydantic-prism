"""One canonical User model served at two shapes on different routes.

Run from the repository root:

    pdm run uvicorn examples.fastapi_app.main:app --reload

Then compare:

    curl http://127.0.0.1:8000/users                    # public shape
    curl http://127.0.0.1:8000/admin/users              # internal shape
    open http://127.0.0.1:8000/docs                     # both schemas documented
"""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...  # Internal sees everything Public sees


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    signup_ip: Annotated[str, scoped(Internal)]
    display_name: Annotated[str, scoped(Public)]


UserPublic = User.scope(Public)
UserInternal = User.scope(Internal)

DB: dict[UUID, User] = {
    user.id: user
    for user in (
        User(
            id=uuid4(),
            email="ada@example.com",
            signup_ip="10.0.0.1",
            display_name="Ada",
        ),
        User(
            id=uuid4(),
            email="alan@example.com",
            signup_ip="10.0.0.2",
            display_name="Alan",
        ),
    )
}

app = FastAPI(title="pydantic-prism demo: one model, two shapes")


def _get(user_id: UUID) -> User:
    user = DB.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="no such user")
    return user


@app.get("/users", response_model=list[UserPublic])
def list_users_public() -> list[User]:
    return list(DB.values())


@app.get("/users/{user_id}", response_model=UserPublic)
def read_user_public(user_id: UUID) -> User:
    return _get(user_id)


@app.get("/admin/users", response_model=list[UserInternal])
def list_users_internal() -> list[User]:
    return list(DB.values())


@app.get("/admin/users/{user_id}", response_model=UserInternal)
def read_user_internal(user_id: UUID) -> User:
    return _get(user_id)
