"""The public ``Projection`` and ``ScopedModel`` classes.

The projection-building engine lives in :mod:`pydantic_prism._internal.model`
(``collect`` / ``build`` / ``narrow`` / ``bases`` / ``schema``); those helpers
import these classes at module level, so the class methods here defer their own
imports of the engine to call time to break the cycle.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeVar, cast

from pydantic import BaseModel

from ._internal.scopes import (
    Scope,
    ScopeExpr,
    ScopeLike,
    as_expr,
    dimension_root,
    union_all,
)
from .refs import RefGraph
from .scopes import Classification, In, Out  # bundled taxonomy

if TYPE_CHECKING:
    from .flow import FlowReport
    from .toolschema import ToolProvider

__all__ = ["Projection", "ScopedModel", "unprojected"]

# Sentinel: "no default_scope= keyword on this class definition". Distinct from
# None, which is a legitimate resolved value meaning "no default declared".
_NO_DEFAULT: Any = object()

_Member = TypeVar("_Member")


def unprojected(member: _Member) -> _Member:
    """Keep a method / ``property`` / ``classmethod`` canonical-only.

    By default prism copies a :class:`ScopedModel`'s non-field callables onto
    every projection. Decorate a member with ``@unprojected`` to exclude it —
    e.g. a method that hard-depends on a field no projection carries::

        class Card(ScopedModel):
            @unprojected
            def needs_storage_only_fields(self) -> bool:
                return bool(self.hashes)  # 'hashes' exists only on Storage

    The flag is set on the underlying function, so ``@unprojected`` may wrap (or
    be wrapped by) ``@property`` / ``@classmethod`` / ``@staticmethod`` in either
    order.
    """
    target: Any = member
    if isinstance(target, (classmethod, staticmethod)):
        target = cast(Any, target).__func__
    elif isinstance(target, property):
        target = cast(Any, target).fget
    target.__prism_unprojected__ = True
    return member


@dataclass(frozen=True, slots=True)
class _ProjectionKey:
    """Identity of one derived projection class within a model's caches.

    All four fields participate — changing any yields a different class:

    * ``expr`` — the scope expression projected to.
    * ``name`` — the explicit ``name=`` override, or None for the auto-name.
    * ``carried`` — the non-``ScopedModel`` bases carried onto the projection.
    * ``extra`` — the ``model_config["extra"]`` override: None inherits the
      canonical's config, "forbid" is what ``input()`` forces. It keeps an
      ``input()`` projection a distinct, separately-named class from the
      equivalent bare ``scope()``.

    Frozen + slotted so it is hashable and usable as a dict key.
    """

    expr: ScopeExpr
    name: str | None
    carried: tuple[type[BaseModel], ...]
    extra: Literal["allow", "ignore", "forbid"] | None


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
    def run_inherited_before(cls, data: Any) -> Any:
        """Run inherited ``@model_validator(mode="before")`` hooks, in pydantic order.

        The projection-side counterpart to
        :meth:`ScopedModel.run_inherited_before` — so a ``@scoped_validator``
        that calls ``cls.run_inherited_before(data)`` keeps working once it is
        carried onto a projection (whose inherited hooks come from carried,
        non-``ScopedModel`` bases). See that method for the full contract,
        including the idempotency requirement.
        """
        from ._internal.model.ordering import _run_inherited_before

        return _run_inherited_before(cls, data)

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
        from ._internal.model.narrow import _narrow

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

    @classmethod
    def scope(
        cls,
        scope: ScopeLike,
        *,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
    ) -> type[Projection]:
        """Re-project: derive a **narrower** projection from this one.

        A projection's fields carry no scope tags (they are stripped at build
        time), so re-projection delegates to the canonical source with the
        **intersection** of this projection's scope and ``scope``::

            UserInternal = User.scope(Internal)
            UserInternal.scope(Public)  # == User.scope(Internal & Public)

        Intersection means re-projection can only ever **narrow** — a view cannot
        expose more than it has, so re-projecting to a wider scope cannot bring
        back fields this projection dropped (``UserPublic.scope(Internal)`` has
        the ``Public`` fields, not Internal-only ones). The result is *another
        projection of the canonical* (a sibling, not a subclass of this one),
        consistent with projections-not-inheritance.

        ``bases`` defaults to this projection's carried ``__prism_bases__`` so
        base behavior survives the narrowing; ``name``/``bases`` forward to
        :meth:`ScopedModel.scope`. The auto-name comes from the intersected
        expression (e.g. ``UserInternalAndPublic``) — pass ``name=`` for a
        stable one. To narrow an *instance*, use :meth:`from_canonical`.
        """
        return cls.__prism_source__.scope(
            cls.__prism_scope__ & as_expr(scope),
            name=name,
            bases=cls.__prism_bases__ if bases is None else bases,
        )

    @classmethod
    def tool_schema(
        cls,
        *,
        provider: ToolProvider = "openai",
        strict: bool = True,
        name: str | None = None,
        description: str | None = None,
        envelope: bool = True,
    ) -> dict[str, Any]:
        """Render this projection as an LLM tool / function schema.

        The projection already hides the fields the model should not see and
        carries any per-scope ``description`` / ``examples``; this method
        normalizes its ``model_json_schema()`` for ``provider`` and wraps it in
        that provider's tool envelope (ready to pass to the ``openai`` /
        ``anthropic`` / ``mistral`` SDK — no SDK is imported; ``mistral`` uses
        the OpenAI-compatible tools format).

        ``strict=True`` (the default, and what OpenAI recommends) applies the
        rewrites OpenAI strict structured outputs require: every object gets
        ``additionalProperties: false`` and lists all its properties as
        ``required``, and an optional/defaulted field becomes a ``"null"`` union
        with its ``default`` dropped. This is the one place prism rewrites types
        rather than only filtering fields — opt out with ``strict=False`` (e.g.
        for Anthropic, whose ``input_schema`` is plain JSON Schema). Under
        ``provider="openai", strict=True`` a schema that nests objects deeper
        than 5 levels (or a recursive model) emits a
        :class:`~pydantic_prism.ToolSchemaDepthWarning`.

        ``name`` defaults to the projection class name; ``description`` falls
        back to the projection's per-scope model description when present.

        ``envelope=False`` returns just the normalized parameters schema instead
        of the provider envelope — the shape a framework wants for its own tool
        definition (e.g. Pydantic AI's ``ToolDefinition.parameters_json_schema``).
        ``provider`` then only governs the OpenAI depth check.
        """
        from .toolschema import build

        return build(
            cls,
            provider=provider,
            strict=strict,
            name=name,
            description=description,
            envelope=envelope,
        )


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
        from ._internal.model.bases import _check_bases
        from ._internal.model.build import _validate_name_template

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
        from ._internal.model.collect import _initialize
        from ._internal.model.ordering import _warn_ordering_trap

        cls.__prism_cache__ = {}
        cls.__prism_names__ = {}
        _initialize(cls)
        _warn_ordering_trap(cls)

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
        from ._internal.model.collect import _collect

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
    def run_inherited_before(cls, data: Any) -> Any:
        """Run inherited ``@model_validator(mode="before")`` hooks, in pydantic order.

        The friendly replacement for the ``Base.hook.__func__(cls, data)``
        descriptor dance. Call it at the top of a ``@scoped_validator(mode="before")``
        whose logic depends on a transformation a non-``ScopedModel`` base hook
        applies (e.g. JSON-decoding columns)::

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive_hostname(cls, data: Any) -> Any:
                data = cls.run_inherited_before(data)  # base hook ran; data is decoded
                ...

        pydantic runs this child validator *before* the inherited base hook
        (child-first), so without this call the child sees raw data — see
        :class:`~pydantic_prism.PrismOrderingWarning`. Every ``before`` validator
        defined on a strict, non-prism ancestor is invoked as
        ``validator(cls, data)``, nearest ancestor first and parent-most last,
        with each return threaded into the next; the transformed data is returned.

        Because the inherited hook still runs again afterwards under pydantic's own
        pipeline, it must be **idempotent** (the type-guarded norm — e.g.
        ``if isinstance(v, str): json.loads(v)``). A hook that transforms
        unconditionally would run twice; guard it on the input shape.
        """
        from ._internal.model.ordering import _run_inherited_before

        return _run_inherited_before(cls, data)

    @classmethod
    def scopes(cls) -> frozenset[type[Scope]]:
        """The Scope classes appearing in this model's field tags."""
        out: set[type[Scope]] = set()
        for expr in cls.__field_scopes__.values():
            out |= expr.atoms()
        return frozenset(out)

    @classmethod
    def dimensions(cls) -> dict[type[Scope], frozenset[type[Scope]]]:
        """The model's scopes grouped by **axis** — the structural view.

        An axis (dimension) is inferred from the inheritance forest: each scope's
        top ancestor just below ``Scope`` is its :func:`dimension_root`, and the
        root's name labels the axis. Returns ``{root: scopes-in-that-axis}``,
        discovering visibility, classification, direction, and any user-defined
        axis alike — without depending on the :class:`Classification` /
        :class:`Direction` bases. Contrast :meth:`classifications`, the *semantic*
        (marker-based) classification slice used by :meth:`redacted`.
        """
        out: dict[type[Scope], set[type[Scope]]] = {}
        for scope in cls.scopes():
            out.setdefault(dimension_root(scope), set()).add(scope)
        return {root: frozenset(members) for root, members in out.items()}

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
    def data_flow(cls) -> FlowReport:
        """Trace dimensional data reachable from this model across the ref graph.

        Walks forward ``ref`` / ``embedded`` edges (BFS, cycle-safe) and reports
        every **tagged** field of every reachable model, with its scopes grouped
        by axis — the compliance/architecture artifact: *given this entry point,
        where does scoped data live (PII and otherwise), via which references?*
        Axes are inferred structurally (:meth:`dimensions`), so PII surfaces
        without prism being told which scope is sensitive. Render the returned
        :class:`.FlowReport` with ``.as_dict()`` (JSON) or ``.to_mermaid()``.
        """
        from .flow import build_flow_report

        return build_flow_report(cls)

    @classmethod
    def redacted(
        cls,
        visible: ScopeLike,
        *,
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
        which classifications to remove instead. ``visible`` is one scope or
        expression (compose wider views with ``|``). Refs survive, so the
        relationship graph stays intact.

        ``name`` / ``bases`` forward to :meth:`scope`.
        """
        visible_expr = as_expr(visible)
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
        cls, visible: ScopeLike | None, drop: type[Scope]
    ) -> ScopeExpr:
        """The visibility expression for ``input``/``output``, minus a direction.

        ``visible`` falls back to the model's ``default_scope=`` when ``None``
        (the direction-only case — tag fields ``In``/``Out``/both and let the
        read-write majority fall back); with no default and no argument it
        raises, mirroring :meth:`redacted`.
        """
        if visible is not None:
            base = as_expr(visible)
        elif cls.__prism_default_scope__ is not None:
            base = cls.__prism_default_scope__
        else:
            raise TypeError(
                f"{cls.__name__}.{'input' if drop is Out else 'output'}() requires a "
                f"visibility scope, or a default_scope= on the model"
            )
        return base - drop

    @classmethod
    def input(  # noqa: A003 — `input`/`output` name the read/write sides on purpose
        cls,
        visible: ScopeLike | None = None,
        *,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
        extra: Literal["allow", "ignore", "forbid"] = "forbid",
    ) -> type[Projection]:
        """The write-side projection: the ``visible`` view minus read-only fields.

        Mass-assignment protection *by shape*: a read-only field (tagged
        ``scoped(..., Out)``) is simply absent from this projection, so it can
        never be over-posted. The subtraction is ``visible - Out`` and it is
        **deep** — nested ``ScopedModel`` fields are projected the same way, so
        read-only fields drop at every level.

        ``extra`` defaults to ``"forbid"``: unknown keys are rejected outright
        (a loud 422 rather than a silent drop, and the only thing that closes the
        hole when the canonical declares ``extra="allow"``). It applies to the
        top-level projection; nest ``input()`` on a field's model for deep
        ``forbid``. Pass ``extra="ignore"``/``"allow"`` to opt out. ``visible`` is
        one scope or expression (compose with ``|``), and falls back to the
        model's ``default_scope=`` when omitted. ``name`` defaults to
        ``"{Model}In"``; ``name``/``bases`` forward to :meth:`scope`.
        """
        expr = cls._directional_expr(visible, Out)
        return cls._build_projection(expr, name or f"{cls.__name__}In", bases, extra)

    @classmethod
    def output(
        cls,
        visible: ScopeLike | None = None,
        *,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
    ) -> type[Projection]:
        """The read-side projection: the ``visible`` view minus write-only fields.

        The response counterpart to :meth:`input`: a write-only field (tagged
        ``scoped(..., In)``, e.g. a password) is absent, so it is never echoed
        back. The subtraction is ``visible - In``; like ``input`` it is deep
        through nested ``ScopedModel`` fields. ``extra`` is left untouched
        (server→client; over-posting does not apply). ``visible`` is one scope or
        expression (compose with ``|``), and falls back to the model's
        ``default_scope=`` when omitted. ``name`` defaults to ``"{Model}Out"``;
        ``name``/``bases`` forward to :meth:`scope`.
        """
        expr = cls._directional_expr(visible, In)
        return cls._build_projection(expr, name or f"{cls.__name__}Out", bases, None)

    @classmethod
    def scope(
        cls,
        scope: ScopeLike,
        *,
        name: str | None = None,
        bases: Sequence[type[BaseModel]] | None = None,
    ) -> type[Projection]:
        """Derive (or fetch from cache) the projection for a scope expression.

        Takes one scope or scope expression — compose with the algebra
        (``Model.scope(Public | Internal)``, ``Model.scope(Internal - Pii)``)
        rather than passing several arguments. The same expression always returns
        the same class object. ``name=`` overrides the auto-generated class name
        and is part of the cache key.

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
        return cls._build_projection(as_expr(scope), name, bases, None)

    @classmethod
    def tool_schema(
        cls,
        scope: ScopeLike | None = None,
        *,
        provider: ToolProvider = "openai",
        strict: bool = True,
        name: str | None = None,
        description: str | None = None,
        envelope: bool = True,
    ) -> dict[str, Any]:
        """Render a scope of this model as an LLM tool / function schema.

        A one-step convenience equivalent to
        ``Model.scope(scope).tool_schema(...)`` — see
        :meth:`Projection.tool_schema` for the ``provider`` / ``strict`` /
        ``name`` / ``description`` / ``envelope`` contract. ``scope`` falls back
        to the model's ``default_scope=`` when omitted (and raises if neither is
        given). For write-side (mass-assignment-safe) tool inputs, build the
        projection explicitly instead: ``Model.input(scope).tool_schema(...)``.
        """
        if scope is not None:
            expr = as_expr(scope)
        elif cls.__prism_default_scope__ is not None:
            expr = cls.__prism_default_scope__
        else:
            raise TypeError(
                f"{cls.__name__}.tool_schema() requires a scope, or a "
                f"default_scope= on the model"
            )
        return cls.scope(expr).tool_schema(
            provider=provider,
            strict=strict,
            name=name,
            description=description,
            envelope=envelope,
        )

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
        from ._internal.model.bases import _check_bases
        from ._internal.model.build import _BuildContext, _project

        checked = _check_bases(cls, bases) if bases is not None else None
        carried = (
            checked if checked is not None else (cls.__prism_projection_bases__ or ())
        )
        cache_key = _ProjectionKey(expr, name, carried, extra)
        cached = cls.__prism_cache__.get(cache_key)
        if cached is not None:
            return cached
        # Build under a lock so concurrent first calls (free-threaded Python,
        # threaded servers) cannot produce two classes for one expression.
        with _build_lock:
            cached = cls.__prism_cache__.get(cache_key)
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
            for build_key, built in ctx.built.items():
                build_key.owner.__prism_cache__[build_key.key] = built
                build_key.owner.__prism_names__[built.__name__] = build_key.key
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
        from ._internal.model.narrow import _validation_key

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
