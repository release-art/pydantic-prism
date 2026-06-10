"""Data-flow governance: trace where classified data flows across the ref graph.

:func:`build_flow_report` walks the forward ``ref`` / ``embedded`` edges
reachable from a root model (BFS, cycle-safe) and reports the classified fields
of every model personal data can reach. The result, a :class:`FlowReport`,
renders to JSON (``as_dict``) for a compliance artifact or to a Mermaid diagram
(``to_mermaid``) for review — the same two-format story as :mod:`._diagram`,
whose IR the Mermaid path reuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .diagram import Diagram
    from .model import ScopedModel
    from .scopes import Classification

__all__ = [
    "ClassifiedField",
    "FlowEdge",
    "FlowNode",
    "FlowReport",
    "build_flow_report",
]


@dataclass(frozen=True)
class ClassifiedField:
    """One classified field: its name and the classifications it carries."""

    field_name: str
    classifications: frozenset[type[Classification]]

    @property
    def labels(self) -> tuple[str, ...]:
        """Classification class names, sorted — the display/serialization form."""
        return tuple(sorted(c.__name__ for c in self.classifications))


@dataclass(frozen=True)
class FlowNode:
    """A reached model that holds classified data, with its classified fields."""

    model: type[ScopedModel]
    fields: tuple[ClassifiedField, ...]


@dataclass(frozen=True)
class FlowEdge:
    """One forward edge on the path classified data travels (``ref``/``embedded``)."""

    source: type[ScopedModel]
    field_name: str
    target: type[ScopedModel]
    kind: str


@dataclass(frozen=True)
class FlowReport:
    """Where classified data reachable from ``root`` lives, and how it is reached.

    ``nodes`` are the reachable models carrying classified fields (``root``
    first, then BFS discovery order); ``edges`` are the forward edges of the
    walk, so the path to every classified model is visible. Truthy iff any
    classified data is reachable.
    """

    root: type[ScopedModel]
    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]

    def __bool__(self) -> bool:
        return bool(self.nodes)

    def as_dict(self) -> dict[str, Any]:
        """The report as JSON-serializable data — the compliance artifact."""
        return {
            "root": self.root.__name__,
            "nodes": [
                {
                    "model": node.model.__name__,
                    "fields": [
                        {"field": f.field_name, "classifications": list(f.labels)}
                        for f in node.fields
                    ],
                }
                for node in self.nodes
            ],
            "edges": [
                {
                    "source": edge.source.__name__,
                    "field": edge.field_name,
                    "target": edge.target.__name__,
                    "kind": edge.kind,
                }
                for edge in self.edges
            ],
        }

    def to_mermaid(self, *, direction: str = "TD") -> str:
        """Render as a Mermaid ``classDiagram`` of the reachable graph.

        Every reachable model is a node; classified models list their classified
        fields (annotated with the classifications), and edges are labelled with
        the referencing field. Reuses the :class:`._diagram.Diagram` renderer.
        """
        return self._diagram(direction=direction).to_mermaid()

    def _diagram(self, *, direction: str) -> Diagram:
        from .diagram import Diagram, Edge, Node, NodeField

        classified = {node.model: node for node in self.nodes}
        order: list[type[ScopedModel]] = [self.root]
        seen: set[type[ScopedModel]] = {self.root}
        for edge in self.edges:
            for model in (edge.source, edge.target):
                if model not in seen:
                    seen.add(model)
                    order.append(model)
        nodes = tuple(
            Node(
                id=model.__name__,
                label=model.__name__,
                kind="model",
                fields=tuple(
                    NodeField(name=f.field_name, type="+".join(f.labels))
                    for f in classified[model].fields
                )
                if model in classified
                else (),
            )
            for model in order
        )
        edges = tuple(
            Edge(
                src=edge.source.__name__,
                dst=edge.target.__name__,
                label=edge.field_name,
            )
            for edge in self.edges
        )
        return Diagram(nodes, edges, direction)


def build_flow_report(root: type[ScopedModel]) -> FlowReport:
    """Trace classified data reachable from ``root`` across its ref graph.

    Walks forward ``ref`` / ``embedded`` edges breadth-first (cycle-safe) and
    collects the classified fields of every model reached. The entry point for
    :meth:`ScopedModel.classified_flow`.
    """
    edges: list[FlowEdge] = []
    order: list[type[ScopedModel]] = [root]
    seen: set[type[ScopedModel]] = {root}
    for source, info in root.__refs__.walk():
        edges.append(FlowEdge(source, info.field_name, info.target, info.kind))
        for model in (source, info.target):
            if model not in seen:
                seen.add(model)
                order.append(model)
    nodes: list[FlowNode] = []
    for model in order:
        fields = model.classified_fields()
        if fields:
            nodes.append(
                FlowNode(
                    model,
                    tuple(ClassifiedField(name, tags) for name, tags in fields.items()),
                )
            )
    return FlowReport(root, tuple(nodes), tuple(edges))
