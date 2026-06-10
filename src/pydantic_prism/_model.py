"""ScopedModel, Projection, and the projection builder."""

from __future__ import annotations

import copy
import inspect
import threading
import types
import warnings
from collections.abc import Callable, Mapping, Sequence
from typing import (
    Annotated,
    Any,
    ClassVar,
    ForwardRef,
    Literal,
    Optional,
    Self,
    Union,
    cast,
    get_args,
    get_origin,
)

from pydantic import BaseModel, create_model, field_validator, model_validator
from pydantic.fields import FieldInfo

from ._markers import PRISM_MARKERS, BackRef, Ref, Scoped
from ._refs import Embedded, RawEdge, RefGraph, RefShape, shape_of
from ._scopes import Scope, ScopeExpr, ScopeLike, as_expr, union_all
from ._validators import (
    _SCOPED_VALIDATOR_SCOPES,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from .errors import EmptyProjectionError, ProjectionBaseError, ProjectionNameError

__all__ = ["Projection", "ScopedModel"]

# Sentinel: "no default_scope= keyword on this class definition". Distinct from
# None, which is a legitimate resolved value meaning "no default declared".
_NO_DEFAULT: Any = object()

# Cache key of one derived projection class: (expression, name override,
# carried bases). All three participate — changing any yields a new class.
type _ProjectionKey = tuple[ScopeExpr, str | None, tuple[type[BaseModel], ...]]


class Projection(BaseModel):
    """Base class of every model class derived by ``ScopedModel.scope(...)``.

    Projections are real pydantic models — validation, serialization, JSON
    schema, and FastAPI integration all work normally. They additionally
    carry where they came from (``__prism_source__``, ``__prism_scope__``,
    ``__prism_bases__``) and the surviving slice of the relationship graph
    (``__refs__``).
    """

    __prism_source__: ClassVar[type[ScopedModel]]
    __prism_scope__: ClassVar[ScopeExpr]
    __prism_bases__: ClassVar[tuple[type[BaseModel], ...]] = ()
    __refs__: ClassVar[RefGraph]

    @classmethod
    def from_canonical(
        cls,
        instance: BaseModel,
        *,
        mode: Literal["python", "json"] | str = "python",
        by_alias: bool = True,
        context: Any | None = None,
        exclude_none: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        narrow: bool | None = None,
    ) -> Self:
        """Build a projected instance from a canonical (or wider) instance.

        The instance is dumped via its own ``model_dump`` — the keyword
        arguments above are forwarded verbatim, with the same defaults pydantic
        uses except ``by_alias=True`` (so alias generators are honored on the
        round trip). ``context`` is also forwarded to ``model_validate``.

        Narrowing: when the dump has pydantic's standard shape, it is
        recursively narrowed to this projection's fields, so canonical-only
        fields are dropped at every nesting level (safe under
        ``extra="forbid"``). When the instance's class *overrides*
        ``model_dump`` (custom envelopes and the like), the dump is passed to
        ``model_validate`` verbatim — prism cannot understand a custom wire
        shape, but the validators carried from your base can. Pass ``narrow=``
        to override this auto-detection in either direction.
        """
        data: Any = instance.model_dump(
            mode=mode,
            by_alias=by_alias,
            context=context,
            exclude_none=exclude_none,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
        )
        if narrow is None:
            narrow = type(instance).model_dump is BaseModel.model_dump
        if narrow and isinstance(data, Mapping):
            data = _narrow(cls, cast(Mapping[str, Any], data))
        return cls.model_validate(data, context=context)


class ScopedModel(BaseModel):
    """Canonical pydantic model whose fields are tagged with scopes.

    Tag fields with ``scoped(...)`` (and optionally ``ref(...)`` /
    ``backref(...)``) inside ``Annotated`` metadata, then derive narrowed,
    fully functional model classes with :meth:`scope`.

    A model with a custom (non-``ScopedModel``) pydantic base can declare it
    as a *projection base* so projections inherit its behavior::

        class Row(AzureTableBase, ScopedModel, projection_bases=(AzureTableBase,)):
            ...

    See :meth:`scope` (``bases=``) for the per-call form.
    """

    __field_scopes__: ClassVar[dict[str, ScopeExpr]] = {}
    # The class-level default scope: the expression a field falls back to when
    # it carries no scoped(...) marker. None means "no default declared"; it is
    # inherited down the ScopedModel MRO like any class attribute and may be
    # re-declared (or cleared with default_scope=None) by a subclass.
    __prism_default_scope__: ClassVar[ScopeExpr | None] = None
    # Model validators declared with @scoped_validator, keyed by validator name,
    # mapped to the scope expression that decides which projections carry them.
    __prism_validator_scopes__: ClassVar[dict[str, ScopeExpr]] = {}
    # Template for auto-naming projections: format placeholders {model} and
    # {scope}. None means the built-in "{model}{scope}" form. Inherited down the
    # MRO; the call-site name= still overrides it.
    __prism_name_template__: ClassVar[str | None] = None
    __refs__: ClassVar[RefGraph]
    __prism_cache__: ClassVar[dict[_ProjectionKey, type[Projection]]] = {}
    __prism_names__: ClassVar[dict[str, _ProjectionKey]] = {}
    # None means "never declared" (inherited declarations stay visible);
    # an explicit empty tuple is a declaration and silences the drop warning.
    __prism_projection_bases__: ClassVar[tuple[type[BaseModel], ...] | None] = None
    __prism_base_warned__: ClassVar[bool] = False

    def __init_subclass__(
        cls,
        projection_bases: Sequence[type[BaseModel]] | None = None,
        default_scope: ScopeLike | None = _NO_DEFAULT,
        projection_name_template: str | None = _NO_DEFAULT,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if projection_bases is not None:
            cls.__prism_projection_bases__ = _check_bases(
                cast("type[ScopedModel]", cls), projection_bases
            )
        if default_scope is not _NO_DEFAULT:
            # Validate eagerly (TypeError for a non-Scope value) at class
            # definition; default_scope=None explicitly clears an inherited
            # default. Setting the attribute on this class shadows the
            # inherited one; leaving the keyword off lets the MRO supply it.
            cls.__prism_default_scope__ = (
                as_expr(default_scope) if default_scope is not None else None
            )
        if projection_name_template is not _NO_DEFAULT:
            if projection_name_template is not None:
                _validate_name_template(
                    cast("type[ScopedModel]", cls), projection_name_template
                )
            cls.__prism_name_template__ = projection_name_template

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
    def scopes(cls) -> frozenset[type[Scope]]:
        """The Scope classes appearing in this model's field tags."""
        out: set[type[Scope]] = set()
        for expr in cls.__field_scopes__.values():
            out |= expr.atoms()
        return frozenset(out)

    @classmethod
    def scope(
        cls,
        *scopes: ScopeLike,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
    ) -> type[Projection]:
        """Derive (or fetch from cache) the projection for a scope expression.

        Multiple arguments union: ``Model.scope(A, B)`` is ``Model.scope(A | B)``.
        The same expression always returns the same class object. ``name=``
        overrides the auto-generated class name and is part of the cache key.

        ``bases=`` lists non-``ScopedModel`` ancestors of this model to carry
        onto the projection (restoring their custom ``model_dump``/
        ``model_validate``, model validators/serializers, methods, and
        ``isinstance`` identity). It defaults to the class-level
        ``projection_bases=`` declaration and participates in the cache key;
        ``bases=()`` opts out explicitly. Fields *declared on a carried base*
        are inherited by every projection (pydantic cannot remove inherited
        fields) — tagging such a field with a scope the projection does not
        select raises :class:`ProjectionBaseError`.
        """
        if not scopes:
            raise TypeError("scope() requires at least one scope or scope expression")
        expr = union_all(as_expr(scope) for scope in scopes)
        checked = _check_bases(cls, bases) if bases is not None else None
        carried = (
            checked if checked is not None else (cls.__prism_projection_bases__ or ())
        )
        cached = cls.__prism_cache__.get((expr, name, carried))
        if cached is not None:
            return cached
        # Build under a lock so concurrent first calls (free-threaded Python,
        # threaded servers) cannot produce two classes for one expression.
        with _build_lock:
            cached = cls.__prism_cache__.get((expr, name, carried))
            if cached is not None:
                return cached
            ctx = _BuildContext()
            projection = _project(cls, expr, name, checked, ctx)
            assert isinstance(projection, type)  # top-level call is never pending
            # Resolve cycle ForwardRefs first, commit second: the caches only
            # ever hold fully built classes (which keeps the lock-free fast
            # path above safe), and a failed build commits nothing.
            for built in ctx.built.values():
                built.model_rebuild(_types_namespace=ctx.namespace)
            for (owner, *owner_key), built in ctx.built.items():
                key = cast(_ProjectionKey, tuple(owner_key))
                owner.__prism_cache__[key] = built
                owner.__prism_names__[built.__name__] = key
            return projection

    @classmethod
    def from_projection(cls, projection: BaseModel, /, **extra: Any) -> Self:
        """Build a canonical instance from a (non-partial) projected one.

        Fields the projection lacks must arrive via ``**extra`` (keyed by
        python field name, or carry defaults on the canonical model).

        This is the round-trip for a *complete* projection. A **partial**
        projection (from a ``partial=True`` scope) is a delta, not a record —
        building a standalone canonical from it has no meaning without a
        baseline. Apply it to one with :meth:`with_updates` instead; passing a
        partial projection here raises :class:`TypeError`.
        """
        if (
            isinstance(projection, Projection)
            and projection.__prism_scope__.is_partial()
        ):
            raise TypeError(
                f"{cls.__name__}.from_projection() received a partial projection "
                f"({type(projection).__name__}); a partial scope is a delta, not a "
                f"complete record. Apply it to a baseline with "
                f"baseline.with_updates({type(projection).__name__.lower()}), or "
                f"build from a non-partial projection of {cls.__name__}"
            )
        data = dict(projection.model_dump(by_alias=True))
        for key, value in extra.items():
            info = cls.model_fields.get(key)
            data[_validation_key(key, info) if info else key] = value
        return cls.model_validate(data)

    def with_updates(self, patch: Projection, /) -> Self:
        """Apply a (partial) projection's set fields onto a copy of this instance.

        The PATCH counterpart to ``from_canonical``: takes the fields explicitly
        set on ``patch`` (``model_dump(exclude_unset=True)`` — absent means
        "don't touch", an explicit ``None`` clears the field) and returns a new,
        **re-validated** instance with them overlaid. Re-validation reconstructs
        nested models and runs the canonical model's validators, so the result
        is a valid instance — unlike a bare ``model_copy(update=...)``, which
        would leave nested fields as raw dicts.

        ``patch`` must be a projection of this model (any scope, though partial
        Update projections are the usual source); a projection of a different
        model raises :class:`TypeError`. ``self`` is left unchanged.
        """
        source = getattr(patch, "__prism_source__", None)
        if not (isinstance(source, type) and isinstance(self, source)):
            raise TypeError(
                f"{type(self).__name__}.with_updates() expects a projection of "
                f"{type(self).__name__}; got {type(patch).__name__}"
                + (
                    f" (a projection of {source.__name__})"
                    if isinstance(source, type)
                    else ""
                )
            )
        merged = {
            **self.model_dump(by_alias=True),
            **patch.model_dump(by_alias=True, exclude_unset=True),
        }
        return type(self).model_validate(merged)


ScopedModel.__refs__ = RefGraph(ScopedModel, {})

# RLock: _project recurses for nested models within one build.
_build_lock = threading.RLock()

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
        warnings.warn(message, UserWarning, stacklevel=2)


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


class _BuildContext:
    """State for one top-level ``scope()`` call, threading through recursion."""

    def __init__(self) -> None:
        # key -> ForwardRef/namespace name, while the class is being built
        self.pending: dict[tuple[type[ScopedModel], Any, Any, Any], str] = {}
        # key -> finished (but not yet rebuilt/committed) class
        self.built: dict[tuple[type[ScopedModel], Any, Any, Any], type[Projection]] = {}
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


def _project(
    cls: type[ScopedModel],
    expr: ScopeExpr,
    name: str | None,
    bases: tuple[type[BaseModel], ...] | None,
    ctx: _BuildContext,
) -> type[Projection] | ForwardRef:
    if not cls.__pydantic_complete__:
        # Unresolved forward references would make markers invisible and the
        # projection silently wrong; resolve now (raises pydantic's clear
        # error if names are genuinely missing) and refresh marker collection
        # via the model_rebuild override.
        cls.model_rebuild()
    carried = _resolve_carried(cls, bases)
    cache_key: _ProjectionKey = (expr, name, carried)
    cached = cls.__prism_cache__.get(cache_key)
    if cached is not None:
        return cached
    key = (cls, expr, name, carried)
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
    for field_name in surviving:
        info = copy.deepcopy(cls.model_fields[field_name])
        _apply_field_schema(cls, field_name, expr, info)
        info.metadata = [m for m in info.metadata if not isinstance(m, PRISM_MARKERS)]
        info.annotation = _rewrite(info.annotation, expr, ctx)
        if partial:
            # Partial scope: every field optional, default None, canonical
            # defaults dropped (PATCH semantics: absent means "don't touch").
            info.annotation = cast(Any, Optional[info.annotation])  # noqa: UP045 — runtime types
            info.default = None
            info.default_factory = None
        field_definitions[field_name] = (info.annotation, info)

    model_config = copy.deepcopy(cls.model_config)
    _apply_model_schema(expr, model_config)
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
    projection.__refs__ = cls.__refs__.filtered(surviving)
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


# --- scope-attached JSON schema --------------------------------------------


def _merge_json_schema_extra(original: Any, extra: dict[str, Any]) -> Any:
    """Merge ``extra`` onto an existing ``json_schema_extra`` (dict or callable)."""
    if callable(original):

        def merged(*args: Any) -> None:
            original(*args)
            args[0].update(extra)  # args[0] is the schema dict in every arity

        return merged
    base = dict(original or {})
    base.update(extra)
    return base


def _resolve_field_schema(
    cls: type[ScopedModel], field_name: str, expr: ScopeExpr
) -> Mapping[str, Any] | None:
    """The per-scope field schema that applies in projection ``expr``, if any.

    Markers whose scope ``expr`` selects are candidates; the most-derived scope
    (a subclass of every other candidate) wins. Candidates with no subclass
    relation are ambiguous and raise.
    """
    candidates: list[tuple[type[Scope], Mapping[str, Any]]] = []
    for marker in cls.model_fields[field_name].metadata:
        if (
            isinstance(marker, Scoped)
            and marker.field_schema is not None
            and expr.selects(marker.expr)
        ):
            scope = next(iter(marker.expr.atoms()))  # single atom (enforced)
            candidates.append((scope, marker.field_schema))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]
    scopes = [scope for scope, _ in candidates]
    for scope, schema in candidates:
        if all(issubclass(scope, other) for other in scopes):
            return schema
    names = ", ".join(sorted(scope.__name__ for scope in scopes))
    raise TypeError(
        f"{cls.__name__}.{field_name}: ambiguous scoped() schema in projection "
        f"{expr!r}; scopes {names} all apply and are unrelated — attach the schema "
        f"to a single common scope or narrow the projection"
    )


def _apply_field_schema(
    cls: type[ScopedModel], field_name: str, expr: ScopeExpr, info: FieldInfo
) -> None:
    """Overlay the resolved per-scope field schema onto a projected ``FieldInfo``."""
    schema = _resolve_field_schema(cls, field_name, expr)
    if schema is None:
        return
    if "description" in schema:
        info.description = schema["description"]
    if "examples" in schema:
        info.examples = list(schema["examples"])
    if "json_schema_extra" in schema:
        info.json_schema_extra = _merge_json_schema_extra(
            info.json_schema_extra, schema["json_schema_extra"]
        )


def _apply_model_schema(expr: ScopeExpr, model_config: Any) -> None:
    """Merge the model-level schema of ``expr``'s scopes into ``model_config``."""
    extra: dict[str, Any] = {}
    for atom in sorted(expr.atoms(), key=lambda scope: scope.__name__):
        schema = vars(atom).get("__prism_model_schema__")
        if not schema:
            continue
        if "description" in schema:
            extra["description"] = schema["description"]
        if "examples" in schema:
            extra["examples"] = list(schema["examples"])
        if "json_schema_extra" in schema:
            extra.update(schema["json_schema_extra"])
    if extra:
        model_config["json_schema_extra"] = _merge_json_schema_extra(
            model_config.get("json_schema_extra"), extra
        )


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
