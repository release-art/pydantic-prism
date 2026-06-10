"""Export prism structure to graph formats (Mermaid, DOT, D2) + a JSON-able IR.

Three builders produce one backend-agnostic :class:`Diagram` IR:

- :func:`scope_diagram` — the ``Scope`` inheritance graph (partial scopes styled).
- :func:`projection_diagram` — a canonical model and the projections it
  generates (one per scope), with each projection's surviving fields.
- :meth:`RefGraph.diagram` — the cross-model relationship graph (``ref`` /
  ``backref`` / ``embedded`` edges), reachable from one model.

A ``Diagram`` renders to ``.to_mermaid()`` / ``.to_dot()`` / ``.to_d2()`` or
``.as_dict()`` (the raw IR, for JSON or any other tool). prism emits *text* only
— no Graphviz/mermaid/D2 dependency; pipe the output to those tools yourself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ._refs import RefGraph
    from ._scopes import Scope

__all__ = ["Diagram", "projection_diagram", "scope_diagram"]

# direction token -> (mermaid, dot rankdir, d2 direction)
_DIRECTIONS = {
    "TD": ("TD", "TB", "down"),
    "LR": ("LR", "LR", "right"),
}


@dataclass(frozen=True)
class NodeField:
    """One field on a model/projection node, with its metadata preserved.

    ``type`` is a display label off the annotation; ``description`` is the
    field's ``FieldInfo.description`` (from ``Field(description=...)``, an
    attribute docstring, or a round-7 scope schema). Descriptions are carried in
    the IR (and ``as_dict``) even when a visual format renders only ``name:
    type``.
    """

    name: str
    type: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Node:
    """A diagram node: a model, projection, or scope."""

    id: str
    label: str
    kind: str  # "model" | "projection" | "scope" (+ "partial_*")
    fields: tuple[NodeField, ...] = ()
    description: str | None = None  # class/projection docstring, or scope desc

    @property
    def partial(self) -> bool:
        return self.kind.startswith("partial")


@dataclass(frozen=True)
class Edge:
    """A directed diagram edge with an optional label."""

    src: str
    dst: str
    label: str = ""


@dataclass(frozen=True)
class Diagram:
    """A rendered-on-demand directed graph of prism structure.

    Build one with :func:`scope_diagram`, :func:`projection_diagram`, or
    :meth:`RefGraph.diagram`, then render with ``to_mermaid`` / ``to_dot`` /
    ``to_d2`` / ``as_dict``.
    """

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    direction: str = "TD"

    def as_dict(self) -> dict[str, Any]:
        """The raw IR as JSON-serializable data (lossless: types + descriptions)."""
        return {
            "direction": self.direction,
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "kind": n.kind,
                    "description": n.description,
                    "fields": [
                        {"name": f.name, "type": f.type, "description": f.description}
                        for f in n.fields
                    ],
                }
                for n in self.nodes
            ],
            "edges": [
                {"src": e.src, "dst": e.dst, "label": e.label} for e in self.edges
            ],
        }

    def to_mermaid(self) -> str:
        """Render as a Mermaid flowchart (``graph TD``)."""
        mermaid_dir = _DIRECTIONS[self.direction][0]
        lines = [f"graph {mermaid_dir}"]
        for node in self.nodes:
            rows = [node.label, *(_field_row(f) for f in node.fields)]
            text = "<br/>".join(_mermaid(r) for r in rows)
            suffix = ":::partial" if node.partial else ""
            lines.append(f'    {node.id}["{text}"]{suffix}')
        for edge in self.edges:
            if edge.label:
                # quote the label: GitHub's Mermaid parser breaks on bare
                # parentheses/specials in an edge label (e.g. "id (ref)")
                lines.append(f'    {edge.src} -->|"{_mermaid(edge.label)}"| {edge.dst}')
            else:
                lines.append(f"    {edge.src} --> {edge.dst}")
        lines.append("    classDef partial stroke-dasharray: 5 5;")
        return "\n".join(lines) + "\n"

    def to_dot(self) -> str:
        """Render as Graphviz DOT (``digraph``)."""
        rankdir = _DIRECTIONS[self.direction][1]
        lines = ["digraph prism {", f"    rankdir={rankdir};", "    node [shape=box];"]
        for node in self.nodes:
            attrs: list[str] = []
            if node.fields:
                rows = "|".join(_dot_record(_field_row(f)) for f in node.fields)
                attrs.append("shape=record")
                attrs.append(f'label="{{{_dot_record(node.label)}|{rows}}}"')
            else:
                attrs.append(f'label="{_dot(node.label)}"')
            if node.partial:
                attrs.append('style="dashed"')
            if node.description:
                attrs.append(f'tooltip="{_dot(node.description)}"')
            lines.append(f"    {node.id} [{','.join(attrs)}];")
        for edge in self.edges:
            label = f' [label="{_dot(edge.label)}"]' if edge.label else ""
            lines.append(f"    {edge.src} -> {edge.dst}{label};")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def to_d2(self) -> str:
        """Render as D2 (terrastruct)."""
        d2_dir = _DIRECTIONS[self.direction][2]
        lines = [f"direction: {d2_dir}"]
        for node in self.nodes:
            style = "\n  style.stroke-dash: 3" if node.partial else ""
            if node.fields:
                rows = "\n".join(f"  {_d2_row(f)}" for f in node.fields)
                body = f"  shape: class\n{rows}{style}"
                lines.append(f'{node.id}: "{_d2(node.label)}" {{\n{body}\n}}')
            elif style:
                lines.append(f'{node.id}: "{_d2(node.label)}" {{{style}\n}}')
            else:
                lines.append(f'{node.id}: "{_d2(node.label)}"')
        for edge in self.edges:
            label = f": {_d2(edge.label)}" if edge.label else ""
            lines.append(f"{edge.src} -> {edge.dst}{label}")
        return "\n".join(lines) + "\n"


# --- label escaping --------------------------------------------------------


def _mermaid(text: str) -> str:
    return text.replace('"', "&quot;")


def _dot(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _dot_record(text: str) -> str:
    # record labels also treat { } | < > as structure
    out = _dot(text)
    for ch in "{}|<>":
        out = out.replace(ch, "\\" + ch)
    return out


def _d2(text: str) -> str:
    return text.replace('"', "'")


def _field_row(node_field: NodeField) -> str:
    """The visible row for a field: ``name`` or ``name: type``."""
    if node_field.type:
        return f"{node_field.name}: {node_field.type}"
    return node_field.name


def _d2_row(node_field: NodeField) -> str:
    """A D2 class row: ``name`` or ``name: type``, name quoted if non-trivial."""
    raw = node_field.name
    name = raw if raw.isidentifier() else f'"{_d2(raw)}"'
    if node_field.type:
        return f"{name}: {_d2(node_field.type)}"
    return name


def _type_label(annotation: Any) -> str:
    """A concise display label for a field's annotation (module paths stripped)."""
    if annotation is None:
        return "None"
    if isinstance(annotation, type):
        return annotation.__name__
    return re.sub(r"\b[\w.]+\.(\w+)", r"\1", str(annotation))


# --- id allocation ---------------------------------------------------------


def _empty_str_set() -> set[str]:
    return set()


@dataclass
class _Ids:
    """Allocates unique, format-safe node ids from arbitrary names."""

    _used: set[str] = field(default_factory=_empty_str_set)

    def make(self, name: str) -> str:
        base = re.sub(r"\W", "_", name) or "n"
        if base[0].isdigit():
            base = "_" + base
        candidate, suffix = base, 1
        while candidate in self._used:
            suffix += 1
            candidate = f"{base}_{suffix}"
        self._used.add(candidate)
        return candidate


# --- builders --------------------------------------------------------------


def _node_fields(model: type[Any]) -> tuple[NodeField, ...]:
    """Structured fields (name, type label, description) of a model/projection."""
    return tuple(
        NodeField(name, _type_label(info.annotation), info.description)
        for name, info in model.model_fields.items()
    )


def _scope_description(scope: type[Any]) -> str | None:
    """A scope's round-7 model-schema description, if it declares one."""
    raw = vars(scope).get("__prism_model_schema__")
    if isinstance(raw, dict):
        description = cast("dict[str, Any]", raw).get("description")
        if isinstance(description, str):
            return description
    return None


def _all_scope_subclasses(root: type[Scope]) -> set[type[Scope]]:
    found: set[type[Scope]] = set()
    stack = list(root.__subclasses__())
    while stack:
        scope = stack.pop()
        if scope not in found:
            found.add(scope)
            stack.extend(scope.__subclasses__())
    return found


def _scope_parents(scope: type[Scope], root: type[Scope]) -> list[type[Scope]]:
    return [
        base for base in scope.__bases__ if issubclass(base, root) and base is not root
    ]


def _collect_with_ancestors(
    scope: type[Scope], root: type[Scope], acc: set[type[Scope]]
) -> None:
    if scope in acc:
        return
    acc.add(scope)
    for parent in _scope_parents(scope, root):
        _collect_with_ancestors(parent, root, acc)


def scope_diagram(*scopes: type[Scope], direction: str = "TD") -> Diagram:
    """The scope-inheritance graph for ``scopes`` (and their ancestors).

    With no arguments, every declared ``Scope`` subclass is included. Edges read
    ``Derived --extends--> Base``; partial scopes are styled. For a model's
    scopes, pass ``scope_diagram(*Model.scopes())``.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_DIRECTIONS)}, got {direction!r}"
        )
    from ._scopes import Scope

    if scopes:
        collected: set[type[Scope]] = set()
        for scope in scopes:
            _collect_with_ancestors(scope, Scope, collected)
    else:
        collected = _all_scope_subclasses(Scope)

    ordered = sorted(collected, key=lambda s: s.__name__)
    ids = _Ids()
    node_id = {scope: ids.make(scope.__name__) for scope in ordered}
    nodes = tuple(
        Node(
            id=node_id[scope],
            label=scope.__name__,
            kind="partial_scope" if scope.__prism_partial__ else "scope",
            description=_scope_description(scope),
        )
        for scope in ordered
    )
    edges = tuple(
        Edge(node_id[scope], node_id[parent], "extends")
        for scope in ordered
        for parent in _scope_parents(scope, Scope)
        if parent in node_id
    )
    return Diagram(nodes, edges, direction)


def projection_diagram(model: type[Any], *, direction: str = "TD") -> Diagram:
    """A canonical model and the projections it generates, with their fields.

    One projection node per scope in ``model.scopes()``; edges are labelled with
    the scope. Partial projections are styled.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_DIRECTIONS)}, got {direction!r}"
        )
    ids = _Ids()
    cid = ids.make(model.__name__)
    nodes = [Node(cid, model.__name__, "model", _node_fields(model), model.__doc__)]
    edges: list[Edge] = []
    for scope in sorted(model.scopes(), key=lambda s: s.__name__):
        proj = model.scope(scope)
        kind = (
            "partial_projection" if proj.__prism_scope__.is_partial() else "projection"
        )
        pid = ids.make(proj.__name__)
        nodes.append(Node(pid, proj.__name__, kind, _node_fields(proj), proj.__doc__))
        edges.append(Edge(cid, pid, scope.__name__))
    return Diagram(tuple(nodes), tuple(edges), direction)


def ref_diagram(graph: RefGraph, *, direction: str = "TD") -> Diagram:
    """The cross-model relationship graph reachable from ``graph``'s owner."""
    if direction not in _DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_DIRECTIONS)}, got {direction!r}"
        )
    walked = list(graph.walk())
    models = {graph.owner}
    for source, info in walked:
        models.add(source)
        models.add(info.target)
    ids = _Ids()
    node_id = {
        m: ids.make(m.__name__) for m in sorted(models, key=lambda c: c.__name__)
    }
    nodes = tuple(
        Node(node_id[m], m.__name__, "model", _node_fields(m), m.__doc__)
        for m in sorted(models, key=lambda c: c.__name__)
    )
    edges = tuple(
        Edge(node_id[source], node_id[info.target], f"{info.field_name} ({info.kind})")
        for source, info in walked
    )
    return Diagram(nodes, edges, direction)
