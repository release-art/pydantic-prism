"""The projection builder: ``_project`` and its supporting helpers."""

from __future__ import annotations

import copy
import inspect
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ForwardRef,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
)

from pydantic import create_model, field_validator, model_validator
from pydantic.experimental.missing_sentinel import MISSING
from pydantic.fields import FieldInfo

from ...errors import EmptyProjectionError, ProjectionBaseError, ProjectionNameError
from ...markers import (
    _NO_TYPE,  # pyright: ignore[reportPrivateUsage] — intra-package
    PRISM_MARKERS,
    Heritage,
)
from ...model import (
    Projection,
    ScopedModel,
    _ProjectionKey,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from ..scopes import ScopeExpr
from .bases import _warn_dropped_behavior
from .behaviors import _copy_behaviors
from .collect import _project_refs
from .schema import _apply_field_spec, _apply_model_schema

if TYPE_CHECKING:
    from pydantic import BaseModel

__all__ = [
    "_BuildContext",
    "_auto_name",
    "_project",
    "_rewrite",
    "_validate_name_template",
]


@dataclass(frozen=True, slots=True)
class _BuildKey:
    """One projection's key *within a build context*: its owner + projection key.

    A single build context spans every nested model reached from the top-level
    ``scope()``/``input()`` call, and two different models can share a
    :class:`_ProjectionKey` (same expr/name/carried/extra), so the owning model
    must be part of the in-flight key. The ``key`` half is exactly what gets
    committed to ``owner``'s caches once the whole context finishes building.

    Frozen + slotted so it is hashable and usable as a dict key.
    """

    owner: type[ScopedModel]
    key: _ProjectionKey


# --- projection naming -----------------------------------------------------


def _validate_name_template(cls: type[ScopedModel], template: str) -> None:
    """Eagerly reject a ``projection_name_template`` that can't make a name."""
    try:
        sample = template.format(model="Model", scope="Scope")
    except (KeyError, IndexError) as exc:
        raise TypeError(
            f"{cls.__name__}: invalid projection_name_template {template!r}; "
            f"use only the {{model}} and {{scope}} placeholders"
        ) from exc
    if not sample.isidentifier():
        raise TypeError(
            f"{cls.__name__}: projection_name_template {template!r} must produce a "
            f"valid Python identifier (a sample model/scope gave {sample!r}); e.g. "
            f"'{{model}}_{{scope}}'. Non-identifier names break generated stubs "
            f"and OpenAPI component refs"
        )


def _auto_name(cls: type[ScopedModel], expr: ScopeExpr) -> str:
    """The auto-generated projection name: class template, or the default form."""
    template = cls.__prism_name_template__
    if template is None:
        return f"{cls.__name__}{expr.token()}"
    return template.format(model=cls.__name__, scope=expr.token())


# --- build context + selection ---------------------------------------------


class _BuildContext:
    """State for one top-level ``scope()`` call, threading through recursion."""

    def __init__(self) -> None:
        # build key -> ForwardRef/namespace name, while the class is being built
        self.pending: dict[_BuildKey, str] = {}
        # build key -> finished (but not yet rebuilt/committed) class
        self.built: dict[_BuildKey, type[Projection]] = {}
        # ForwardRef name -> class; names are unique even when class names collide
        self.namespace: dict[str, type[Projection]] = {}

    def reserve_name(self, base: str) -> str:
        candidate = base
        suffix = 1
        while candidate in self.namespace or candidate in self.pending.values():
            suffix += 1
            candidate = f"{base}__{suffix}"
        return candidate


def _resolve_carried(
    cls: type[ScopedModel], bases: tuple[type[BaseModel], ...] | None
) -> tuple[type[BaseModel], ...]:
    """The bases a projection of ``cls`` carries (per-call > class > none).

    Falling through to "none" — no per-call ``bases=``, no class-level
    ``projection_bases=`` — warns once per model if base behavior is dropped.
    """
    if bases is not None:
        return bases
    declared = cls.__prism_projection_bases__
    if declared is None:
        _warn_dropped_behavior(cls)
        return ()
    return declared


def _surviving_fields(cls: type[ScopedModel], expr: ScopeExpr) -> list[str]:
    """The model's fields selected by ``expr``; empty selections raise."""
    surviving = [
        field_name
        for field_name in cls.model_fields
        if field_name in cls.__field_scopes__
        and expr.selects(cls.__field_scopes__[field_name])
    ]
    if not surviving:
        defined = sorted(scope.__name__ for scope in cls.scopes())
        detail = (
            f"; {cls.__name__} defines scopes: {', '.join(defined)}"
            if defined
            else f"; no fields of {cls.__name__} are tagged with scoped(...)"
        )
        raise EmptyProjectionError(
            f"{cls.__name__}.scope({expr!r}) selects no fields; untagged fields "
            f"belong to no scope{detail}"
        )
    return surviving


def _record_field_payload(
    marker: Any,
    field_name: str,
    retyped: dict[str, Any],
    encoders: dict[str, Callable[[Any], Any]],
    decoders: dict[str, Callable[[Any], Any]],
) -> None:
    """Record a field's ``as_type`` (for ref re-derivation) and converters."""
    if marker is None:
        return
    if marker.field_type is not _NO_TYPE:
        retyped[field_name] = marker.field_type
    if marker.convert is not None:
        if marker.convert.encode is not None:
            encoders[field_name] = marker.convert.encode
        if marker.convert.decode is not None:
            decoders[field_name] = marker.convert.decode


def _project(
    cls: type[ScopedModel],
    expr: ScopeExpr,
    name: str | None,
    bases: tuple[type[BaseModel], ...] | None,
    ctx: _BuildContext,
    extra: Literal["allow", "ignore", "forbid"] | None = None,
) -> type[Projection] | ForwardRef:
    # ``extra`` overrides the projection's ``model_config["extra"]`` (e.g.
    # ``input()`` forces "forbid"); None inherits the canonical's. It applies to
    # this top-level projection only — nested projections built via ``_rewrite``
    # pass the default None, so they stay identical to a plain ``scope()`` and
    # share its cache, never forking a class on the parent's input/output mode.
    if not cls.__pydantic_complete__:
        # Unresolved forward references would make markers invisible and the
        # projection silently wrong; resolve now (raises pydantic's clear
        # error if names are genuinely missing) and refresh marker collection
        # via the model_rebuild override.
        cls.model_rebuild()
    carried = _resolve_carried(cls, bases)
    cache_key = _ProjectionKey(expr, name, carried, extra)
    cached = cls.__prism_cache__.get(cache_key)
    if cached is not None:
        return cached
    key = _BuildKey(cls, cache_key)
    if key in ctx.built:
        return ctx.built[key]
    if key in ctx.pending:
        # Cycle: refer to the in-flight class by its reserved namespace name,
        # resolved by the rebuild pass once every class in this context exists.
        return ForwardRef(ctx.pending[key])
    class_name = name if name is not None else _auto_name(cls, expr)
    registered = cls.__prism_names__.get(class_name)
    if registered is not None and registered != cache_key:
        raise ProjectionNameError(
            f"{cls.__name__} already has a projection named {class_name!r} for a "
            f"different scope expression; pass name= to disambiguate"
        )
    ref_name = ctx.reserve_name(class_name)
    ctx.pending[key] = ref_name

    surviving = _surviving_fields(cls, expr)
    _check_base_fields(cls, expr, carried, set(surviving))

    partial = expr.is_partial()
    field_definitions: dict[str, tuple[Any, FieldInfo]] = {}
    encoders: dict[str, Callable[[Any], Any]] = {}
    decoders: dict[str, Callable[[Any], Any]] = {}
    retyped: dict[str, Any] = {}  # field -> override annotation (for ref re-derivation)
    for field_name in surviving:
        info = copy.deepcopy(cls.model_fields[field_name])
        marker = _apply_field_spec(cls, field_name, expr, info)
        _record_field_payload(marker, field_name, retyped, encoders, decoders)
        heritage = Heritage(
            source=field_name,
            overridden=marker is not None,
            # info.description is now final; compare to the canonical's original
            description_inherited=(
                info.description == cls.model_fields[field_name].description
            ),
        )
        info.metadata = [
            *(m for m in info.metadata if not isinstance(m, PRISM_MARKERS)),
            heritage,
        ]
        info.annotation = _rewrite(info.annotation, expr, ctx)
        if partial:
            # Partial scope: every field becomes optional via the MISSING
            # sentinel (PATCH semantics — absent means "don't touch"). The
            # canonical's own nullability is preserved (a required field stays
            # non-nullable; an Optional one keeps None as a distinct value), and
            # canonical defaults are dropped: an absent field reads as MISSING
            # and is omitted from model_dump(), distinct from an explicit null.
            info.annotation = cast(Any, info.annotation | MISSING)
            info.default = MISSING
            info.default_factory = None
        field_definitions[field_name] = (info.annotation, info)

    model_config = copy.deepcopy(cls.model_config)
    _apply_model_schema(expr, model_config)
    if extra is not None:
        model_config["extra"] = extra
    config_base = types.new_class(
        f"_{class_name}Base",
        (*carried, Projection),
        exec_body=lambda ns: ns.update(
            model_config=model_config,
            __module__=cls.__module__,
        ),
    )
    projection = create_model(
        class_name,
        __base__=cast(type[Projection], config_base),
        __module__=cls.__module__,
        __doc__=f"Projection of {cls.__qualname__} to scope {expr!r}.",
        __validators__=_carry_validators(cls, set(surviving), expr),
        **cast(dict[str, Any], field_definitions),
    )
    projection.__prism_source__ = cls
    projection.__prism_scope__ = expr
    projection.__prism_bases__ = carried
    projection.__refs__ = _project_refs(cls, surviving, retyped)
    projection.__prism_encoders__ = encoders
    projection.__prism_decoders__ = decoders
    _copy_behaviors(cls, projection)
    del ctx.pending[key]
    ctx.built[key] = projection
    ctx.namespace[ref_name] = projection
    return projection


def _check_base_fields(
    cls: type[ScopedModel],
    expr: ScopeExpr,
    carried: tuple[type[BaseModel], ...],
    surviving: set[str],
) -> None:
    """Refuse projections that cannot honor a carried base field's scope tag.

    Fields declared on a carried base are inherited by the projection and
    cannot be removed; a ``scoped()`` tag the expression does not select
    would silently leak — fail loudly instead.
    """
    for base in carried:
        for field_name in base.model_fields:
            if field_name in cls.__field_scopes__ and field_name not in surviving:
                raise ProjectionBaseError(
                    f"{cls.__name__}.scope({expr!r}): field {field_name!r} is "
                    f"declared on carried base {base.__name__} and tagged "
                    f"scoped(...), but the expression does not select it; "
                    f"inherited fields cannot be removed from a projection — "
                    f"widen the expression, drop the base from bases=, or move "
                    f"the field onto {cls.__name__}"
                )


def _is_scoped_model_class(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, ScopedModel)


def _rewrite(annotation: Any, expr: ScopeExpr, ctx: _BuildContext) -> Any:
    """Propagate the scope into nested ScopedModel annotations, strip markers."""
    if _is_scoped_model_class(annotation):
        return _project(cast("type[ScopedModel]", annotation), expr, None, None, ctx)
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None:
        # nested Annotated cannot hold prism markers (rejected at collection
        # time), so the metadata survives verbatim
        inner = _rewrite(get_args(annotation)[0], expr, ctx)
        return Annotated[inner, *metadata]
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    args = get_args(annotation)
    if not args:
        return annotation
    new_args = tuple(
        [_rewrite(item, expr, ctx) for item in cast(list[Any], arg)]
        if isinstance(arg, list)  # Callable parameter lists
        else _rewrite(arg, expr, ctx)
        for arg in args
    )
    if new_args == args:
        return annotation
    if origin in (Union, types.UnionType):
        return Union[new_args]  # noqa: UP007 — args are only known at runtime
    return origin[new_args]


def _carry_validators(
    cls: type[ScopedModel], surviving: set[str], expr: ScopeExpr
) -> dict[str, Any] | None:
    """Re-target the canonical model's validators onto the projection.

    Field validators carry, re-targeted to the surviving subset. Plain
    ``@model_validator``s are intentionally *not* carried (they assume the full
    canonical field set); only those declared with ``@scoped_validator`` carry,
    and only onto projections whose ``expr`` selects the validator's scope tag.
    (Model validators declared on *carried bases* are inherited through the base
    itself, independently of this.)
    """
    carried: dict[str, Any] = {}
    for dec_name, decorator in cls.__pydantic_decorators__.field_validators.items():
        if "*" in decorator.info.fields:
            kept = ["*"]
        else:
            kept = [f for f in decorator.info.fields if f in surviving]
        if not kept:
            continue
        func: Any = decorator.func
        if inspect.ismethod(func):
            # decorator.func is the classmethod bound to the canonical class;
            # re-wrap the raw function as a fresh classmethod so pydantic's
            # signature inspection sees the canonical class-body form (a bound
            # method is mis-inspected on some Python versions, e.g. 3.12).
            func = classmethod(func.__func__)
        make = cast(Callable[..., Callable[[Any], Any]], field_validator)
        carried[dec_name] = make(
            kept[0], *kept[1:], mode=decorator.info.mode, check_fields=False
        )(func)
    for dec_name, decorator in cls.__pydantic_decorators__.model_validators.items():
        tag = cls.__prism_validator_scopes__.get(dec_name)
        if tag is None or not expr.selects(tag):
            continue
        func = decorator.func
        if inspect.ismethod(func):  # before/wrap: re-wrap as a fresh classmethod
            func = classmethod(func.__func__)
        make_model = cast(Callable[..., Callable[[Any], Any]], model_validator)
        carried[dec_name] = make_model(mode=decorator.info.mode)(func)
    return carried or None
