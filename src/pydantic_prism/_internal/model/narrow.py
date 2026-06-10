"""Recursive narrowing of a dumped instance to a projection's field set."""

from __future__ import annotations

import types
from collections.abc import Mapping
from typing import Any, Union, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

__all__ = ["_narrow", "_narrow_value", "_validation_key"]


def _validation_key(name: str, info: FieldInfo) -> str:
    """The key a field expects in validation input (alias-aware)."""
    if isinstance(info.validation_alias, str):
        return info.validation_alias
    if isinstance(info.alias, str):
        return info.alias
    return name


def _narrow(model_cls: type[BaseModel], data: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the keys ``model_cls`` accepts, recursing into nested models."""
    out: dict[str, Any] = {}
    for name, info in model_cls.model_fields.items():
        key = _validation_key(name, info)
        if key in data:
            out[key] = _narrow_value(info.annotation, data[key])
        elif name in data:
            out[key] = _narrow_value(info.annotation, data[name])
    return out


def _narrow_value(annotation: Any, value: Any) -> Any:
    while hasattr(annotation, "__metadata__"):
        annotation = get_args(annotation)[0]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if isinstance(value, Mapping):
            return _narrow(annotation, cast(Mapping[str, Any], value))
        return value
    origin = get_origin(annotation)
    if origin is None:
        return value
    args = get_args(annotation)
    if origin in (Union, types.UnionType):
        return _narrow_union(args, value)
    if isinstance(origin, type) and issubclass(origin, Mapping):
        if len(args) == 2 and isinstance(value, Mapping):
            items = cast(Mapping[Any, Any], value)
            return {k: _narrow_value(args[1], v) for k, v in items.items()}
        return value
    if (
        origin in (list, set, frozenset)
        and args
        and isinstance(value, (list, set, frozenset))
    ):
        return [_narrow_value(args[0], item) for item in cast(list[Any], value)]
    if origin is tuple and args and isinstance(value, (list, tuple)):
        return _narrow_tuple(args, list(cast(list[Any], value)))
    return value


def _narrow_union(args: tuple[Any, ...], value: Any) -> Any:
    models = [a for a in args if isinstance(a, type) and issubclass(a, BaseModel)]
    if len(models) == 1 and isinstance(value, Mapping):
        return _narrow(models[0], cast(Mapping[str, Any], value))
    return value


def _narrow_tuple(args: tuple[Any, ...], items: list[Any]) -> list[Any]:
    if len(args) == 2 and args[1] is Ellipsis:
        return [_narrow_value(args[0], item) for item in items]
    return [_narrow_value(arg, item) for arg, item in zip(args, items, strict=False)]
