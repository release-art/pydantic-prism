"""Diagram export: scope / projection / relationship graphs to Mermaid/DOT/D2."""

from typing import Annotated
from uuid import UUID

import pytest

from pydantic_prism import (
    Diagram,
    Scope,
    ScopedModel,
    backref,
    projection_diagram,
    ref,
    scope_diagram,
    scoped,
)
from pydantic_prism._diagram import Edge, Node, _Ids


class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


class Update(Storage, partial=True): ...


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    order_ids: Annotated[
        list[UUID], backref("Order", via="customer_id"), scoped(Internal)
    ]


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
    draft: Annotated[str, scoped(Update)] = ""  # puts Update in Order.scopes()


# --- scope inheritance graph -----------------------------------------------


def test_scope_diagram_pulls_ancestors_and_marks_partial() -> None:
    diagram = scope_diagram(Update)  # Update + Storage + Internal + Public
    by_label = {n.label: n for n in diagram.nodes}
    assert set(by_label) == {"Update", "Storage", "Internal", "Public"}
    assert by_label["Update"].kind == "partial_scope"
    assert by_label["Public"].kind == "scope"
    # extends edges chain up to the root scope
    pairs = {(e.src, e.dst) for e in diagram.edges}
    ids = {n.label: n.id for n in diagram.nodes}
    assert (ids["Update"], ids["Storage"]) in pairs
    assert (ids["Internal"], ids["Public"]) in pairs


def test_scope_diagram_no_args_discovers_all() -> None:
    diagram = scope_diagram()
    labels = {n.label for n in diagram.nodes}
    assert {"Public", "Internal", "Storage", "Update"} <= labels
    assert diagram.to_mermaid()  # renders


def test_scope_diagram_mermaid_marks_partial() -> None:
    out = scope_diagram(Update).to_mermaid()
    assert "Update" in out
    assert ":::partial" in out
    assert "-->|extends|" in out


def test_scope_diagram_d2_partial_node_without_fields() -> None:
    # a partial scope is a partial node with no fields -> the d2 'elif style' path
    out = scope_diagram(Update).to_d2()
    assert "style.stroke-dash" in out
    assert "shape: class" not in out  # scopes have no fields


def test_scope_diagram_shared_ancestors_collected_once() -> None:
    # passing two scopes in one chain revisits a shared ancestor (Internal/Public)
    diagram = scope_diagram(Storage, Internal)
    labels = [n.label for n in diagram.nodes]
    assert labels.count("Public") == 1
    assert set(labels) == {"Storage", "Internal", "Public"}


# --- projection landscape ---------------------------------------------------


def test_projection_diagram_nodes_edges_and_fields() -> None:
    diagram = projection_diagram(Order)
    by_label = {n.label: n for n in diagram.nodes}
    assert by_label["Order"].kind == "model"
    assert set(by_label["Order"].fields) == {"id", "customer_id", "draft"}
    # one projection per scope in Order.scopes() = {Public, Update}
    assert by_label["OrderPublic"].kind == "projection"
    assert "draft" not in by_label["OrderPublic"].fields  # Public drops Update field
    assert by_label["OrderUpdate"].kind == "partial_projection"
    # edges labelled by scope
    labels = {e.label for e in diagram.edges}
    assert {"Public", "Update"} <= labels


# --- relationship graph -----------------------------------------------------


def test_ref_diagram_models_fields_and_kind_labels() -> None:
    diagram = Order.__refs__.diagram()
    by_label = {n.label: n for n in diagram.nodes}
    assert set(by_label) == {"Order", "Customer"}
    assert "customer_id" in by_label["Order"].fields
    edge_labels = {e.label for e in diagram.edges}
    assert "customer_id (ref)" in edge_labels


# --- renderers --------------------------------------------------------------


def test_dot_record_nodes_and_edges() -> None:
    out = Order.__refs__.diagram().to_dot()
    assert "digraph prism {" in out
    assert "rankdir=TB;" in out
    assert "shape=record" in out
    assert 'label="customer_id (ref)"' in out


def test_d2_class_shape_and_partial_style() -> None:
    out = projection_diagram(Order).to_d2()
    assert "direction: down" in out
    assert "shape: class" in out
    assert "style.stroke-dash" in out  # partial projection styled
    assert "-> OrderPublic: Public" in out


def test_as_dict_roundtrips_to_json() -> None:
    import json

    data = projection_diagram(Order).as_dict()
    assert data["direction"] == "TD"
    assert {"id", "label", "kind", "fields"} <= set(data["nodes"][0])
    assert {"src", "dst", "label"} <= set(data["edges"][0])
    json.dumps(data)  # serializable


def test_direction_lr_maps_per_format() -> None:
    diagram = scope_diagram(Internal, direction="LR")
    assert "graph LR" in diagram.to_mermaid()
    assert "rankdir=LR;" in diagram.to_dot()
    assert "direction: right" in diagram.to_d2()


@pytest.mark.parametrize("builder", [scope_diagram, projection_diagram])
def test_bad_direction_raises(builder: object) -> None:
    fn = builder  # scope_diagram(*scopes) / projection_diagram(model)
    with pytest.raises(ValueError, match="direction must be one of"):
        if fn is scope_diagram:
            scope_diagram(Internal, direction="sideways")
        else:
            projection_diagram(Order, direction="sideways")


def test_ref_diagram_bad_direction_raises() -> None:
    with pytest.raises(ValueError, match="direction must be one of"):
        Order.__refs__.diagram(direction="diagonal")


# --- IR edge cases: unlabelled edges, no-field & special-char nodes ---------


def test_unlabelled_edge_and_plain_nodes() -> None:
    diagram = Diagram(
        nodes=(Node("a", "A", "model"), Node("b", "B", "scope")),
        edges=(Edge("a", "b"),),
    )
    assert "    a --> b" in diagram.to_mermaid()
    assert "a -> b;" in diagram.to_dot()
    d2 = diagram.to_d2()
    assert "a -> b" in d2 and "a -> b:" not in d2  # no label


def test_label_escaping_across_formats() -> None:
    diagram = Diagram(
        nodes=(Node("x", 'La"bel', "model", ("a|b", "ok_field")),),
        edges=(),
    )
    assert "&quot;" in diagram.to_mermaid()  # mermaid entity-escapes quote
    dot = diagram.to_dot()
    assert "\\|" in dot  # record special char escaped
    d2 = diagram.to_d2()
    assert '"a|b"' in d2  # non-identifier field quoted
    assert "ok_field" in d2  # identifier field bare


def test_ids_sanitize_and_disambiguate() -> None:
    ids = _Ids()
    assert ids.make("Foo") == "Foo"
    assert ids.make("Foo") == "Foo_2"  # collision
    assert ids.make("9lives") == "_9lives"  # leading digit
    assert ids.make("") == "n"  # empty name -> fallback
    assert ids.make("a.b-c") == "a_b_c"  # non-word chars
