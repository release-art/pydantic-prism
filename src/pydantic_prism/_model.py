"""ScopedModel, Projection, and the projection builder."""

from __future__ import annotations

import copy
import threading
import types
from collections.abc import Callable
from typing import (
    Annotated,
    Any,
    ClassVar,
    ForwardRef,
    Self,
    Union,
    cast,
    get_args,
    get_origin,
)

from pydantic import BaseModel, create_model, field_validator
from pydantic.fields import FieldInfo

from ._markers import PRISM_MARKERS, BackRef, Ref, Scoped
from ._refs import RefGraph, cardinality
from ._scopes import ScopeExpr, ScopeLike, as_expr, union_all
from .errors import EmptyProjectionError

__all__ = ["Projection", "ScopedModel"]


class Projection(BaseModel):
    """Base class of every model class derived by ``ScopedModel.scope(...)``.

    Projections are real pydantic models — validation, serialization, JSON
    schema, and FastAPI integration all work normally. They additionally
    carry where they came from (``__prism_source__``, ``__prism_scope__``)
    and the surviving slice of the relationship graph (``__refs__``).
    """

    __prism_source__: ClassVar[type[ScopedModel]]
    __prism_scope__: ClassVar[ScopeExpr]
    __refs__: ClassVar[RefGraph]

    @classmethod
    def from_canonical(cls, instance: BaseModel) -> Self:
        """Build a projected instance from a canonical (or wider) instance.

        Fields outside this projection are dropped; nested ScopedModels are
        re-validated into their projected counterparts.
        """
        data = instance.model_dump()
        return cls.model_validate(
            {name: value for name, value in data.items() if name in cls.model_fields}
        )


class ScopedModel(BaseModel):
    """Canonical pydantic model whose fields are tagged with scopes.

    Tag fields with ``scoped(...)`` (and optionally ``ref(...)`` /
    ``backref(...)``) inside ``Annotated`` metadata, then derive narrowed,
    fully functional model classes with :meth:`scope`.
    """

    __field_scopes__: ClassVar[dict[str, ScopeExpr]] = {}
    __refs__: ClassVar[RefGraph]
    __prism_cache__: ClassVar[dict[tuple[ScopeExpr, str | None], type[Projection]]] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        cls.__prism_cache__ = {}
        _initialize(cls)

    @classmethod
    def scope(cls, *scopes: ScopeLike, name: str | None = None) -> type[Projection]:
        """Derive (or fetch from cache) the projection for a scope expression.

        Multiple arguments union: ``Model.scope(A, B)`` is ``Model.scope(A | B)``.
        The same expression always returns the same class object. ``name=``
        overrides the auto-generated class name and is part of the cache key.
        """
        if not scopes:
            raise TypeError("scope() requires at least one scope or scope expression")
        expr = union_all(as_expr(scope) for scope in scopes)
        cached = cls.__prism_cache__.get((expr, name))
        if cached is not None:
            return cached
        # Build under a lock so concurrent first calls (free-threaded Python,
        # threaded servers) cannot produce two classes for one expression.
        with _build_lock:
            ctx = _BuildContext()
            projection = _project(cls, expr, name, ctx)
            assert isinstance(projection, type)  # top-level call is never pending
            namespace = cast(dict[str, Any], dict(ctx.created))
            for built in ctx.created.values():
                built.model_rebuild(raise_errors=False, _types_namespace=namespace)
            return projection

    @classmethod
    def from_projection(cls, projection: BaseModel, /, **extra: Any) -> Self:
        """Build a canonical instance from a projected one.

        Fields the projection lacks must arrive via ``**extra`` (or carry
        defaults on the canonical model).
        """
        return cls.model_validate({**projection.model_dump(), **extra})


ScopedModel.__refs__ = RefGraph(ScopedModel, {})

# RLock: _project recurses for nested models within one build.
_build_lock = threading.RLock()


def _initialize(cls: type[ScopedModel]) -> None:
    """Collect markers, validate structure, set up scopes/refs for a subclass."""
    field_scopes: dict[str, ScopeExpr] = {}
    raw_refs: dict[str, tuple[Ref | BackRef, bool, bool]] = {}
    needs_rebuild = False
    for field_name, info in cls.model_fields.items():
        if isinstance(info.default, PRISM_MARKERS):
            raise TypeError(
                f"{cls.__name__}.{field_name}: {type(info.default).__name__} marker "
                f"used as a field default; prism markers go inside Annotated[...] "
                f"metadata, e.g. Annotated[str, scoped(...)]"
            )
        scope_markers = [m for m in info.metadata if isinstance(m, Scoped)]
        ref_markers = [m for m in info.metadata if isinstance(m, (Ref, BackRef))]
        if scope_markers:
            field_scopes[field_name] = union_all(m.expr for m in scope_markers)
        if len(ref_markers) > 1:
            raise TypeError(
                f"{cls.__name__}.{field_name}: at most one ref()/backref() marker "
                f"is allowed per field"
            )
        if ref_markers:
            many, optional = cardinality(info.annotation)
            raw_refs[field_name] = (ref_markers[0], many, optional)
            if isinstance(ref_markers[0], BackRef) and info.is_required():
                needs_rebuild = _imply_backref_default(info, many, optional)
    cls.__field_scopes__ = field_scopes
    cls.__refs__ = RefGraph(cls, raw_refs)
    if needs_rebuild:
        cls.model_rebuild(force=True, raise_errors=False)


def _imply_backref_default(info: FieldInfo, many: bool, optional: bool) -> bool:
    """Give a required backref field its implied empty default."""
    if many:
        annotation = info.annotation
        while hasattr(annotation, "__metadata__"):
            annotation = get_args(annotation)[0]
        origin = get_origin(annotation)
        containers = (list, set, frozenset, tuple)
        info.default_factory = origin if origin in containers else list
        return True
    if optional:
        info.default = None
        return True
    return False


class _BuildContext:
    """State for one top-level ``scope()`` call, threading through recursion."""

    def __init__(self) -> None:
        self.pending: dict[tuple[type[ScopedModel], ScopeExpr, str | None], str] = {}
        self.created: dict[str, type[Projection]] = {}


def _project(
    cls: type[ScopedModel],
    expr: ScopeExpr,
    name: str | None,
    ctx: _BuildContext,
) -> type[Projection] | ForwardRef:
    cache_key = (expr, name)
    cached = cls.__prism_cache__.get(cache_key)
    if cached is not None:
        return cached
    pending_key = (cls, expr, name)
    if pending_key in ctx.pending:
        # Cycle: refer to the in-flight class by name, resolved by the
        # model_rebuild pass once every class in this context exists.
        return ForwardRef(ctx.pending[pending_key])
    class_name = name if name is not None else f"{cls.__name__}{expr.token()}"
    ctx.pending[pending_key] = class_name

    surviving = [
        field_name
        for field_name in cls.model_fields
        if field_name in cls.__field_scopes__ and expr.selects(cls.__field_scopes__[field_name])
    ]
    if not surviving:
        raise EmptyProjectionError(
            f"{cls.__name__}.scope({expr!r}) selects no fields; untagged fields belong to no scope"
        )

    field_definitions: dict[str, tuple[Any, FieldInfo]] = {}
    for field_name in surviving:
        info = copy.deepcopy(cls.model_fields[field_name])
        info.metadata = [m for m in info.metadata if not isinstance(m, PRISM_MARKERS)]
        info.annotation = _rewrite(info.annotation, expr, ctx)
        field_definitions[field_name] = (info.annotation, info)

    config_base = types.new_class(
        f"_{class_name}Base",
        (Projection,),
        exec_body=lambda ns: ns.update(
            model_config=copy.deepcopy(cls.model_config),
            __module__=cls.__module__,
        ),
    )
    projection = create_model(
        class_name,
        __base__=cast(type[Projection], config_base),
        __module__=cls.__module__,
        __doc__=f"Projection of {cls.__qualname__} to scope {expr!r}.",
        __validators__=_carry_validators(cls, set(surviving)),
        **cast(dict[str, Any], field_definitions),
    )
    projection.__prism_source__ = cls
    projection.__prism_scope__ = expr
    projection.__refs__ = cls.__refs__.filtered(surviving)
    ctx.created[class_name] = projection
    cls.__prism_cache__[cache_key] = projection
    return projection


def _is_scoped_model_class(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, ScopedModel)


def _rewrite(annotation: Any, expr: ScopeExpr, ctx: _BuildContext) -> Any:
    """Propagate the scope into nested ScopedModel annotations, strip markers."""
    if _is_scoped_model_class(annotation):
        return _project(cast("type[ScopedModel]", annotation), expr, None, ctx)
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None:
        inner = _rewrite(get_args(annotation)[0], expr, ctx)
        kept = [m for m in metadata if not isinstance(m, PRISM_MARKERS)]
        if not kept:
            return inner
        return Annotated[inner, *kept]
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    args = get_args(annotation)
    if not args:
        return annotation
    new_args = tuple(_rewrite(arg, expr, ctx) for arg in args)
    if new_args == args:
        return annotation
    if origin in (Union, types.UnionType):
        return Union[new_args]  # noqa: UP007 — args are only known at runtime
    return origin[new_args]


def _carry_validators(cls: type[ScopedModel], surviving: set[str]) -> dict[str, Any] | None:
    """Re-target the canonical model's field validators onto surviving fields.

    Model validators are intentionally not carried over: they assume the full
    canonical field set.
    """
    carried: dict[str, Any] = {}
    for dec_name, decorator in cls.__pydantic_decorators__.field_validators.items():
        if "*" in decorator.info.fields:
            kept = ["*"]
        else:
            kept = [f for f in decorator.info.fields if f in surviving]
        if not kept:
            continue
        make = cast(Callable[..., Callable[[Any], Any]], field_validator)
        carried[dec_name] = make(kept[0], *kept[1:], mode=decorator.info.mode, check_fields=False)(
            decorator.func
        )
    return carried or None
