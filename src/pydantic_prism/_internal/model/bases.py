"""Validation + drop-warnings for carried (non-ScopedModel) projection bases."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel

from ...errors import PrismBaseDropWarning
from ...model import ScopedModel

__all__ = ["_check_bases", "_warn_dropped_behavior"]

# Pydantic I/O entry points whose base-class overrides projections would
# silently drop without carried bases.
_MODEL_IO_METHODS = (
    "model_dump",
    "model_dump_json",
    "model_validate",
    "model_validate_json",
)


def _check_bases(
    cls: type[ScopedModel], bases: Sequence[type[BaseModel]]
) -> tuple[type[BaseModel], ...]:
    """Validate a projection-bases declaration (class-level or per-call)."""
    checked: list[type[BaseModel]] = []
    for raw_base in bases:
        # runtime guard: annotations don't stop untyped callers
        base = cast(Any, raw_base)
        if not (isinstance(base, type) and issubclass(base, BaseModel)):
            raise TypeError(
                f"{cls.__name__}: projection base {base!r} is not a pydantic "
                f"BaseModel subclass"
            )
        if issubclass(base, ScopedModel):
            raise TypeError(
                f"{cls.__name__}: projection base {base.__name__} is a ScopedModel; "
                f"only plain pydantic bases can be carried onto projections "
                f"(scoped ancestry is rebuilt by the projection itself)"
            )
        if not issubclass(cls, base):
            raise TypeError(
                f"{cls.__name__}: projection base {base.__name__} is not an ancestor "
                f"of {cls.__name__}; projections may only carry bases their "
                f"canonical model inherits from"
            )
        checked.append(base)
    return tuple(checked)


def _droppable_behavior(cls: type[ScopedModel]) -> str | None:
    """Describe base-class pydantic behavior projections would drop, if any."""
    for base in cls.__mro__[1:]:
        if (
            not issubclass(base, BaseModel)
            or base is BaseModel
            or issubclass(base, ScopedModel)
        ):
            continue
        dropped: list[str] = []
        overridden = [m for m in _MODEL_IO_METHODS if m in vars(base)]
        if overridden:
            dropped.append("overridden " + "/".join(overridden))
        decorators = base.__pydantic_decorators__
        if decorators.model_validators:
            dropped.append("model validators")
        if decorators.model_serializers:
            dropped.append("model serializers")
        if dropped:
            return (
                f"projections of {cls.__name__} do not inherit "
                f"{' and '.join(dropped)} from base {base.__name__}; pass "
                f"bases=({base.__name__},) to .scope(), or declare "
                f"projection_bases=({base.__name__},) on the class, to carry the "
                f"base — or declare projection_bases=() to silence this warning"
            )
    return None


def _warn_dropped_behavior(cls: type[ScopedModel]) -> None:
    """Warn (once per canonical model) about base behavior being dropped."""
    if cls.__dict__.get("__prism_base_warned__"):
        return
    cls.__prism_base_warned__ = True
    message = _droppable_behavior(cls)
    if message is not None:
        warnings.warn(message, PrismBaseDropWarning, stacklevel=2)
