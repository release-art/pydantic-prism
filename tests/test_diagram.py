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
from pydantic_prism.diagram import (
    Edge,
    Node,
    NodeField,
    _class_member,
    _Ids,
    _type_label,
)


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


def test_scope_diagram_mermaid_is_classdiagram_with_inheritance() -> None:
    out = scope_diagram(Update).to_mermaid()
    assert out.startswith("classDiagram")
    assert "class Update {\n        <<partial>>" in out  # partial stereotype
    assert "Storage <|-- Update" in out  # UML inheritance: parent <|-- child
    assert "-->" not in out  # scope edges are inheritance, not association


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
    assert {f.name for f in by_label["Order"].fields} == {"id", "customer_id", "draft"}
    # one projection per scope in Order.scopes() = {Public, Update}
    assert by_label["OrderPublic"].kind == "projection"
    public_fields = {f.name for f in by_label["OrderPublic"].fields}
    assert "draft" not in public_fields  # Public drops the Update-only field
    assert by_label["OrderUpdate"].kind == "partial_projection"
    # edges labelled by scope
    labels = {e.label for e in diagram.edges}
    assert {"Public", "Update"} <= labels


# --- relationship graph -----------------------------------------------------


def test_ref_diagram_models_fields_and_kind_labels() -> None:
    diagram = Order.__refs__.diagram()
    by_label = {n.label: n for n in diagram.nodes}
    assert set(by_label) == {"Order", "Customer"}
    assert "customer_id" in {f.name for f in by_label["Order"].fields}
    edge_labels = {e.label for e in diagram.edges}
    assert "customer_id (ref)" in edge_labels


# --- renderers --------------------------------------------------------------


def test_mermaid_classdiagram_associations_strip_parens() -> None:
    # ref edges become classDiagram associations; GitHub's Mermaid breaks on
    # parens in a relation label, so "(ref)" is stripped to "ref".
    out = Order.__refs__.diagram().to_mermaid()
    assert out.startswith("classDiagram")
    assert "Order --> Customer : customer_id ref" in out
    assert "(ref)" not in out  # parentheses never reach the label


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
    assert "direction LR" in diagram.to_mermaid()  # classDiagram direction
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
    node = Node("x", 'La"bel', "model", (NodeField("a|b"), NodeField("ok_field")))
    diagram = Diagram(nodes=(node,), edges=())
    # mermaid classDiagram renders the (identifier) node id, not the raw label
    mermaid = diagram.to_mermaid()
    assert "class x" in mermaid
    assert 'La"bel' not in mermaid
    dot = diagram.to_dot()
    assert "\\|" in dot  # record special char escaped
    d2 = diagram.to_d2()
    assert '"a|b"' in d2  # non-identifier field quoted
    assert "ok_field" in d2  # identifier field bare


def test_fields_carry_type_and_description() -> None:
    from pydantic import Field

    class Doc(ScopedModel):
        """A documented model."""

        id: Annotated[UUID, scoped(Public)]
        note: Annotated[str, Field(description="A note."), scoped(Public)]
        tags: Annotated[list[str], scoped(Public)] = []

    diagram = projection_diagram(Doc)
    canonical = next(n for n in diagram.nodes if n.label == "Doc")
    by_name = {f.name: f for f in canonical.fields}
    assert by_name["id"].type == "UUID"
    assert by_name["tags"].type == "list[str]"  # module paths stripped
    assert by_name["note"].description == "A note."
    assert by_name["id"].description is None
    # node-level description = the model docstring
    assert canonical.description == "A documented model."
    # projection nodes carry their __doc__
    proj_node = next(n for n in diagram.nodes if n.label == "DocPublic")
    assert proj_node.description and "Projection of" in proj_node.description


def test_field_rows_render_name_and_type() -> None:
    diagram = projection_diagram(Order)
    assert "+UUID customer_id" in diagram.to_mermaid()  # classDiagram member
    assert "customer_id: UUID" in diagram.to_dot()  # record row
    assert "customer_id: UUID" in diagram.to_d2()  # d2 class row


def test_descriptions_in_as_dict_and_dot_tooltip() -> None:
    class Doc(ScopedModel):
        """Doc model."""

        x: Annotated[str, scoped(Public, description="the x field")]

    data = projection_diagram(Doc).as_dict()
    canonical = next(n for n in data["nodes"] if n["label"] == "Doc")
    assert canonical["description"] == "Doc model."  # docstring on the node
    # the round-7 per-scope description shows on the projection node
    projection = next(n for n in data["nodes"] if n["label"] == "DocPublic")
    xfield = next(f for f in projection["fields"] if f["name"] == "x")
    assert xfield["description"] == "the x field"
    assert xfield["type"] == "str"
    # Node.description surfaces as a DOT tooltip
    assert 'tooltip="Doc model."' in projection_diagram(Doc).to_dot()


def test_scope_node_carries_round7_description() -> None:
    class Described(Scope, description="A described scope"): ...

    node = next(n for n in scope_diagram(Described).nodes if n.label == "Described")
    assert node.description == "A described scope"


def test_class_member_rendering() -> None:
    assert _class_member(NodeField("id", "UUID")) == "UUID id"  # type name
    assert _class_member(NodeField("tags", "list[str]")) == "list~str~ tags"  # generic
    assert _class_member(NodeField("x")) == "x"  # no type -> name only
    # union/optional contains `|`, which breaks classDiagram members -> name only
    assert _class_member(NodeField("maybe", "str | None")) == "maybe"


def test_type_label() -> None:
    assert _type_label(None) == "None"
    assert _type_label(str) == "str"  # plain type -> __name__
    assert _type_label(list[str]) == "list[str]"
    assert _type_label(dict[UUID, str]) == "dict[UUID, str]"  # module paths stripped


def test_ids_sanitize_and_disambiguate() -> None:
    ids = _Ids()
    assert ids.make("Foo") == "Foo"
    assert ids.make("Foo") == "Foo_2"  # collision
    assert ids.make("9lives") == "_9lives"  # leading digit
    assert ids.make("") == "n"  # empty name -> fallback
    assert ids.make("a.b-c") == "a_b_c"  # non-word chars
