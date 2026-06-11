"""Data-flow governance: trace dimensional data across the ref graph.

:func:`build_flow_report` walks the forward ``ref`` / ``embedded`` edges
reachable from a root model (BFS, cycle-safe) and reports, for every reachable
model, each tagged field's scopes **grouped by axis** — the structural view.
PII, direction, visibility, and any user-defined dimension surface alike,
inferred from the inheritance forest (:meth:`~pydantic_prism.ScopedModel.dimensions`)
with no dependence on the shipped axis bases. The result, a :class:`FlowReport`,
renders to JSON (``as_dict``) for a compliance artifact or to a Mermaid diagram
(``to_mermaid``) for review — the same two-format story as :mod:`.diagram`, whose
IR (and per-field axis badges) the Mermaid path reuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._internal.scopes import dimension_root

if TYPE_CHECKING:
    from ._internal.model import ScopedModel
    from ._internal.scopes import Scope
    from .diagram import Diagram

__all__ = [
    "FlowEdge",
    "FlowField",
    "FlowNode",
    "FlowReport",
    "build_flow_report",
]


@dataclass(frozen=True, slots=True)
class FlowField:
    """One tagged field on a reachable model: its name and every scope it carries.

    Reports *all* the field's scope atoms across *every* axis — visibility,
    classification (PII), direction, and any user dimension — not just one. Group
    them by axis with :attr:`by_dimension`; PII appears as the slice rooted at
    your ``Classification`` subclass, like any other dimension.
    """

    field_name: str
    scopes: frozenset[type[Scope]]

    @property
    def labels(self) -> tuple[str, ...]:
        """Every scope's class name, sorted — the flat display form."""
        return tuple(sorted(scope.__name__ for scope in self.scopes))

    @property
    def by_dimension(self) -> dict[str, tuple[str, ...]]:
        """The field's scopes grouped by axis: ``{root_name: (scope_names,)}``."""
        grouped: dict[type[Scope], list[str]] = {}
        for scope in self.scopes:
            grouped.setdefault(dimension_root(scope), []).append(scope.__name__)
        return {
            root.__name__: tuple(sorted(names))
            for root, names in sorted(grouped.items(), key=lambda kv: kv[0].__name__)
        }


@dataclass(frozen=True, slots=True)
class FlowNode:
    """A reached model that holds tagged data, with its tagged fields."""

    model: type[ScopedModel]
    fields: tuple[FlowField, ...]


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """One forward edge on the path data travels (``ref`` / ``embedded``)."""

    source: type[ScopedModel]
    field_name: str
    target: type[ScopedModel]
    kind: str


@dataclass(frozen=True, slots=True)
class FlowReport:
    """Where dimensional data reachable from ``root`` lives, and how it is reached.

    ``nodes`` are the reachable models carrying tagged fields (``root`` first,
    then BFS discovery order); ``edges`` are the forward edges of the walk, so
    the path to every model is visible. Truthy iff any tagged data is reachable.
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
                        {
                            "field": f.field_name,
                            "dimensions": {
                                axis: list(names)
                                for axis, names in f.by_dimension.items()
                            },
                        }
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

        Every reachable model is a node showing its fields with per-axis badges
        (``email [Pii]``); edges are labelled with the referencing field. Reuses
        the :class:`.diagram.Diagram` renderer and its structural badges.
        """
        return self._diagram(direction=direction).to_mermaid()

    def _diagram(self, *, direction: str) -> Diagram:
        from .diagram import (
            Diagram,
            Edge,
            Node,
            _node_fields,  # pyright: ignore[reportPrivateUsage] — intra-package
        )

        order: list[type[ScopedModel]] = [self.root]
        seen: set[type[ScopedModel]] = {self.root}
        for edge in self.edges:
            for model in (edge.source, edge.target):
                if model not in seen:
                    seen.add(model)
                    order.append(model)
        nodes = tuple(
            Node(model.__name__, model.__name__, "model", _node_fields(model))
            for model in order
        )
        edges = tuple(
            Edge(edge.source.__name__, edge.target.__name__, edge.field_name)
            for edge in self.edges
        )
        return Diagram(nodes, edges, direction)


def build_flow_report(root: type[ScopedModel]) -> FlowReport:
    """Trace dimensional data reachable from ``root`` across its ref graph.

    Walks forward ``ref`` / ``embedded`` edges breadth-first (cycle-safe) and
    reports every **tagged** field of every model reached, with its scopes across
    all axes. The entry point for :meth:`ScopedModel.data_flow`.
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
        tagged = tuple(
            FlowField(name, frozenset(expr.atoms()))
            for name, expr in model.__field_scopes__.items()
        )
        if tagged:
            nodes.append(FlowNode(model, tagged))
    return FlowReport(root, tuple(nodes), tuple(edges))
