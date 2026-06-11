"""Round trips between canonical models and their projections."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    display_name: Annotated[str, scoped(Public)]
    note: str = "untagged"


def test_from_canonical_narrows() -> None:
    user = User(id=uuid4(), email="ada@example.com", display_name="Ada")
    pub = User.scope(Public).from_canonical(user)
    assert pub.model_dump() == {"id": user.id, "display_name": "Ada"}


def test_from_projection_widens_with_extra() -> None:
    user = User(id=uuid4(), email="ada@example.com", display_name="Ada")
    pub = User.scope(Public).from_canonical(user)
    back = User.from_projection(pub, email="ada@example.com")
    assert isinstance(back, User)
    assert back.id == user.id
    assert back.email == "ada@example.com"
    assert back.note == "untagged"  # canonical default applies


def test_from_projection_missing_required_fields_fails() -> None:
    pub = User.scope(Public)(id=uuid4(), display_name="Ada")
    with pytest.raises(ValidationError):
        User.from_projection(pub)  # email has no default and no extra given


def test_plain_pydantic_round_trip() -> None:
    # no helper needed: field names and types are identical by construction
    user = User(id=uuid4(), email="e@x.io", display_name="Ada")
    dumped = User.scope(Internal).model_validate(user.model_dump()).model_dump()
    restored = User.model_validate(dumped)
    assert restored.email == "e@x.io"


def test_wider_projection_feeds_narrower_canonical_path() -> None:
    internal = User.scope(Internal)(id=uuid4(), email="e@x.io", display_name="Ada")
    pub = User.scope(Public).from_canonical(internal)
    assert set(pub.model_dump()) == {"id", "display_name"}
