"""The public ``Projection`` and ``ScopedModel`` classes.

The class methods lazy-import the collection / build / narrow / bases helpers
from sibling modules: those helpers import these classes at module level, so the
classes must defer their own imports to call time to break the cycle.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast

from pydantic import BaseModel

from ..refs import RefGraph
from ..scopes import (
    Classification,
    In,
    Out,
    Scope,
    ScopeExpr,
    ScopeLike,
    as_expr,
    union_all,
)

if TYPE_CHECKING:
    from ..flow import FlowReport

__all__ = ["Projection", "ScopedModel"]

# Sentinel: "no default_scope= keyword on this class definition". Distinct from
# None, which is a legitimate resolved value meaning "no default declared".
_NO_DEFAULT: Any = object()

# Cache key of one derived projection class: (expression, name override,
# carried bases, extra-config override). All four participate — changing any
# yields a new class. ``extra`` is None for plain scope()/output() (inherit the
# canonical's config) and "forbid" for input(); it keeps an input() projection a
# distinct, separately-named class from the equivalent bare scope().
type _ProjectionKey = tuple[
    ScopeExpr, str | None, tuple[type[BaseModel], ...], str | None
]

# RLock: _project recurses for nested models within one build.
_build_lock = threading.RLock()


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
        from .narrow import _narrow

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
        from .bases import _check_bases
        from .build import _validate_name_template

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
        from .collect import _initialize

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
        from .collect import _collect

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
    def classifications(cls) -> frozenset[type[Classification]]:
        """The :class:`Classification` atoms appearing in this model's field tags.

        The classification slice of :meth:`scopes` — visibility scopes excluded.
        """
        return frozenset(s for s in cls.scopes() if issubclass(s, Classification))

    @classmethod
    def classified_fields(cls) -> dict[str, frozenset[type[Classification]]]:
        """Per-field classification inventory: field name → classifications carried.

        Only fields tagged with at least one :class:`Classification` appear. The
        classifications are read directly off each field's tag (its expression
        atoms); visibility scopes and untagged fields are omitted.
        """
        out: dict[str, frozenset[type[Classification]]] = {}
        for field_name, expr in cls.__field_scopes__.items():
            tags = frozenset(a for a in expr.atoms() if issubclass(a, Classification))
            if tags:
                out[field_name] = tags
        return out

    @classmethod
    def classified_flow(cls) -> FlowReport:
        """Trace classified data reachable from this model across the ref graph.

        Walks forward ``ref`` / ``embedded`` edges (BFS, cycle-safe) and reports
        the classified fields of every model personal data can reach — the
        compliance artifact: *given this entry point, where does classified data
        live, via which references?* Render the returned :class:`.FlowReport`
        with ``.as_dict()`` (JSON) or ``.to_mermaid()``.
        """
        from ..flow import build_flow_report

        return build_flow_report(cls)

    @classmethod
    def redacted(
        cls,
        *visible: ScopeLike,
        strip: ScopeLike | None = None,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
    ) -> type[Projection]:
        """Derive an audit-safe projection: the ``visible`` view, classified out.

        Redaction is set difference. ``Model.redacted(Internal)`` is the
        ``Internal`` projection with **every classification stripped** — by
        default ``strip`` is the union of all classifications declared on the
        model, so a classification added later is auto-redacted. Pass ``strip=``
        (any scope expression, e.g. ``Secret`` or ``Pii | Secret``) to choose
        which classifications to remove instead. Refs survive, so the
        relationship graph stays intact.

        ``name`` / ``bases`` forward to :meth:`scope`.
        """
        if not visible:
            raise TypeError(
                "redacted() requires at least one visibility scope or expression"
            )
        visible_expr = union_all(as_expr(scope) for scope in visible)
        if strip is not None:
            strip_expr: ScopeExpr | None = as_expr(strip)
        else:
            classifications = cls.classifications()
            strip_expr = (
                union_all(as_expr(c) for c in classifications)
                if classifications
                else None
            )
        expr = visible_expr if strip_expr is None else visible_expr - strip_expr
        return cls.scope(expr, name=name, bases=bases)

    @classmethod
    def _directional_expr(
        cls, visible: tuple[ScopeLike, ...], drop: type[Scope]
    ) -> ScopeExpr:
        """The visibility expression for ``input``/``output``, minus a direction.

        ``visible`` defaults to the model's ``default_scope=`` when empty (the
        direction-only case — tag fields ``In``/``Out``/both and let the
        read-write majority fall back); with no default and no argument it
        raises, mirroring :meth:`redacted`.
        """
        if visible:
            base = union_all(as_expr(scope) for scope in visible)
        elif cls.__prism_default_scope__ is not None:
            base = cls.__prism_default_scope__
        else:
            raise TypeError(
                f"{cls.__name__}.{'input' if drop is Out else 'output'}() requires at "
                f"least one visibility scope, or a default_scope= on the model"
            )
        return base - drop

    @classmethod
    def input(  # noqa: A003 — `input`/`output` name the read/write sides on purpose
        cls,
        *visible: ScopeLike,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
        extra: Literal["allow", "ignore", "forbid"] = "forbid",
    ) -> type[Projection]:
        """The write-side projection: the ``visible`` view minus read-only fields.

        Mass-assignment protection *by shape*: a read-only field (tagged
        ``scoped(..., Out)``) is simply absent from this projection, so it can
        never be over-posted. The subtraction is ``union(visible) - Out`` and it
        is **deep** — nested ``ScopedModel`` fields are projected the same way, so
        read-only fields drop at every level.

        ``extra`` defaults to ``"forbid"``: unknown keys are rejected outright
        (a loud 422 rather than a silent drop, and the only thing that closes the
        hole when the canonical declares ``extra="allow"``). It applies to the
        top-level projection; nest ``input()`` on a field's model for deep
        ``forbid``. Pass ``extra="ignore"``/``"allow"`` to opt out. ``name``
        defaults to ``"{Model}In"``; ``visible`` falls back to the model's
        ``default_scope=`` when omitted. ``name``/``bases`` forward to
        :meth:`scope`.
        """
        expr = cls._directional_expr(visible, Out)
        return cls._build_projection(expr, name or f"{cls.__name__}In", bases, extra)

    @classmethod
    def output(
        cls,
        *visible: ScopeLike,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
    ) -> type[Projection]:
        """The read-side projection: the ``visible`` view minus write-only fields.

        The response counterpart to :meth:`input`: a write-only field (tagged
        ``scoped(..., In)``, e.g. a password) is absent, so it is never echoed
        back. The subtraction is ``union(visible) - In``; like ``input`` it is
        deep through nested ``ScopedModel`` fields. ``extra`` is left untouched
        (server→client; over-posting does not apply). ``name`` defaults to
        ``"{Model}Out"``; ``visible`` falls back to the model's ``default_scope=``
        when omitted. ``name``/``bases`` forward to :meth:`scope`.
        """
        expr = cls._directional_expr(visible, In)
        return cls._build_projection(expr, name or f"{cls.__name__}Out", bases, None)

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
        return cls._build_projection(expr, name, bases, None)

    @classmethod
    def _build_projection(
        cls,
        expr: ScopeExpr,
        name: str | None,
        bases: Sequence[type[BaseModel]] | None,
        extra: Literal["allow", "ignore", "forbid"] | None,
    ) -> type[Projection]:
        """The cached, locked build shared by scope()/input()/output().

        ``extra`` overrides the projection's ``model_config["extra"]`` (None
        inherits the canonical's) and is part of the cache key, so an input()
        projection is a distinct class from the equivalent bare scope(). It is
        kept off scope()'s public signature: a config-forked class must carry a
        distinct name, which input()/output() supply ("{Model}In"/"{Model}Out").
        """
        from .bases import _check_bases
        from .build import _BuildContext, _project

        checked = _check_bases(cls, bases) if bases is not None else None
        carried = (
            checked if checked is not None else (cls.__prism_projection_bases__ or ())
        )
        cached = cls.__prism_cache__.get((expr, name, carried, extra))
        if cached is not None:
            return cached
        # Build under a lock so concurrent first calls (free-threaded Python,
        # threaded servers) cannot produce two classes for one expression.
        with _build_lock:
            cached = cls.__prism_cache__.get((expr, name, carried, extra))
            if cached is not None:
                return cached
            ctx = _BuildContext()
            projection = _project(cls, expr, name, checked, ctx, extra)
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
        from .narrow import _validation_key

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
