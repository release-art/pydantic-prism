"""Read-only / write-only fields: ``input()`` / ``output()`` and the In/Out axis.

Run from the repository root:

    pdm run python examples/readwrite_fields/main.py

Shows: the read/write *direction* axis (``In`` / ``Out``) as a third axis next to
visibility. Tag the exceptions — a read-only field with ``Out``, a write-only
field with ``In`` — and derive the request/response faces with ``input()`` /
``output()``. ``input()`` drops read-only fields (mass-assignment protection by
shape) and defaults to ``extra="forbid"`` so unknown keys are rejected;
``output()`` drops write-only fields so they never leak back.
"""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, ValidationError

from pydantic_prism import In, Out, Scope, ScopedModel, scoped


class Public(Scope): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public, Out), Field(description="Server-set id.")]
    created_at: Annotated[
        str, scoped(Public, Out), Field(description="Server-set timestamp.")
    ]
    email: Annotated[str, scoped(Public), Field(description="Read-write contact.")]
    password: Annotated[
        str, scoped(Public, In), Field(description="Write-only credential.")
    ]


def demo() -> None:
    UserIn = User.input(Public)  # request body: minus read-only fields
    UserOut = User.output(Public)  # response model: minus write-only fields

    print(f"input  ({UserIn.__name__}):  {sorted(UserIn.model_fields)}")
    print(f"output ({UserOut.__name__}): {sorted(UserOut.model_fields)}")

    # A read-only field cannot be over-posted — it is not even a field here.
    created = UserIn(email="a@b.c", password="hunter2")
    print(f"id is not on the input model: {'id' not in UserIn.model_fields}")

    # extra='forbid' rejects unknown keys outright (a loud 422).
    try:
        UserIn(email="a@b.c", password="hunter2", is_admin=True)
    except ValidationError:
        print("over-post of 'is_admin' rejected")

    # The response face never echoes the write-only password.
    stored = User(
        id=uuid4(), created_at="2026-06-11T00:00:00Z", email="a@b.c", password="hunter2"
    )
    out = UserOut.from_canonical(stored)
    print(f"output dump has no password: {'password' not in out.model_dump()}")
    print(f"the same class is cached: {User.input(Public) is UserIn}")
    # silence the unused-variable check while keeping the example readable
    assert created.email == "a@b.c"


if __name__ == "__main__":
    demo()
