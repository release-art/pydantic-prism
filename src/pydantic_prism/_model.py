"""ScopedModel, Projection, and the projection builder."""

from __future__ import annotations

import copy
import inspect
import threading
import types
from collections.abc import Callable, Mapping
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
from .errors import EmptyProjectionError, ProjectionNameError

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

        The instance is dumped with aliases and recursively narrowed to this
        projection's fields, so canonical-only fields are dropped at every
        nesting level (safe under ``extra="forbid"``) and alias generators
        are honored.
        """
        return cls.model_validate(_narrow(cls, instance.model_dump(by_alias=True)))


class ScopedModel(BaseModel):
    """Canonical pydantic model whose fields are tagged with scopes.

    Tag fields with ``scoped(...)`` (and optionally ``ref(...)`` /
    ``backref(...)``) inside ``Annotated`` metadata, then derive narrowed,
    fully functional model classes with :meth:`scope`.
    """

    __field_scopes__: ClassVar[dict[str, ScopeExpr]] = {}
    __refs__: ClassVar[RefGraph]
    __prism_cache__: ClassVar[dict[tuple[ScopeExpr, str | None], type[Projection]]] = {}
    __prism_names__: ClassVar[dict[str, tuple[ScopeExpr, str | None]]] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        cls.__prism_cache__ = {}
        cls.__prism_names__ = {}
        _initialize(cls)

    @classmethod
    def model_rebuild(
        cls,
        *,
        force: bool = False,
        raise_errors: bool = True,
        _parent_namespace_depth: int = 2,
        _types_namespace: Any = None,
    ) -> bool | None:
        """Rebuild the model, then refresh prism's marker collection.

        The refresh matters when annotations were unresolved forward
        references at class-definition time: their ``scoped()``/``ref()``
        markers only become visible once the rebuild evaluates them.
        """
        result = super().model_rebuild(
            force=force,
            raise_errors=raise_errors,
            # +1: this override adds one frame between pydantic and the caller.
            _parent_namespace_depth=_parent_namespace_depth + 1,
            _types_namespace=_types_namespace,
        )
        if result:
            _collect(cls)
        return result

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
            cached = cls.__prism_cache__.get((expr, name))
            if cached is not None:
                return cached
            ctx = _BuildContext()
            projection = _project(cls, expr, name, ctx)
            assert isinstance(projection, type)  # top-level call is never pending
            # Resolve cycle ForwardRefs first, commit second: the caches only
            # ever hold fully built classes (which keeps the lock-free fast
            # path above safe), and a failed build commits nothing.
            for built in ctx.built.values():
                built.model_rebuild(_types_namespace=ctx.namespace)
            for (owner, owner_expr, owner_name), built in ctx.built.items():
                owner.__prism_cache__[(owner_expr, owner_name)] = built
                owner.__prism_names__[built.__name__] = (owner_expr, owner_name)
            return projection

    @classmethod
    def from_projection(cls, projection: BaseModel, /, **extra: Any) -> Self:
        """Build a canonical instance from a projected one.

        Fields the projection lacks must arrive via ``**extra`` (keyed by
        python field name, or carry defaults on the canonical model).
        """
        data = dict(projection.model_dump(by_alias=True))
        for key, value in extra.items():
            info = cls.model_fields.get(key)
            data[_validation_key(key, info) if info else key] = value
        return cls.model_validate(data)


ScopedModel.__refs__ = RefGraph(ScopedModel, {})

# RLock: _project recurses for nested models within one build.
_build_lock = threading.RLock()


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
    raw_refs: dict[str, tuple[Ref | BackRef, bool, bool]] = {}
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
            field_scopes[field_name] = union_all(m.expr for m in scope_markers)
        if len(ref_markers) > 1:
            raise TypeError(
                f"{cls.__name__}.{field_name}: at most one ref()/backref() marker "
                f"is allowed per field"
            )
        if ref_markers:
            many, optional = cardinality(info.annotation)
            raw_refs[field_name] = (ref_markers[0], many, optional)
    cls.__field_scopes__ = field_scopes
    existing = cls.__dict__.get("__refs__")
    if isinstance(existing, RefGraph):
        # Mutate in place so graphs already held by user code stay current.
        existing._reset(raw_refs)  # pyright: ignore[reportPrivateUsage] — intra-package
    else:
        cls.__refs__ = RefGraph(cls, raw_refs)


def _reject_nested_markers(cls: type[ScopedModel], field_name: str, annotation: Any) -> None:
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
        many, optional = cardinality(info.annotation)
        if many:
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
    if origin in (list, set, frozenset):
        return cast(type[Any], origin)
    if origin is tuple:
        args = get_args(annotation)
        if args and args[-1] is Ellipsis:
            return tuple
    return None


class _BuildContext:
    """State for one top-level ``scope()`` call, threading through recursion."""

    def __init__(self) -> None:
        # key -> ForwardRef/namespace name, while the class is being built
        self.pending: dict[tuple[type[ScopedModel], ScopeExpr, str | None], str] = {}
        # key -> finished (but not yet rebuilt/committed) class
        self.built: dict[tuple[type[ScopedModel], ScopeExpr, str | None], type[Projection]] = {}
        # ForwardRef name -> class; names are unique even when class names collide
        self.namespace: dict[str, type[Projection]] = {}

    def reserve_name(self, base: str) -> str:
        candidate = base
        suffix = 1
        while candidate in self.namespace or candidate in self.pending.values():
            suffix += 1
            candidate = f"{base}__{suffix}"
        return candidate


def _project(
    cls: type[ScopedModel],
    expr: ScopeExpr,
    name: str | None,
    ctx: _BuildContext,
) -> type[Projection] | ForwardRef:
    if not cls.__pydantic_complete__:
        # Unresolved forward references would make markers invisible and the
        # projection silently wrong; resolve now (raises pydantic's clear
        # error if names are genuinely missing) and refresh marker collection
        # via the model_rebuild override.
        cls.model_rebuild()
    cached = cls.__prism_cache__.get((expr, name))
    if cached is not None:
        return cached
    key = (cls, expr, name)
    if key in ctx.built:
        return ctx.built[key]
    if key in ctx.pending:
        # Cycle: refer to the in-flight class by its reserved namespace name,
        # resolved by the rebuild pass once every class in this context exists.
        return ForwardRef(ctx.pending[key])
    class_name = name if name is not None else f"{cls.__name__}{expr.token()}"
    registered = cls.__prism_names__.get(class_name)
    if registered is not None and registered != (expr, name):
        raise ProjectionNameError(
            f"{cls.__name__} already has a projection named {class_name!r} for a "
            f"different scope expression; pass name= to disambiguate"
        )
    ref_name = ctx.reserve_name(class_name)
    ctx.pending[key] = ref_name

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
    del ctx.pending[key]
    ctx.built[key] = projection
    ctx.namespace[ref_name] = projection
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
        func: Any = decorator.func
        if inspect.ismethod(func):
            # decorator.func is the classmethod bound to the canonical class;
            # re-wrap the raw function as a fresh classmethod so pydantic's
            # signature inspection sees the canonical class-body form (a bound
            # method is mis-inspected on some Python versions, e.g. 3.12).
            func = classmethod(func.__func__)
        make = cast(Callable[..., Callable[[Any], Any]], field_validator)
        carried[dec_name] = make(kept[0], *kept[1:], mode=decorator.info.mode, check_fields=False)(
            func
        )
    return carried or None


def _validation_key(name: str, info: FieldInfo | None) -> str:
    """The key a field expects in validation input (alias-aware)."""
    if info is None:
        return name
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
        models = [a for a in args if isinstance(a, type) and issubclass(a, BaseModel)]
        if len(models) == 1 and isinstance(value, Mapping):
            return _narrow(models[0], cast(Mapping[str, Any], value))
        return value
    if isinstance(origin, type) and issubclass(origin, Mapping):
        if len(args) == 2 and isinstance(value, Mapping):
            items = cast(Mapping[Any, Any], value)
            return {k: _narrow_value(args[1], v) for k, v in items.items()}
        return value
    if origin in (list, set, frozenset) and args and isinstance(value, (list, set, frozenset)):
        return [_narrow_value(args[0], item) for item in cast(list[Any], value)]
    if origin is tuple and args and isinstance(value, (list, tuple)):
        items = list(cast(list[Any], value))
        if len(args) == 2 and args[1] is Ellipsis:
            return [_narrow_value(args[0], item) for item in items]
        return [_narrow_value(arg, item) for arg, item in zip(args, items, strict=False)]
    return value
