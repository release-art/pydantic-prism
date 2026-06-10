"""Marker collection: build ``__field_scopes__`` / ``__refs__`` from a model."""

from __future__ import annotations

import inspect
from typing import Any, cast, get_args, get_origin

from .._markers import PRISM_MARKERS, BackRef, Ref, Scoped
from .._refs import Embedded, RawEdge, RefGraph, RefShape, shape_of
from .._scopes import ScopeExpr, union_all
from .._validators import (
    _SCOPED_VALIDATOR_SCOPES,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from ._classes import Projection, ScopedModel

__all__ = ["_collect", "_initialize", "_variable_container"]


def _initialize(cls: type[ScopedModel]) -> None:
    """Class-definition setup: collect markers, imply backref defaults."""
    _collect(cls)
    if _imply_backref_defaults(cls):
        cls.model_rebuild(force=True, raise_errors=False)


def _collect(cls: type[ScopedModel]) -> None:
    """Validate markers and (re)build ``__field_scopes__`` / ``__refs__``.

    Runs at class creation and again after every successful ``model_rebuild``,
    because markers on forward-referenced annotations are invisible until the
    rebuild resolves them.
    """
    field_scopes: dict[str, ScopeExpr] = {}
    raw_refs: dict[str, RawEdge] = {}
    for field_name, info in cls.model_fields.items():
        if isinstance(info.default, PRISM_MARKERS):
            raise TypeError(
                f"{cls.__name__}.{field_name}: {type(info.default).__name__} marker "
                f"used as a field default; prism markers go inside Annotated[...] "
                f"metadata, e.g. Annotated[str, scoped(...)]"
            )
        _reject_nested_markers(cls, field_name, info.annotation)
        scope_markers = [m for m in info.metadata if isinstance(m, Scoped)]
        ref_markers = [m for m in info.metadata if isinstance(m, (Ref, BackRef))]
        if scope_markers:
            # Explicit wins, no merge: a tagged field ignores the class default.
            field_scopes[field_name] = union_all(m.expr for m in scope_markers)
        elif cls.__prism_default_scope__ is not None:
            # Untagged field on a class with a default: fall back to it. The
            # fallback is uniform — ref()/backref() fields are filled too.
            field_scopes[field_name] = cls.__prism_default_scope__
        if len(ref_markers) > 1:
            raise TypeError(
                f"{cls.__name__}.{field_name}: at most one ref()/backref() marker "
                f"is allowed per field"
            )
        if ref_markers:
            shape, optional, key_type = shape_of(info.annotation)
            raw_refs[field_name] = RawEdge(ref_markers[0], shape, optional, key_type)
        else:
            embedded = _detect_embedded(info.annotation)
            if embedded is not None:
                shape, optional, key_type = shape_of(info.annotation)
                raw_refs[field_name] = RawEdge(embedded, shape, optional, key_type)
    cls.__field_scopes__ = field_scopes
    cls.__prism_validator_scopes__ = _collect_validator_scopes(cls)
    existing = cls.__dict__.get("__refs__")
    if isinstance(existing, RefGraph):
        # Mutate in place so graphs already held by user code stay current.
        existing._reset(raw_refs)  # pyright: ignore[reportPrivateUsage] — intra-package
    else:
        cls.__refs__ = RefGraph(cls, raw_refs)


def _detect_embedded(annotation: Any) -> Embedded | None:
    """The auto-detected embedded edge of a field annotation, if unambiguous.

    A field embedding exactly one model — a canonical ``ScopedModel``
    (composition: reshapes with the outer projection) or a ``Projection``
    class (a fixed carrier record with provenance) — registers an
    ``embedded`` edge. Annotations mixing several distinct models register
    nothing.
    """
    found: set[tuple[type[ScopedModel], ScopeExpr | None]] = set()
    _find_embedded_models(annotation, found)
    if len(found) != 1:
        return None
    target, scope = next(iter(found))
    return Embedded(target, scope)


def _find_embedded_models(
    annotation: Any, found: set[tuple[type[ScopedModel], ScopeExpr | None]]
) -> None:
    while hasattr(annotation, "__metadata__"):
        annotation = get_args(annotation)[0]
    if isinstance(annotation, type):
        if issubclass(annotation, ScopedModel) and annotation is not ScopedModel:
            found.add((annotation, None))
        elif issubclass(annotation, Projection) and annotation is not Projection:
            source = getattr(annotation, "__prism_source__", None)
            if source is not None:
                found.add((source, annotation.__prism_scope__))
        return
    for arg in get_args(annotation):
        if isinstance(arg, list):  # Callable parameter lists
            for item in cast(list[Any], arg):
                _find_embedded_models(item, found)
        else:
            _find_embedded_models(arg, found)


def _reject_nested_markers(
    cls: type[ScopedModel], field_name: str, annotation: Any
) -> None:
    """Refuse prism markers below the field's top-level ``Annotated``.

    Pydantic only lifts top-level metadata into ``FieldInfo.metadata``;
    anything deeper would be silently ignored, which for scope markers means
    silent field loss — so it is an error instead.
    """
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None and any(isinstance(m, PRISM_MARKERS) for m in metadata):
        raise TypeError(
            f"{cls.__name__}.{field_name}: prism markers must sit in the field's "
            f"top-level Annotated metadata; found one nested inside the annotation"
        )
    for arg in get_args(annotation):
        if isinstance(arg, list):  # Callable parameter lists
            for item in cast(list[Any], arg):
                _reject_nested_markers(cls, field_name, item)
        else:
            _reject_nested_markers(cls, field_name, arg)


def _imply_backref_defaults(cls: type[ScopedModel]) -> bool:
    """Give required backref fields their implied empty default."""
    changed = False
    for info in cls.model_fields.values():
        marker = next((m for m in info.metadata if isinstance(m, BackRef)), None)
        if marker is None or not info.is_required():
            continue
        shape, optional, _ = shape_of(info.annotation)
        if shape is not RefShape.SCALAR:
            factory = _variable_container(info.annotation)
            if factory is not None:  # fixed-size tuples stay required
                info.default_factory = factory
                changed = True
        elif optional:
            info.default = None
            changed = True
    return changed


def _variable_container(annotation: Any) -> type[Any] | None:
    """The empty-constructible container type of a to-many annotation, if any."""
    while hasattr(annotation, "__metadata__"):
        annotation = get_args(annotation)[0]
    origin = get_origin(annotation)
    if origin in (list, set, frozenset, dict):
        return cast(type[Any], origin)
    if origin is tuple:
        args = get_args(annotation)
        if args and args[-1] is Ellipsis:
            return tuple
    return None


def _collect_validator_scopes(cls: type[ScopedModel]) -> dict[str, ScopeExpr]:
    """Map each ``@scoped_validator`` name to the scope expression it carries to.

    The scope tag is recorded by the decorator in a registry keyed by the raw
    function; ``decorator.func`` is that function for ``mode="after"`` and a
    bound method (``.__func__`` is the raw function) for ``before``/``wrap``.
    """
    scopes: dict[str, ScopeExpr] = {}
    for dec_name, decorator in cls.__pydantic_decorators__.model_validators.items():
        func: Any = decorator.func
        raw: Any = func.__func__ if inspect.ismethod(func) else func
        tag = _SCOPED_VALIDATOR_SCOPES.get(raw)
        if tag is not None:
            scopes[dec_name] = tag
    return scopes
