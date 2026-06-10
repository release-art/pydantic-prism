"""Class-level projection_name_template."""

from typing import Annotated

import pytest

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


def test_template_names_projections() -> None:
    class User(ScopedModel, projection_name_template="{model}_{scope}"):
        id: Annotated[int, scoped(Public)]
        email: Annotated[str, scoped(Internal)]

    assert User.scope(Public).__name__ == "User_Public"
    assert User.scope(Internal).__name__ == "User_Internal"
    # expression tokens flow through too
    assert User.scope(Public | Internal).__name__ == "User_InternalOrPublic"


def test_call_site_name_overrides_template() -> None:
    class User(ScopedModel, projection_name_template="{model}_{scope}"):
        id: Annotated[int, scoped(Public)]

    assert User.scope(Public, name="UserPub").__name__ == "UserPub"


def test_default_when_no_template() -> None:
    class User(ScopedModel):
        id: Annotated[int, scoped(Public)]

    assert User.scope(Public).__name__ == "UserPublic"


def test_template_inherited_and_overridable() -> None:
    class Base(ScopedModel, projection_name_template="{model}__{scope}"):
        id: Annotated[int, scoped(Public)]

    class Sub(Base):  # inherits the template; {model} is the subclass name
        extra: Annotated[int, scoped(Public)] = 0

    assert Sub.scope(Public).__name__ == "Sub__Public"

    class Reset(Base, projection_name_template=None):  # back to the default form
        more: Annotated[int, scoped(Public)] = 0

    assert Reset.scope(Public).__name__ == "ResetPublic"


def test_non_identifier_template_rejected_at_definition() -> None:
    with pytest.raises(TypeError, match="valid Python identifier"):

        class Bad(ScopedModel, projection_name_template="{model}@{scope}"):
            id: Annotated[int, scoped(Public)]


def test_unknown_placeholder_rejected_at_definition() -> None:
    with pytest.raises(TypeError, match="invalid projection_name_template"):

        class Bad(ScopedModel, projection_name_template="{model}_{scop}"):
            id: Annotated[int, scoped(Public)]

    with pytest.raises(TypeError, match="invalid projection_name_template"):

        class Bad2(ScopedModel, projection_name_template="{0}_{scope}"):
            id: Annotated[int, scoped(Public)]
