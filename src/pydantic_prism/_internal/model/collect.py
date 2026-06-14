"""Marker collection: build a model's ``__prism__`` field-scopes / refs."""

from __future__ import annotations

import inspect
from typing import Any, cast, get_args, get_origin

from ...errors import ProjectionNameError
from ...markers import PRISM_MARKERS, BackRef, Ref, Scoped
from ...model import Projection, ScopedModel
from ...refs import Embedded, RawEdge, RefGraph, RefShape, shape_of
from ...validators import (
    _SCOPED_VALIDATOR_SCOPES,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from ..scopes import Scope, ScopeExpr, as_expr, union_all

__all__ = ["_collect", "_initialize", "_project_refs", "_variable_container"]


def _initialize(cls: type[ScopedModel]) -> None:
    """Class-definition setup: collect markers, imply backref defaults."""
    _collect(cls)
    if _imply_backref_defaults(cls):
        cls.model_rebuild(force=True, raise_errors=False)


def _collect(cls: type[ScopedModel]) -> None:
    """Validate markers and (re)build ``__prism__.field_scopes`` / ``__prism__.refs``.

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
        elif cls.__prism__.default_scope is not None:
            # Untagged field on a class with a default: fall back to it. The
            # fallback is uniform — ref()/backref() fields are filled too.
            field_scopes[field_name] = cls.__prism__.default_scope
        if len(ref_markers) > 1:
            raise TypeError(
                f"{cls.__name__}.{field_name}: at most one ref()/backref() marker "
                f"is allowed per field"
            )
        edge = _derive_edge(info.annotation, ref_markers)
        if edge is not None:
            raw_refs[field_name] = edge
    cls.__prism__.field_scopes = field_scopes
    _check_scope_name_tokens(cls)
    cls.__prism__.validator_scopes = _collect_validator_scopes(cls)
    # The state's RefGraph is created with the class (in __init_subclass__) and
    # reset in place on every (re)collect, so graphs already held by user code
    # stay current.
    cls.__prism__.refs._reset(raw_refs)  # pyright: ignore[reportPrivateUsage] — intra-package


def _derive_edge(annotation: Any, ref_markers: list[Any]) -> RawEdge | None:
    """The relationship edge of a field annotation, if any (≤1 ref marker assumed).

    An explicit ``ref()``/``backref()`` marker wins; otherwise an unambiguously
    embedded model is auto-detected. Shared by initial collection and per-scope
    ref re-derivation (when ``as_type=`` reshapes a field).
    """
    if ref_markers:
        shape, optional, key_type = shape_of(annotation)
        return RawEdge(ref_markers[0], shape, optional, key_type)
    embedded = _detect_embedded(annotation)
    if embedded is not None:
        shape, optional, key_type = shape_of(annotation)
        return RawEdge(embedded, shape, optional, key_type)
    return None


def _project_refs(
    cls: type[ScopedModel], surviving: list[str], retyped: dict[str, Any]
) -> RefGraph:
    """The projection's relationship graph: canonical edges filtered to ``surviving``.

    A field reshaped by ``as_type=`` has its edge **re-derived** from the override
    annotation (its shape / key-type / embedded target may differ, or it may gain
    or lose an edge entirely), keeping any explicit ``ref()``/``backref()`` marker.
    """
    if not retyped:
        return cls.__prism__.refs.filtered(surviving)
    overrides: dict[str, RawEdge | None] = {}
    for field_name, annotation in retyped.items():
        ref_markers = [
            m
            for m in cls.model_fields[field_name].metadata
            if isinstance(m, (Ref, BackRef))
        ]
        overrides[field_name] = _derive_edge(annotation, ref_markers)
    return cls.__prism__.refs.reshaped(surviving, overrides)


def _check_scope_name_tokens(cls: type[ScopedModel]) -> None:
    """Reject a model whose scopes would auto-name two projections identically.

    A projection's auto-name is the model name + the scope expression's token,
    where each atom contributes its ``cls_name_token`` (else its ``__name__``).
    Two scopes on one model sharing that token — two same-named scopes from
    different modules, or a stray duplicate ``cls_name_token=`` — would make
    ``Model.scope(A)`` and ``Model.scope(B)`` resolve to the same class name.
    That is confusable, so it is rejected here, at model definition, and fixed at
    the source (rename one, or give it a distinct ``cls_name_token=``) rather than
    papered over with ``name=`` at every call site.

    Scoped to *this* model's atoms — there is no global scope registry, since a
    token only has to be unique within one model's projection namespace; two
    unrelated modules may each define a ``Public``.
    """
    by_token: dict[str, type[Scope]] = {}
    for scope in sorted(cls.scopes(), key=lambda s: (s.__module__, s.__qualname__)):
        token = as_expr(scope).token()
        clash = by_token.get(token)
        if clash is not None:
            raise ProjectionNameError(
                f"{cls.__name__}: scopes {clash.__module__}.{clash.__qualname__} and "
                f"{scope.__module__}.{scope.__qualname__} both contribute the "
                f"projection-name token {token!r}, so their projections of "
                f"{cls.__name__} would share a class name. Rename one, or give it a "
                f"distinct cls_name_token=."
            )
        by_token[token] = scope


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
            state = getattr(annotation, "__prism__", None)
            if state is not None:
                found.add((state.source, state.scope))
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
