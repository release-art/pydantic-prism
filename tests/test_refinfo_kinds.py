"""RefInfo discriminated by kind: IdRefInfo / BackRefInfo / EmbeddedRefInfo."""

from typing import Annotated
from uuid import UUID

from pydantic_prism import (
    BackRefInfo,
    EmbeddedRefInfo,
    IdRefInfo,
    RefInfo,
    RefShape,
    Scope,
    ScopedModel,
    backref,
    ref,
    scoped,
)


class Public(Scope): ...


class Carrier(Scope): ...


class Snapshot(ScopedModel):
    id: Annotated[UUID, scoped(Public, Carrier)]
    taken_at: Annotated[str, scoped(Public, Carrier)]


SnapshotRef = Snapshot.scope(Carrier)


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    order_ids: Annotated[
        list[UUID], backref("Order", via="customer_id"), scoped(Public)
    ]


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
    highlights: Annotated[dict[UUID, Snapshot], ref(Snapshot), scoped(Public)]
    history: Annotated[list[SnapshotRef], scoped(Public)] = []  # type: ignore[valid-type]


def test_ref_edge_is_idrefinfo() -> None:
    info = Order.__prism__.refs["customer_id"]
    assert isinstance(info, IdRefInfo)
    assert isinstance(info, RefInfo)  # base
    assert info.kind == "ref"
    assert not isinstance(info, (BackRefInfo, EmbeddedRefInfo))


def test_backref_edge_is_backrefinfo_with_via() -> None:
    info = Customer.__prism__.refs["order_ids"]
    assert isinstance(info, BackRefInfo)
    assert info.kind == "backref"
    assert info.via == "customer_id"  # non-optional on the variant


def test_embedded_edge_is_embeddedrefinfo_with_scope() -> None:
    info = Order.__prism__.refs["history"]
    assert isinstance(info, EmbeddedRefInfo)
    assert info.kind == "embedded"
    assert info.scope == SnapshotRef.__prism__.scope


def test_via_and_scope_are_not_on_other_kinds() -> None:
    # The split moved via/scope off the base: they exist only on their variant.
    id_info = Order.__prism__.refs["customer_id"]
    assert not hasattr(id_info, "via")
    assert not hasattr(id_info, "scope")
    back_info = Customer.__prism__.refs["order_ids"]
    assert not hasattr(back_info, "scope")


def test_key_type_and_many_stay_on_base() -> None:
    # key_type is shape-driven, so it lives on the base regardless of kind.
    dict_ref = Order.__prism__.refs["highlights"]
    assert isinstance(dict_ref, IdRefInfo)
    assert dict_ref.shape is RefShape.KEYED_DICT
    assert dict_ref.key_type is UUID
    assert dict_ref.many  # compat property on the base
    assert Order.__prism__.refs["customer_id"].many is False


def test_accessors_return_precise_subtypes() -> None:
    assert all(isinstance(v, IdRefInfo) for v in Order.__prism__.refs.outgoing.values())
    assert all(
        isinstance(v, BackRefInfo) for v in Customer.__prism__.refs.incoming.values()
    )
    assert all(
        isinstance(v, EmbeddedRefInfo) for v in Order.__prism__.refs.embedded.values()
    )


def test_subtypes_survive_projection() -> None:
    proj_refs = Order.scope(Public).__prism__.refs
    assert isinstance(proj_refs["customer_id"], IdRefInfo)
    assert isinstance(proj_refs["history"], EmbeddedRefInfo)
