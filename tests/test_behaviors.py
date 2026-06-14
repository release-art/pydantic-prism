"""Behavior survival: methods / properties / class- & staticmethods on projections.

By default prism copies a canonical model's non-field callables onto every
projection; ``@unprojected`` opts a member out, and framework names are never
overwritten.
"""

from __future__ import annotations

from typing import Annotated

from pydantic_prism import Projection, Scope, ScopedModel, scoped, unprojected


class Header(Scope): ...


class Storage(Scope): ...


class Card(ScopedModel):
    name: Annotated[str, scoped(Header, Storage)]
    hashes: Annotated[list[str], scoped(Storage)]

    @property
    def is_quarantined(self) -> bool:
        return self.name.startswith("!")

    @classmethod
    def of(cls, name: str) -> Card:
        return cls(name=name, hashes=[])

    @staticmethod
    def banner() -> str:
        return "CARD"

    def shout(self) -> str:
        return self.name.upper()

    @unprojected
    def storage_only(self) -> int:  # depends conceptually on storage-only data
        return len(self.hashes)

    @unprojected
    @property
    def secret(self) -> str:
        return "x"

    @unprojected
    @classmethod
    def hidden_cm(cls) -> str:
        return "cm"

    @unprojected
    @staticmethod
    def hidden_sm() -> str:
        return "sm"

    def run_inherited_before(self) -> str:  # collides with a framework name
        return "canonical"


def test_property_survives() -> None:
    proj = Card.scope(Storage)
    inst = proj(name="!bad", hashes=[])
    assert inst.is_quarantined is True


def test_classmethod_survives() -> None:
    proj = Card.scope(Header)
    built = proj.of("hi")
    assert isinstance(built, proj)
    assert built.name == "hi"


def test_staticmethod_survives() -> None:
    assert Card.scope(Header).banner() == "CARD"


def test_plain_method_survives() -> None:
    inst = Card.scope(Header)(name="hi")
    assert inst.shout() == "HI"


def test_unprojected_members_are_dropped() -> None:
    proj = Card.scope(Storage)
    for name in ("storage_only", "secret", "hidden_cm", "hidden_sm"):
        assert name not in vars(proj)
    # …but stay on the canonical model
    canonical = Card(name="x", hashes=["a"])
    assert canonical.storage_only() == 1
    assert canonical.secret == "x"
    assert Card.hidden_cm() == "cm"
    assert Card.hidden_sm() == "sm"
    # the shadowing instance-method is still live on the canonical itself
    assert canonical.run_inherited_before() == "canonical"


def test_framework_name_is_not_overwritten() -> None:
    proj = Card.scope(Header)
    # the canonical instance-method shadow is *not* copied; the projection keeps
    # Projection's classmethod
    assert "run_inherited_before" not in vars(proj)
    assert (
        proj.run_inherited_before.__func__ is Projection.run_inherited_before.__func__
    )


def test_most_derived_definition_wins() -> None:
    class Base(ScopedModel):
        tag: Annotated[str, scoped(Header)]

        def label(self) -> str:
            return "base"

    class Child(Base):
        def label(self) -> str:
            return "child"

    assert Child.scope(Header)(tag="t").label() == "child"
    # the ancestor definition is what a projection of the ancestor carries
    assert Base.scope(Header)(tag="t").label() == "base"


def test_model_with_no_extra_behavior_projects() -> None:
    class Plain(ScopedModel):
        x: Annotated[int, scoped(Header)]

    assert Plain.scope(Header)(x=1).x == 1
