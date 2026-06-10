"""FastAPI compatibility smoke test: same entity, different scopes per route."""

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    display_name: Annotated[str, scoped(Public)]


USER = User(
    id=UUID("00000000-0000-0000-0000-000000000001"),
    email="ada@example.com",
    display_name="Ada",
)

app = FastAPI()


@app.get("/users/{user_id}", response_model=User.scope(Public))
def get_user_public(user_id: UUID) -> User:
    return USER


@app.get("/admin/users/{user_id}", response_model=User.scope(Internal))
def get_user_internal(user_id: UUID) -> User:
    return USER


client = TestClient(app)


def test_public_route_filters_fields() -> None:
    response = client.get(f"/users/{USER.id}")
    assert response.status_code == 200
    assert response.json() == {"id": str(USER.id), "display_name": "Ada"}


def test_internal_route_includes_email() -> None:
    response = client.get(f"/admin/users/{USER.id}")
    assert response.status_code == 200
    assert response.json() == {
        "id": str(USER.id),
        "email": "ada@example.com",
        "display_name": "Ada",
    }


def test_openapi_schema_has_both_projections() -> None:
    schemas = app.openapi()["components"]["schemas"]
    assert set(schemas["UserPublic"]["properties"]) == {"id", "display_name"}
    assert set(schemas["UserInternal"]["properties"]) == {"id", "email", "display_name"}
