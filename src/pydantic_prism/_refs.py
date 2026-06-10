"""Introspection surface for model relationships: RefInfo and RefGraph."""

from __future__ import annotations

import sys
import types
from collections import deque
from collections.abc import Collection, Iterator, Mapping, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Any, Literal, Union, cast, get_args, get_origin

from ._markers import BackRef, Ref
from .errors import RefResolutionError

if TYPE_CHECKING:
    from ._diagram import Diagram
    from ._model import ScopedModel
    from ._scopes import ScopeExpr

__all__ = [
    "BackRefInfo",
    "EmbeddedRefInfo",
    "IdRefInfo",
    "RefGraph",
    "RefInfo",
    "RefShape",
]

RefKind = Literal["ref", "backref", "embedded"]


@unique
class RefShape(StrEnum):
    """Storage shape of a relationship field, inferred from its annotation.

    - ``SCALAR`` — one value: ``UUID``, ``Snapshot``
    - ``COLLECTION`` — a sequence/set of values: ``list[UUID]``, ``set[UUID]``
    - ``KEYED_DICT`` — a mapping keyed by the related id:
      ``dict[UUID, Highlight]`` (the dict key IS the foreign id)
    """

    SCALAR = "scalar"
    COLLECTION = "collection"
    KEYED_DICT = "keyed_dict"


@dataclass(frozen=True)
class Embedded:
    """Internal pseudo-marker for auto-detected embedded-model edges.

    Created by marker collection — never written by users. ``scope`` is the
    carrier projection's scope expression, or ``None`` when the embedded
    annotation is a canonical ScopedModel (composition that reshapes with the
    outer projection).
    """

    target: type[ScopedModel]
    scope: ScopeExpr | None
    target_field: str = "id"


@dataclass(frozen=True)
class RawEdge:
    """One unresolved relationship edge as collected from a field."""

    marker: Ref | BackRef | Embedded
    shape: RefShape
    optional: bool
    key_type: Any = None


@dataclass(frozen=True, kw_only=True)
class RefInfo:
    """One resolved relationship edge — the base of the three edge kinds.

    ``__refs__[name]`` is typed as this base; the concrete object is one of
    :class:`IdRefInfo` (``kind="ref"``), :class:`BackRefInfo` (``kind="backref"``,
    adds ``via``) or :class:`EmbeddedRefInfo` (``kind="embedded"``, adds
    ``scope``). Narrow with ``isinstance`` / ``match info.kind`` — or use the
    kind-typed accessors :attr:`RefGraph.outgoing` / ``.incoming`` / ``.embedded``,
    which return the precise subtype.

    Attributes:
        field_name: Name of the field carrying the edge on the owning model.
        target: The referenced ScopedModel class (canonical, never a projection).
        target_field: Field on ``target`` the stored ids correspond to.
        shape: Storage shape (:class:`RefShape`): scalar, collection, or
            keyed dict (where the dict key is the foreign id).
        optional: True when the annotation admits ``None``.
        kind: ``"ref"``, ``"backref"`` or ``"embedded"`` — the discriminant.
        key_type: For keyed-dict shapes, the dict key type (shape-driven, so it
            lives on the base, not a kind variant); ``None`` otherwise.
    """

    field_name: str
    target: type[ScopedModel]
    target_field: str
    shape: RefShape
    optional: bool
    kind: RefKind
    key_type: Any = None

    @property
    def many(self) -> bool:
        """True when the edge holds more than one value (compat property)."""
        return self.shape is not RefShape.SCALAR


@dataclass(frozen=True, kw_only=True)
class IdRefInfo(RefInfo):
    """A forward, id-valued reference edge (``kind="ref"``)."""


@dataclass(frozen=True, kw_only=True)
class BackRefInfo(RefInfo):
    """A declared reverse-reference edge (``kind="backref"``).

    ``via`` names the field on ``target`` holding the forward ``ref`` back here.
    """

    via: str


@dataclass(frozen=True, kw_only=True)
class EmbeddedRefInfo(RefInfo):
    """An embedded-model edge: a carrier projection or composition.

    ``kind="embedded"``. ``scope`` is the embedded projection's scope
    expression, or ``None`` when the
    embedded annotation is a canonical ScopedModel (composition that reshapes
    with the outer projection).
    """

    scope: ScopeExpr | None = None


def shape_of(annotation: Any) -> tuple[RefShape, bool, Any]:
    """Infer ``(shape, optional, key_type)`` from a field annotation."""
    ann = annotation
    while hasattr(ann, "__metadata__"):
        ann = get_args(ann)[0]
    origin = get_origin(ann)
    if origin in (Union, types.UnionType):
        args = get_args(ann)
        optional = type(None) in args
        # a union always keeps >= 1 non-None member (X | X collapses to X)
        rest = [arg for arg in args if arg is not type(None)]
        shapes = [shape_of(arg) for arg in rest]
        first_shape, _, first_key = shapes[0]
        # a non-scalar shape only when every union member agrees on it
        if all(s == (first_shape, False, first_key) for s in shapes):
            return first_shape, optional, first_key
        return RefShape.SCALAR, optional, None
    if isinstance(origin, type) and issubclass(origin, Mapping):
        args = get_args(ann)
        key_type = args[0] if len(args) == 2 else None
        return RefShape.KEYED_DICT, False, key_type
    if isinstance(origin, type) and issubclass(
        origin, (list, set, frozenset, tuple, Sequence, Set)
    ):
        return RefShape.COLLECTION, False, None
    return RefShape.SCALAR, False, None


class RefGraph(Mapping[str, RefInfo]):
    """The relationship graph of one model: a mapping of field name → RefInfo.

    Targets resolve lazily on access (string forward references are looked up
    in the owning model's module), so circular model graphs work regardless of
    definition order. Resolution failures raise :class:`RefResolutionError`.
    """

    def __init__(
        self,
        owner: type[Any],
        entries: Mapping[str, RawEdge],
    ) -> None:
        self._owner = owner
        self._raw = dict(entries)
        self._resolved: dict[str, RefInfo] = {}

    @property
    def owner(self) -> type[Any]:
        """The canonical model class these relationships belong to."""
        return self._owner

    def __getitem__(self, field_name: str) -> RefInfo:
        if field_name not in self._resolved:
            self._resolved[field_name] = self._resolve(field_name)
        return self._resolved[field_name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._raw)

    def __len__(self) -> int:
        return len(self._raw)

    def __repr__(self) -> str:
        edges = ", ".join(
            f"{name}->{m.target if isinstance(m.target, str) else m.target.__name__}"
            for name, m in ((n, e.marker) for n, e in self._raw.items())
        )
        return f"RefGraph({self._owner.__name__}: {edges or 'no refs'})"

    @property
    def outgoing(self) -> dict[str, IdRefInfo]:
        """Forward ``ref`` edges only (id-valued)."""
        return cast(
            "dict[str, IdRefInfo]",
            {n: self[n] for n, e in self._raw.items() if isinstance(e.marker, Ref)},
        )

    @property
    def incoming(self) -> dict[str, BackRefInfo]:
        """Declared ``backref`` edges only."""
        return cast(
            "dict[str, BackRefInfo]",
            {n: self[n] for n, e in self._raw.items() if isinstance(e.marker, BackRef)},
        )

    @property
    def embedded(self) -> dict[str, EmbeddedRefInfo]:
        """Auto-detected embedded-model edges only (carrier records, composition)."""
        edges = {
            n: self[n] for n, e in self._raw.items() if isinstance(e.marker, Embedded)
        }
        return cast("dict[str, EmbeddedRefInfo]", edges)

    def targets(self) -> set[type[ScopedModel]]:
        """Every model referenced by this one (forward, embedded, or reverse)."""
        return {info.target for info in self.values()}

    def walk(self) -> Iterator[tuple[type[Any], RefInfo]]:
        """Breadth-first traversal of forward edges reachable from the owner.

        Forward means ``ref`` and ``embedded`` edges. Yields
        ``(source_model, info)`` pairs; ``info.target`` is the edge's
        destination. Each model is expanded once, so cycles terminate.
        """
        seen: set[type[Any]] = {self._owner}
        queue: deque[RefGraph] = deque([self])
        while queue:
            graph = queue.popleft()
            forward = {**graph.outgoing, **graph.embedded}
            for info in forward.values():
                yield graph.owner, info
                if info.target not in seen:
                    seen.add(info.target)
                    target_graph = getattr(info.target, "__refs__", None)
                    if isinstance(target_graph, RefGraph):
                        queue.append(target_graph)

    def diagram(self, *, direction: str = "TD") -> Diagram:
        """The cross-model relationship graph as a :class:`Diagram`.

        Renders with ``.to_mermaid()`` / ``.to_dot()`` / ``.to_d2()`` /
        ``.as_dict()``. Covers the ``ref``/``backref``/``embedded`` edges
        reachable from this model (the same span as :meth:`walk`).
        """
        from ._diagram import ref_diagram

        return ref_diagram(self, direction=direction)

    def _reset(self, entries: Mapping[str, RawEdge]) -> None:
        """Replace the raw edges in place (after a model rebuild), keeping
        graph objects already held by user code current."""
        self._raw = dict(entries)
        self._resolved.clear()

    def filtered(self, field_names: Collection[str]) -> RefGraph:
        """A sub-graph restricted to ``field_names`` (used by projections)."""
        graph = RefGraph(
            self._owner,
            {name: raw for name, raw in self._raw.items() if name in field_names},
        )
        graph._resolved = {
            name: info for name, info in self._resolved.items() if name in field_names
        }
        return graph

    def _resolve(self, field_name: str) -> RefInfo:
        from ._model import ScopedModel

        edge = self._raw[field_name]
        marker = edge.marker
        target = marker.target
        if isinstance(target, str):
            if "<locals>" in self._owner.__qualname__:
                raise RefResolutionError(
                    f"{self._owner.__name__}.{field_name}: string target {target!r} "
                    f"cannot be resolved for a model defined inside a function; "
                    f"pass the class object instead"
                )
            module = sys.modules.get(self._owner.__module__)
            candidate = getattr(module, target, None)
            if not (isinstance(candidate, type) and issubclass(candidate, ScopedModel)):
                raise RefResolutionError(
                    f"{self._owner.__name__}.{field_name}: cannot resolve "
                    f"{target!r} to a ScopedModel in module "
                    f"{self._owner.__module__!r}"
                )
            target = candidate
        common: dict[str, Any] = {
            "field_name": field_name,
            "target": target,
            "target_field": marker.target_field,
            "shape": edge.shape,
            "optional": edge.optional,
            "key_type": edge.key_type,
        }
        if isinstance(marker, BackRef):
            self._check_backref(field_name, target, marker.via)
            return BackRefInfo(kind="backref", via=marker.via, **common)
        if isinstance(marker, Embedded):
            return EmbeddedRefInfo(kind="embedded", scope=marker.scope, **common)
        if edge.shape is RefShape.KEYED_DICT:
            self._check_key_type(field_name, target, marker.target_field, edge.key_type)
        return IdRefInfo(kind="ref", **common)

    def _check_key_type(
        self,
        field_name: str,
        target: type[ScopedModel],
        target_field: str,
        key_type: Any,
    ) -> None:
        """A keyed-dict ``ref()``'s dict key type must match the target id field.

        Only explicit ``ref()`` edges are checked: embedded composition may be
        keyed by anything (``dict[str, Self]`` is structure, not identity).
        """
        prefix = (
            f"{self._owner.__name__}.{field_name}: keyed-dict ref to {target.__name__}"
        )
        info = target.model_fields.get(target_field)
        if info is None:
            raise RefResolutionError(
                f"{prefix} — {target.__name__} has no field named {target_field!r}"
            )
        if key_type is not None and key_type != info.annotation:
            raise RefResolutionError(
                f"{prefix} — dict key type {key_type!r} does not match "
                f"{target.__name__}.{target_field} type {info.annotation!r}"
            )

    def _check_backref(
        self, field_name: str, target: type[ScopedModel], via: str
    ) -> None:
        target_graph = target.__refs__
        prefix = f"{self._owner.__name__}.{field_name}: backref via {via!r}"
        raw = target_graph._raw.get(via)
        if raw is None or not isinstance(raw.marker, Ref):
            raise RefResolutionError(
                f"{prefix} — {target.__name__} has no ref() on a field named {via!r}"
            )
        via_target = target_graph[via].target
        if not issubclass(self._owner, via_target):
            raise RefResolutionError(
                f"{prefix} — {target.__name__}.{via} references "
                f"{via_target.__name__}, not {self._owner.__name__}"
            )
