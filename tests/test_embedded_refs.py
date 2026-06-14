"""Embedded models (projection carriers and composition) in the ref graph."""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic_prism import RefShape, Scope, ScopedModel, scoped


class Public(Scope): ...


class Carrier(Scope): ...


class Snapshot(ScopedModel):
    id: Annotated[UUID, scoped(Public, Carrier)]
    taken_at: Annotated[str, scoped(Public, Carrier)]
    blob: Annotated[str, scoped(Public)]


SnapshotRef = Snapshot.scope(Carrier)


class Document(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    latest: Annotated[SnapshotRef | None, scoped(Public)] = None  # type: ignore[valid-type]
    history: Annotated[list[SnapshotRef], scoped(Public)] = []  # type: ignore[valid-type]
    by_id: Annotated[dict[UUID, SnapshotRef], scoped(Public)] = {}  # type: ignore[valid-type]


def test_projection_carrier_fields_register_embedded_edges() -> None:
    refs = Document.__prism__.refs
    assert set(refs.embedded) == {"latest", "history", "by_id"}
    latest = refs["latest"]
    assert latest.kind == "embedded"
    assert latest.target is Snapshot  # the canonical, not the projection
    assert latest.scope == SnapshotRef.__prism__.scope
    assert latest.shape is RefShape.SCALAR
    assert latest.optional


def test_embedded_shapes() -> None:
    assert Document.__prism__.refs["history"].shape is RefShape.COLLECTION
    by_id = Document.__prism__.refs["by_id"]
    assert by_id.shape is RefShape.KEYED_DICT
    assert by_id.key_type is UUID


def test_embedded_keyed_dict_key_is_not_validated() -> None:
    """Composition may be keyed by anything; only ref() keyed dicts validate."""

    class Notes(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        by_label: Annotated[dict[str, SnapshotRef], scoped(Public)] = {}  # type: ignore[valid-type]

    info = Notes.__prism__.refs["by_label"]  # resolves without RefResolutionError
    assert info.key_type is str


def test_embedded_edges_are_not_outgoing() -> None:
    assert "latest" not in Document.__prism__.refs.outgoing
    assert Snapshot in Document.__prism__.refs.targets()


def test_canonical_composition_registers_uniformly() -> None:
    class Address(ScopedModel):
        city: Annotated[str, scoped(Public)]

    class Shipment(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        destination: Annotated[Address | None, scoped(Public)] = None

    info = Shipment.__prism__.refs["destination"]
    assert info.kind == "embedded"
    assert info.target is Address
    assert info.scope is None  # canonical annotation: reshapes with the outer scope
    assert info.optional


def test_embedded_edges_survive_projection_and_walk() -> None:
    projected = Document.scope(Public)
    assert set(projected.__prism__.refs.embedded) == {"latest", "history", "by_id"}
    assert projected.__prism__.refs["history"].target is Snapshot
    edges = {
        (source.__name__, info.field_name)
        for source, info in Document.__prism__.refs.walk()
    }
    assert ("Document", "history") in edges


def test_carrier_keeps_fixed_shape_under_projection() -> None:
    """A projection-typed field does not reshape with the outer scope."""
    projected = Document.scope(Public)
    sid = uuid4()
    doc = projected(
        id=uuid4(),
        history=[{"id": sid, "taken_at": "now"}],
    )
    item = doc.history[0]  # type: ignore[attr-defined]
    assert type(item) is SnapshotRef
    assert "blob" not in type(item).model_fields


def test_ambiguous_annotations_register_nothing() -> None:
    class Other(ScopedModel):
        id: Annotated[UUID, scoped(Public)]

    class Mixed(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        either: Annotated[Snapshot | Other | None, scoped(Public)] = None

    assert "either" not in Mixed.__prism__.refs
