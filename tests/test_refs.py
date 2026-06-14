"""The relationship graph: ref/backref markers, RefGraph, projection survival."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest

from pydantic_prism import (
    RefGraph,
    RefInfo,
    RefResolutionError,
    Scope,
    ScopedModel,
    backref,
    ref,
    scoped,
)


class Public(Scope): ...


class Internal(Public): ...


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    order_ids: Annotated[
        list[UUID], backref("Order", via="customer_id"), scoped(Internal)
    ]


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
    coupon_id: Annotated[UUID | None, ref("Coupon"), scoped(Internal)] = None
    total: Annotated[str, scoped(Internal)]


class Coupon(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    code: Annotated[str, scoped(Public)]


class NodeA(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    b_id: Annotated[UUID, ref("NodeB"), scoped(Public)]


class NodeB(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    a_id: Annotated[UUID, ref(NodeA), scoped(Public)]


def test_forward_ref_info() -> None:
    info = Order.__prism__.refs["customer_id"]
    assert isinstance(info, RefInfo)
    assert info.target is Customer
    assert info.target_field == "id"
    assert info.kind == "ref"
    assert not info.many
    assert not info.optional


def test_string_target_resolves_lazily() -> None:
    info = Order.__prism__.refs["coupon_id"]
    assert info.target is Coupon
    assert info.optional and not info.many


def test_backref_info_and_validation() -> None:
    info = Customer.__prism__.refs["order_ids"]
    assert info.kind == "backref"
    assert info.target is Order
    assert info.via == "customer_id"
    assert info.many and not info.optional


def test_backref_implies_empty_default() -> None:
    customer = Customer(id=uuid4(), name="Ada")
    assert customer.order_ids == []


def test_graph_views() -> None:
    assert isinstance(Order.__prism__.refs, RefGraph)
    assert set(Order.__prism__.refs.outgoing) == {"customer_id", "coupon_id"}
    assert Order.__prism__.refs.incoming == {}
    assert set(Customer.__prism__.refs.incoming) == {"order_ids"}
    assert Order.__prism__.refs.targets() == {Customer, Coupon}
    assert len(Order.__prism__.refs) == 2


def test_walk_is_bfs_and_terminates_on_cycles() -> None:
    edges = [
        (src.__name__, info.field_name, info.target.__name__)
        for src, info in NodeA.__prism__.refs.walk()
    ]
    assert edges == [("NodeA", "b_id", "NodeB"), ("NodeB", "a_id", "NodeA")]


def test_refs_survive_projection() -> None:
    OrderPublic = Order.scope(Public)
    assert set(OrderPublic.__prism__.refs) == {
        "customer_id"
    }  # coupon_id is Internal-only
    assert OrderPublic.__prism__.refs["customer_id"].target is Customer
    OrderInternal = Order.scope(Internal)
    assert set(OrderInternal.__prism__.refs) == {"customer_id", "coupon_id"}


def test_unresolvable_string_target() -> None:
    class Dangling(ScopedModel):
        other_id: Annotated[UUID, ref("NoSuchModel"), scoped(Public)]

    with pytest.raises(RefResolutionError, match="NoSuchModel"):
        Dangling.__prism__.refs["other_id"]


def test_backref_via_missing_field() -> None:
    class BadVia(ScopedModel):
        order_ids: Annotated[list[UUID], backref(Order, via="nope"), scoped(Public)]

    with pytest.raises(RefResolutionError, match="no ref"):
        BadVia.__prism__.refs["order_ids"]


def test_backref_via_points_at_wrong_model() -> None:
    class NotTheCustomer(ScopedModel):
        order_ids: Annotated[
            list[UUID], backref(Order, via="customer_id"), scoped(Public)
        ]

    with pytest.raises(RefResolutionError, match="references Customer"):
        NotTheCustomer.__prism__.refs["order_ids"]


def test_backref_via_field_without_ref_marker() -> None:
    class ViaPlainField(ScopedModel):
        order_ids: Annotated[list[UUID], backref(Order, via="total"), scoped(Public)]

    with pytest.raises(RefResolutionError, match="no ref"):
        ViaPlainField.__prism__.refs["order_ids"]


def test_cardinality_variants() -> None:
    class Many(ScopedModel):
        ids_list: Annotated[list[UUID], ref(Coupon), scoped(Public)]
        ids_set: Annotated[set[UUID], ref(Coupon), scoped(Public)]
        maybe_many: Annotated[list[UUID] | None, ref(Coupon), scoped(Public)] = None

    assert Many.__prism__.refs["ids_list"].many
    assert Many.__prism__.refs["ids_set"].many
    info = Many.__prism__.refs["maybe_many"]
    assert info.many and info.optional


def test_custom_target_field() -> None:
    class ByCode(ScopedModel):
        coupon_code: Annotated[str, ref(Coupon, field="code"), scoped(Public)]

    assert ByCode.__prism__.refs["coupon_code"].target_field == "code"
