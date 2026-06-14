"""Recursive narrowing of a dumped instance to a projection's field set."""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping
from typing import Any, Union, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

__all__ = ["_apply_decoders", "_narrow", "_narrow_value", "_validation_key"]

# A handler for one model node: takes the model class + its dumped mapping and
# returns the transformed dict. ``_narrow`` (drop canonical-only keys + encode)
# and ``_apply_decoders`` (decode in place) are the two implementations.
_OnModel = Callable[[type[BaseModel], Mapping[str, Any]], dict[str, Any]]


def _validation_key(name: str, info: FieldInfo) -> str:
    """The key a field expects in validation input (alias-aware)."""
    if isinstance(info.validation_alias, str):
        return info.validation_alias
    if isinstance(info.alias, str):
        return info.alias
    return name


def _narrow(model_cls: type[BaseModel], data: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the keys ``model_cls`` accepts, recursing into nested models.

    Drives ``from_canonical``: also **encodes** any ``as_type=`` field through the
    projection's ``__prism__.encoders`` (canonical value → projection value); an
    encoded field's raw value goes straight to its encoder, bypassing the
    structural walk (its canonical shape need not match the override annotation).
    """
    out: dict[str, Any] = {}
    # getattr-chain so a plain BaseModel (no __prism__) or a canonical model
    # (ModelState has no .encoders) both fall back to {}.
    state = getattr(model_cls, "__prism__", None)
    encoders: dict[str, Callable[[Any], Any]] = getattr(state, "encoders", {})
    for name, info in model_cls.model_fields.items():
        key = _validation_key(name, info)
        if key in data:
            raw = data[key]
        elif name in data:
            raw = data[name]
        else:
            continue
        out[key] = (
            encoders[name](raw)
            if name in encoders
            else _narrow_value(info.annotation, raw)
        )
    return out


def _apply_decoders(
    proj_cls: type[BaseModel], data: Mapping[str, Any]
) -> dict[str, Any]:
    """Decode an ``as_type=`` projection's dump back toward the canonical.

    Drives ``from_projection`` / ``with_updates``: unlike ``_narrow`` it keeps
    every present key (the canonical is a superset), applying each retyped field's
    ``__prism__.decoders`` (projection value → canonical value) and recursing into
    nested projections. A no-op (identity) when nothing in the tree was retyped.
    """
    out: dict[str, Any] = {}
    state = getattr(proj_cls, "__prism__", None)
    decoders: dict[str, Callable[[Any], Any]] = getattr(state, "decoders", {})
    for name, info in proj_cls.model_fields.items():
        # The data is the projection's *own* dump (by_alias), so each field sits
        # under its validation key — one lookup, no canonical/alias ambiguity.
        key = _validation_key(name, info)
        if key not in data:
            continue
        raw = data[key]
        out[key] = (
            decoders[name](raw)
            if name in decoders
            else _walk_value(info.annotation, raw, _apply_decoders)
        )
    return out


def _narrow_value(annotation: Any, value: Any) -> Any:
    return _walk_value(annotation, value, _narrow)


def _walk_value(annotation: Any, value: Any, on_model: _OnModel) -> Any:
    """Recurse into containers/unions, dispatching model nodes to ``on_model``."""
    while hasattr(annotation, "__metadata__"):
        annotation = get_args(annotation)[0]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if isinstance(value, Mapping):
            return on_model(annotation, cast(Mapping[str, Any], value))
        return value
    origin = get_origin(annotation)
    if origin is None:
        return value
    args = get_args(annotation)
    if origin in (Union, types.UnionType):
        return _walk_union(args, value, on_model)
    if isinstance(origin, type) and issubclass(origin, Mapping):
        if len(args) == 2 and isinstance(value, Mapping):
            items = cast(Mapping[Any, Any], value)
            return {k: _walk_value(args[1], v, on_model) for k, v in items.items()}
        return value
    if (
        origin in (list, set, frozenset)
        and args
        and isinstance(value, (list, set, frozenset))
    ):
        return [_walk_value(args[0], item, on_model) for item in cast(list[Any], value)]
    if origin is tuple and args and isinstance(value, (list, tuple)):
        return _walk_tuple(args, list(cast(list[Any], value)), on_model)
    return value


def _walk_union(args: tuple[Any, ...], value: Any, on_model: _OnModel) -> Any:
    models = [a for a in args if isinstance(a, type) and issubclass(a, BaseModel)]
    if len(models) == 1 and isinstance(value, Mapping):
        return on_model(models[0], cast(Mapping[str, Any], value))
    return value


def _walk_tuple(
    args: tuple[Any, ...], items: list[Any], on_model: _OnModel
) -> list[Any]:
    if len(args) == 2 and args[1] is Ellipsis:
        return [_walk_value(args[0], item, on_model) for item in items]
    return [
        _walk_value(arg, item, on_model) for arg, item in zip(args, items, strict=False)
    ]
