"""Field provenance on projections: the ``Heritage`` metadata marker.

Every projected field inherits the canonical field's description (important for
LLM-facing schemas) and carries a ``Heritage`` stamp in its ``FieldInfo.metadata``
recording whether it was overridden per scope and whether its description is the
canonical's.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from pydantic_prism import Heritage, Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


def _heritage(proj: type, field: str) -> Heritage:
    return next(m for m in proj.model_fields[field].metadata if isinstance(m, Heritage))


class User(ScopedModel):
    plain: Annotated[
        str, Field(description="a public-facing label"), scoped(Public, Internal)
    ]
    retitled: Annotated[
        str,
        Field(description="canonical description"),
        scoped(Public),
        scoped(Internal, override=Field(description="audit-facing description")),
    ]
    constrained: Annotated[
        str,
        Field(description="kept description"),
        scoped(Public, override=Field(min_length=2)),
    ]
    bare: Annotated[int, scoped(Public, Internal)]  # no description anywhere


def test_description_inherits_to_projections() -> None:
    # the original ask: a projected field keeps the canonical description
    assert (
        User.scope(Public).model_fields["plain"].description == "a public-facing label"
    )
    assert (
        User.scope(Public).model_json_schema()["properties"]["plain"]["description"]
        == "a public-facing label"
    )


def test_every_projected_field_has_exactly_one_heritage() -> None:
    proj = User.scope(Internal)
    for name in proj.model_fields:
        stamps = [
            m for m in proj.model_fields[name].metadata if isinstance(m, Heritage)
        ]
        assert len(stamps) == 1
        assert stamps[0].source == name


def test_plain_field_is_inherited() -> None:
    h = _heritage(User.scope(Public), "plain")
    assert h.overridden is False
    assert h.description_inherited is True


def test_overridden_description_is_not_inherited() -> None:
    h = _heritage(User.scope(Internal), "retitled")
    assert h.overridden is True
    assert h.description_inherited is False


def test_non_description_override_keeps_description_inherited() -> None:
    # the field is overridden (min_length) but its description is still canonical
    h = _heritage(User.scope(Public), "constrained")
    assert h.overridden is True
    assert h.description_inherited is True


def test_bare_field_reports_inherited() -> None:
    h = _heritage(User.scope(Public), "bare")
    assert h.overridden is False
    assert h.description_inherited is True


def test_heritage_does_not_leak_into_schema() -> None:
    schema = User.scope(Public).model_json_schema()["properties"]["plain"]
    assert "source" not in schema
    assert set(schema) <= {"description", "title", "type"}


def test_retyped_field_is_overridden() -> None:
    class Llm(Scope): ...

    class M(ScopedModel):
        created: Annotated[
            int,
            Field(description="epoch seconds"),
            scoped(Public),
            scoped(Llm, as_type=str),
        ]

    h = _heritage(M.scope(Llm), "created")
    assert h.overridden is True
    assert h.description_inherited is True  # retype left the description alone


def test_heritage_on_nested_projection_fields() -> None:
    class Inner(ScopedModel):
        label: Annotated[str, Field(description="inner label"), scoped(Public)]

    class Outer(ScopedModel):
        inner: Annotated[Inner, scoped(Public)]

    nested = Outer.scope(Public).model_fields["inner"].annotation
    assert _heritage(nested, "label").description_inherited is True
