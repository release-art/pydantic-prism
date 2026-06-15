"""Carry a canonical model's plain Python behavior onto its projections.

Projections never include the canonical class in their MRO
(``<Model><Scope> -> _<Model><Scope>Base -> Projection -> BaseModel``), so
methods, ``@property``, ``@classmethod`` and ``@staticmethod`` defined on the
canonical model would be lost. This module copies those non-field callables onto
every projection by default; ``@unprojected`` opts a member out, and framework
names (anything already on :class:`Projection`/``BaseModel``) are never
overwritten.

This is distinct from carried *bases* (:mod:`.bases`): ``projection_bases=``
exists for pydantic-level behavior (custom ``model_dump``, model validators /
serializers, ``isinstance`` identity); plain callables need no separate base.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, cast

from ...model import Projection, ScopedModel

if TYPE_CHECKING:
    from ...model import ScopedModel as ScopedModelT

__all__ = [
    "_collect_behaviors",
    "_copy_behaviors",
    "_is_unprojected",
    "_pydantic_managed",
]


def _is_behavior(member: object) -> bool:
    """Whether ``member`` is a non-field callable prism should carry."""
    return isinstance(
        member, (staticmethod, classmethod, property)
    ) or inspect.isfunction(member)


def _is_dunder(name: str) -> bool:
    """Whether ``name`` is a ``__dunder__`` — never a user behavior to carry.

    Excludes interpreter/compiler-injected callables that live in a class
    ``__dict__`` but are machinery, not behavior — notably Python 3.14's
    PEP-649 ``__annotate_func__`` (a function, so :func:`_is_behavior` would
    otherwise carry it). Any dunder a projection legitimately needs
    (``__str__``, ``__eq__``, …) already comes from ``Projection`` / pydantic.
    """
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _is_unprojected(member: Any) -> bool:
    """Whether ``member`` carries the ``@unprojected`` opt-out flag.

    The flag is set on the underlying function — ``__func__`` for a
    ``classmethod`` / ``staticmethod``, ``fget`` for a ``property`` — so it
    survives whichever order it wraps with.
    """
    if isinstance(member, (classmethod, staticmethod)):
        member = cast(Any, member).__func__
    elif isinstance(member, property):
        member = cast(Any, member).fget
    return getattr(member, "__prism_unprojected__", False) is True


def _pydantic_managed(cls: type[ScopedModelT]) -> set[str]:
    """Names pydantic owns on ``cls`` — validators, serializers, computed fields.

    These are not plain Python behavior: a ``@model_validator`` /
    ``@field_validator`` / ``@computed_field`` stays a bare ``classmethod`` /
    ``property`` in ``vars(cls)`` (its registration lives in
    ``__pydantic_decorators__``), so copying the raw callable would duplicate —
    and silently mis-fire — pydantic machinery. Such behavior already travels via
    the field-validator carry path or a carried base, never this one.
    """
    decorators = cls.__pydantic_decorators__
    return {
        *decorators.validators,
        *decorators.field_validators,
        *decorators.root_validators,
        *decorators.field_serializers,
        *decorators.model_serializers,
        *decorators.model_validators,
        *decorators.computed_fields,
    }


def _collect_behaviors(cls: type[ScopedModelT]) -> dict[str, Any]:
    """The canonical behaviors prism carries onto a projection: name → member.

    Walks ``cls``'s MRO down to — but not including — :class:`ScopedModel`, so
    behavior declared on canonical ancestors is included; the most-derived
    definition of a name wins. Omitted: any ``__dunder__`` (interpreter
    machinery, e.g. 3.14's ``__annotate_func__``), a member named like a
    :class:`Projection` / ``BaseModel`` member, a pydantic-managed validator /
    serializer / computed field, and any ``@unprojected`` member.

    The single source of truth shared by the runtime copy (:func:`_copy_behaviors`)
    and ``prism gen`` (which renders these into each face's stub), so both honor
    ``@unprojected`` and the pydantic-managed exclusions identically.
    """
    managed = _pydantic_managed(cls)
    seen: set[str] = set()
    out: dict[str, Any] = {}
    for klass in cls.__mro__:
        if klass is ScopedModel:
            break
        for name, member in vars(klass).items():
            if name in seen or not _is_behavior(member):
                continue
            seen.add(name)
            if (
                _is_dunder(name)
                or name in managed
                or _is_unprojected(member)
                or hasattr(Projection, name)
            ):
                continue
            out[name] = member
    return out


def _copy_behaviors(cls: type[ScopedModelT], projection: type[Projection]) -> None:
    """Copy ``cls``'s (and its canonical ancestors') behaviors onto ``projection``.

    Uses :func:`_collect_behaviors` for the selection, additionally skipping any
    name already present on ``projection`` (a pydantic-generated class attribute
    must never be overwritten).
    """
    existing = set(vars(projection))
    for name, member in _collect_behaviors(cls).items():
        if name not in existing:
            setattr(projection, name, member)
