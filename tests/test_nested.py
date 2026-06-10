"""Scope propagation through nested ScopedModel annotations."""

from typing import Annotated, Optional, get_args, get_origin
from uuid import UUID, uuid4

from pydantic import Field

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Internal(Public): ...


class Address(ScopedModel):
    city: Annotated[str, scoped(Public)]
    plus_code: Annotated[str, scoped(Internal)] = ""


class Shipment(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    destination: Annotated[Address | None, scoped(Public)] = None
    waypoints: Annotated[list[Address], scoped(Internal)] = Field(default_factory=list)
    by_label: Annotated[dict[str, Address], scoped(Internal)] = Field(default_factory=dict)


def test_nested_annotation_rewritten_to_projection() -> None:
    ShipmentPublic = Shipment.scope(Public)
    annotation = ShipmentPublic.model_fields["destination"].annotation
    assert annotation == Optional[Address.scope(Public)]  # noqa: UP045


def test_nested_projection_classes_are_cached_singletons() -> None:
    inner = Shipment.scope(Public).model_fields["destination"].annotation
    assert get_args(inner)[0] is Address.scope(Public)


def test_nested_validation_filters_fields() -> None:
    ShipmentPublic = Shipment.scope(Public)
    shipment = ShipmentPublic.model_validate(
        {"id": str(uuid4()), "destination": {"city": "Riga", "plus_code": "9G86"}}
    )
    assert shipment.destination is not None
    assert shipment.destination.model_dump() == {"city": "Riga"}


def test_nested_containers_rewritten() -> None:
    ShipmentInternal = Shipment.scope(Internal)
    waypoints_ann = ShipmentInternal.model_fields["waypoints"].annotation
    assert get_origin(waypoints_ann) is list
    assert get_args(waypoints_ann)[0] is Address.scope(Internal)
    by_label_ann = ShipmentInternal.model_fields["by_label"].annotation
    assert get_args(by_label_ann) == (str, Address.scope(Internal))


def test_directly_recursive_model() -> None:
    class TreeNode(ScopedModel):
        name: Annotated[str, scoped(Public)]
        children: Annotated[list["TreeNode"], scoped(Public)] = Field(default_factory=list)

    TreeNode.model_rebuild()
    TreePublic = TreeNode.scope(Public)
    tree = TreePublic.model_validate({"name": "root", "children": [{"name": "leaf"}]})
    assert type(tree.children[0]) is TreePublic
    assert tree.model_dump() == {
        "name": "root",
        "children": [{"name": "leaf", "children": []}],
    }


class Ping(ScopedModel):
    name: Annotated[str, scoped(Public)]
    pong: Annotated["Pong | None", scoped(Public)] = None


class Pong(ScopedModel):
    name: Annotated[str, scoped(Public)]
    ping: Annotated[Ping | None, scoped(Public)] = None


Ping.model_rebuild()


def test_mutually_recursive_models() -> None:
    PingPublic = Ping.scope(Public)
    value = PingPublic.model_validate({"name": "a", "pong": {"name": "b", "ping": {"name": "c"}}})
    assert value.pong is not None and value.pong.ping is not None
    assert value.pong.ping.name == "c"
    assert type(value.pong) is Pong.scope(Public)
