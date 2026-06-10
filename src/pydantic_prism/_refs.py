"""Introspection surface for model relationships: RefInfo and RefGraph."""

from __future__ import annotations

import sys
import types
from collections import deque
from collections.abc import Collection, Iterator, Mapping, Sequence, Set
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Union, get_args, get_origin

from ._markers import BackRef, Ref
from .errors import RefResolutionError

if TYPE_CHECKING:
    from ._model import ScopedModel

__all__ = ["RefGraph", "RefInfo"]

RefKind = Literal["ref", "backref"]


@dataclass(frozen=True)
class RefInfo:
    """One resolved relationship edge.

    Attributes:
        field_name: Name of the field carrying the marker on the owning model.
        target: The referenced ScopedModel class (canonical, never a projection).
        target_field: Field on ``target`` the stored ids correspond to.
        many: True when the annotation is a container (``list[UUID]`` etc.).
        optional: True when the annotation admits ``None``.
        kind: ``"ref"`` for forward references, ``"backref"`` for declared
            reverse references.
        via: For backrefs, the field on ``target`` holding the forward ref.
    """

    field_name: str
    target: type[ScopedModel]
    target_field: str
    many: bool
    optional: bool
    kind: RefKind
    via: str | None = None


def cardinality(annotation: Any) -> tuple[bool, bool]:
    """Infer ``(many, optional)`` from a field annotation."""
    ann = annotation
    while hasattr(ann, "__metadata__"):
        ann = get_args(ann)[0]
    origin = get_origin(ann)
    if origin in (Union, types.UnionType):
        args = get_args(ann)
        optional = type(None) in args
        rest = [arg for arg in args if arg is not type(None)]
        many = cardinality(rest[0])[0] if len(rest) == 1 else False
        return many, optional
    if isinstance(origin, type) and issubclass(
        origin, (list, set, frozenset, tuple, Sequence, Set)
    ):
        return True, False
    return False, False


class RefGraph(Mapping[str, RefInfo]):
    """The relationship graph of one model: a mapping of field name → RefInfo.

    Targets resolve lazily on access (string forward references are looked up
    in the owning model's module), so circular model graphs work regardless of
    definition order. Resolution failures raise :class:`RefResolutionError`.
    """

    def __init__(
        self,
        owner: type[Any],
        entries: Mapping[str, tuple[Ref | BackRef, bool, bool]],
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
            for name, (m, _, _) in self._raw.items()
        )
        return f"RefGraph({self._owner.__name__}: {edges or 'no refs'})"

    @property
    def outgoing(self) -> dict[str, RefInfo]:
        """Forward ``ref`` edges only."""
        return {n: self[n] for n, (m, _, _) in self._raw.items() if isinstance(m, Ref)}

    @property
    def incoming(self) -> dict[str, RefInfo]:
        """Declared ``backref`` edges only."""
        return {n: self[n] for n, (m, _, _) in self._raw.items() if isinstance(m, BackRef)}

    def targets(self) -> set[type[ScopedModel]]:
        """Every model referenced by this one (forward or declared reverse)."""
        return {info.target for info in self.values()}

    def walk(self) -> Iterator[tuple[type[Any], RefInfo]]:
        """Breadth-first traversal of forward edges reachable from the owner.

        Yields ``(source_model, info)`` pairs; ``info.target`` is the edge's
        destination. Each model is expanded once, so cycles terminate.
        """
        seen: set[type[Any]] = {self._owner}
        queue: deque[RefGraph] = deque([self])
        while queue:
            graph = queue.popleft()
            for info in graph.outgoing.values():
                yield graph.owner, info
                if info.target not in seen:
                    seen.add(info.target)
                    target_graph = getattr(info.target, "__refs__", None)
                    if isinstance(target_graph, RefGraph):
                        queue.append(target_graph)

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

        marker, many, optional = self._raw[field_name]
        target = marker.target
        if isinstance(target, str):
            module = sys.modules.get(self._owner.__module__)
            candidate = getattr(module, target, None)
            if not (isinstance(candidate, type) and issubclass(candidate, ScopedModel)):
                raise RefResolutionError(
                    f"{self._owner.__name__}.{field_name}: cannot resolve "
                    f"{target!r} to a ScopedModel in module "
                    f"{self._owner.__module__!r}"
                )
            target = candidate
        if isinstance(marker, BackRef):
            self._check_backref(field_name, target, marker.via)
            kind: RefKind = "backref"
            via = marker.via
        else:
            kind = "ref"
            via = None
        return RefInfo(
            field_name=field_name,
            target=target,
            target_field=marker.target_field,
            many=many,
            optional=optional,
            kind=kind,
            via=via,
        )

    def _check_backref(self, field_name: str, target: type[ScopedModel], via: str) -> None:
        target_graph = target.__refs__
        prefix = f"{self._owner.__name__}.{field_name}: backref via {via!r}"
        raw = target_graph._raw.get(via)
        if raw is None or not isinstance(raw[0], Ref):
            raise RefResolutionError(
                f"{prefix} — {target.__name__} has no ref() on a field named {via!r}"
            )
        via_target = target_graph[via].target
        if not issubclass(self._owner, via_target):
            raise RefResolutionError(
                f"{prefix} — {target.__name__}.{via} references "
                f"{via_target.__name__}, not {self._owner.__name__}"
            )
