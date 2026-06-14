"""Before-validator ordering: the trap warning + the ``run_inherited_before`` helper.

pydantic v2 runs ``mode="before"`` model validators **child-first, then up the
MRO**. A ``@scoped_validator(mode="before")`` therefore runs *before* a plain
``@model_validator(mode="before")`` inherited from a base — so if the child
depends on the base hook's transformation (e.g. JSON-decoding columns), it sees
raw, untransformed data. (The base need not be a non-``ScopedModel``; a plain
hook on a ``ScopedModel`` ancestor races just the same.) This module detects it at
class definition (:func:`_warn_ordering_trap`) and provides the runtime escape
hatch (:func:`_run_inherited_before`, surfaced as
``ScopedModel.run_inherited_before``).
"""

from __future__ import annotations

import inspect
import warnings
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from pydantic import BaseModel

from ...errors import PrismOrderingWarning
from ...validators import (
    _SCOPED_VALIDATOR_PARENT_ORDERING,  # pyright: ignore[reportPrivateUsage]
    _SCOPED_VALIDATOR_SCOPES,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from ...model import ScopedModel

__all__ = ["_run_inherited_before", "_warn_ordering_trap"]

# Per-class set of scoped-validator names already warned about, so the warning
# is one-shot per (class, validator-name) and never per validate() call. Weak so
# it dies with the class.
_WARNED: WeakKeyDictionary[type, set[str]] = WeakKeyDictionary()


def _raw_func(decorator: Any) -> Any:
    """The underlying function of a pydantic validator decorator."""
    func = decorator.func
    return func.__func__ if inspect.ismethod(func) else func


def _validator_owner(cls: type[BaseModel], cls_var_name: str) -> type | None:
    """The MRO class that *defines* the named validator (nearest first)."""
    return next((a for a in cls.__mro__ if cls_var_name in a.__dict__), None)


def _inherited_before_validators(
    cls: type[BaseModel],
) -> list[tuple[str, Any, type]]:
    """``(name, raw_func, owner)`` for plain inherited ``before`` model validators.

    A validator qualifies when it is a ``mode="before"`` ``@model_validator``
    defined on a **strict ancestor** of ``cls`` (so ``cls``'s own validators are
    excluded) that is **not** a prism ``@scoped_validator`` (those are
    prism-managed and pydantic orders them per the round-5 contract; the trap is
    specifically a *plain* base hook racing a scoped one). Whether the owner
    subclasses ``ScopedModel`` is irrelevant — the race exists either way.
    Ordered the way pydantic runs them — nearest ancestor first, parent-most
    last — by the owner's MRO position.
    """
    out: list[tuple[int, str, Any, type]] = []
    mro_index = {klass: i for i, klass in enumerate(cls.__mro__)}
    for name, decorator in cls.__pydantic_decorators__.model_validators.items():
        if decorator.info.mode != "before":
            continue
        # A model_validator's owner is always an MRO class (pydantic put the
        # decorator there) and always a BaseModel subclass; skip cls's own.
        owner = _validator_owner(cls, decorator.cls_var_name)
        if owner is None or owner is cls:
            continue
        raw = _raw_func(decorator)
        if raw in _SCOPED_VALIDATOR_SCOPES:  # a scoped_validator, not a plain hook
            continue
        out.append((mro_index[owner], name, raw, owner))
    out.sort(key=lambda item: item[0])
    return [(name, raw, owner) for _, name, raw, owner in out]


def _scoped_before_validators(cls: type[ScopedModel]) -> list[str]:
    """Names of this class's ``@scoped_validator(mode="before")`` validators."""
    return [
        name
        for name in cls.__prism__.validator_scopes
        if cls.__pydantic_decorators__.model_validators[name].info.mode == "before"
    ]


def _ordering_declared(cls: type[ScopedModel], name: str) -> bool:
    """True if the scoped validator declared ``parent_ordering="acknowledged"``.

    The author asserted the validator does not depend on the inherited hook, so
    the warning is silenced.
    """
    raw = _raw_func(cls.__pydantic_decorators__.model_validators[name])
    return raw in _SCOPED_VALIDATOR_PARENT_ORDERING


def _warn_ordering_trap(cls: type[ScopedModel]) -> None:
    """Warn (once per scoped validator) when the before-ordering trap exists.

    The trap: a ``@scoped_validator(mode="before")`` on a model that inherits a
    plain ``@model_validator(mode="before")`` (on any ancestor — the owner's
    base is irrelevant; what matters is it is not itself a scoped_validator).
    pydantic runs the scoped one first, so a child that depends on the base
    hook's output sees untransformed data. Silenced per-validator with
    ``parent_ordering="acknowledged"``.
    """
    scoped_before = _scoped_before_validators(cls)
    if not scoped_before:
        return
    inherited = _inherited_before_validators(cls)
    if not inherited:
        return
    parent_name, _, ancestor = inherited[0]  # nearest = the one that runs next
    seen = _WARNED.setdefault(cls, set())
    for name in scoped_before:
        if name in seen or _ordering_declared(cls, name):
            continue
        seen.add(name)
        warnings.warn(
            f"{cls.__name__}.{name} is a @scoped_validator(mode='before') while "
            f"{ancestor.__name__}.{parent_name} is an inherited "
            f"@model_validator(mode='before'). pydantic v2 runs {name} first, so if "
            f"it depends on {parent_name}'s transformation the data is not yet "
            f"processed. Best fix: if {name} derives a value from already-parsed "
            f"fields, use mode='after' and read self (the base hook has run by "
            f"then) — no ordering race. If you need the before-phase, call "
            f"{cls.__name__}.run_inherited_before(data) at the top of {name} "
            f"(its inherited hooks must be idempotent — they re-run). If {name} "
            f"does not depend on {parent_name}, pass "
            f"parent_ordering='acknowledged' to silence this.",
            category=PrismOrderingWarning,
            stacklevel=2,
        )


def _run_inherited_before(cls: type[BaseModel], data: Any) -> Any:
    """Run every inherited ``before`` model validator, in pydantic order.

    Implements :meth:`ScopedModel.run_inherited_before`. Each validator owned by
    a strict, non-prism ancestor is invoked as ``validator(cls, data)`` with its
    return threaded into the next, nearest ancestor first and parent-most last —
    the same order pydantic would run the inherited slice in. Returns the fully
    transformed data.
    """
    for _name, raw, _owner in _inherited_before_validators(cls):
        data = raw(cls, data)
    return data
