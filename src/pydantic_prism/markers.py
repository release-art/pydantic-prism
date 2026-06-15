"""Field markers placed inside ``Annotated[...]`` metadata.

All pydantic-prism field metadata is declared this way — never as a field
default. Marker order inside one ``Annotated`` is insignificant, and prism
markers compose freely with pydantic's own (``Field(...)``, validators,
constraints).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import Field
from pydantic.fields import FieldInfo

from ._internal.scopes import (
    ScopeExpr,
    ScopeLike,
    as_expr,
    union_all,
)

if TYPE_CHECKING:
    from .model import ScopedModel

__all__ = [
    "BackRef",
    "Converter",
    "Heritage",
    "Ref",
    "Scoped",
    "backref",
    "ref",
    "scoped",
]

# The keyword names ``Field(...)`` actually understands. Pydantic silently routes
# *unknown* kwargs into ``json_schema_extra`` (deprecated, removed in v3), so the
# relaxed mapping form of ``override=`` is validated against this set first — a
# typo'd key raises here instead of vanishing into the schema.
_FIELD_KWARGS = frozenset(
    name
    for name, param in inspect.signature(Field).parameters.items()
    if param.kind is not inspect.Parameter.VAR_KEYWORD
)

# Sentinel for "no as_type= given" — distinct from ``as_type=None`` (≡ NoneType).
_NO_TYPE: Any = object()


@dataclass(frozen=True, slots=True)
class Converter:
    """A per-scope round-trip converter for a type-overridden field.

    ``encode`` maps a canonical field value to its projection form (run by
    :meth:`Projection.from_canonical`); ``decode`` maps it back (run by
    :meth:`ScopedModel.from_projection` / :meth:`ScopedModel.with_updates`). Both
    are optional — supply only the direction(s) you need; an absent direction
    falls back to pydantic's native coercion (and may raise if the types do not
    bridge). Used with ``scoped(Scope, as_type=..., convert=Converter(...))``.
    """

    encode: Callable[[Any], Any] | None = None
    decode: Callable[[Any], Any] | None = None


@dataclass(frozen=True, slots=True)
class Heritage:
    """Provenance stamp on a *projected* field, found in its ``FieldInfo.metadata``.

    Every field of a projection carries exactly one ``Heritage`` (read it with
    ``next(m for m in field.metadata if isinstance(m, Heritage))``). Unlike the
    input markers in :data:`PRISM_MARKERS`, it is added by the builder, not the
    author, and is not stripped — it is output, not a tag.

    Attributes:
        source: The canonical field this projected field descends from.
        overridden: True when a per-scope ``override=`` / ``as_type=`` /
            ``convert=`` reshaped this field for this projection; False when the
            field is the canonical's verbatim.
        description_inherited: True when the field's description is the canonical's
            (the LLM-facing question: is this the original description, or one
            tailored for this face?).
    """

    source: str
    overridden: bool
    description_inherited: bool


@dataclass(frozen=True, slots=True)
class Scoped:
    """Marker produced by :func:`scoped`. Holds the field's scope expression.

    ``field_override`` (when present) is a :class:`~pydantic.fields.FieldInfo`
    whose explicitly-set attributes — description, examples, json_schema_extra,
    constraints (``min_length`` / ``ge`` / ``pattern`` / …), alias, default, … —
    overlay the field in projections selecting this marker's (single) scope.
    ``field_type`` (when not the ``_NO_TYPE`` sentinel) replaces the field's
    annotation in that scope, and ``convert`` carries its round-trip converter.
    """

    expr: ScopeExpr
    field_override: FieldInfo | None = None
    field_type: Any = _NO_TYPE
    convert: Converter | None = None


@dataclass(frozen=True, slots=True)
class Ref:
    """Marker produced by :func:`ref`. A forward, FK-style reference."""

    target: type[ScopedModel] | str
    target_field: str = "id"


@dataclass(frozen=True, slots=True)
class BackRef:
    """Marker produced by :func:`backref`. A declared reverse reference."""

    target: type[ScopedModel] | str
    via: str
    target_field: str = "id"


def scoped(
    *scopes: ScopeLike,
    override: FieldInfo | Mapping[str, Any] | None = None,
    as_type: Any = _NO_TYPE,
    convert: Converter | None = None,
) -> Scoped:
    """Tag a field with the scopes (or scope expression) it belongs to.

    Multiple arguments union: ``scoped(A, B)`` is ``scoped(A | B)``.

    ``override=`` makes the same field read — and *validate* — differently per
    projection. Pass a ``Field(...)`` (or a plain mapping of the same kwargs):
    its explicitly-set attributes overlay the field in projections that select
    this scope. That spans the whole ``FieldInfo`` surface — ``description`` /
    ``examples`` / ``json_schema_extra`` annotations *and* core validation
    constraints (``min_length`` / ``ge`` / ``pattern`` / …), plus ``alias``,
    ``default``, and anything else a ``Field`` carries. Constraints merge with
    the canonical ``Field(...)`` by *kind* (each kind you set overrides, the rest
    inherit) and land in both the core schema (validation actually differs) and
    the JSON schema.

    The override is arbitrary, including *loosening* a canonical bound — a
    projection may then accept values the canonical rejects, so the canonical is
    no longer a superset of its projections::

        image_description: Annotated[
            str,
            scoped(Body,    override=Field(min_length=200, description="rich prompt")),
            scoped(Storage, override={"min_length": 10}),
            Field(max_length=5000),   # canonical, shared by every projection
        ]

    ``as_type=`` goes one step further than ``override=``: it replaces the
    field's *annotation* in that scope (the one thing a ``Field`` cannot carry).
    Since a projection then holds a value of a different type than the canonical,
    pass ``convert=Converter(encode=…, decode=…)`` to keep round-trips total
    (``encode`` runs in :meth:`Projection.from_canonical`, ``decode`` in
    :meth:`ScopedModel.from_projection`); omit a direction to fall back to
    pydantic's native coercion::

        created: Annotated[
            datetime,
            scoped(Storage),
            scoped(
                Llm,
                as_type=str,
                convert=Converter(
                    encode=datetime.isoformat, decode=datetime.fromisoformat
                ),
                override=Field(description="ISO-8601 timestamp"),
            ),
        ]

    A ``scoped()`` carrying *any* per-scope payload (``override`` / ``as_type`` /
    ``convert``) must name exactly one ``Scope`` class (so it keys to a single
    scope); split membership across markers to attach per-scope payloads::

        email: Annotated[
            str,
            scoped(Public, override=Field(description="User contact (public-facing)")),
            scoped(Internal, override=Field(description="User identity, for audit")),
        ]

    Usage::

        class User(ScopedModel):
            id: Annotated[UUID, scoped(Public, Storage)]
            password_hash: Annotated[str, scoped(Storage)]
    """
    if not scopes:
        raise TypeError("scoped() requires at least one scope or scope expression")
    expr = union_all(as_expr(scope) for scope in scopes)
    info: FieldInfo | None = None
    if override is not None:
        # A plain mapping is the relaxed form; normalize it to a strict FieldInfo
        # so the rest of prism only ever sees a FieldInfo. Validate the keys
        # ourselves first — Field() would otherwise swallow a typo as schema.
        if isinstance(override, FieldInfo):
            info = override
        else:
            unknown = sorted(set(override) - _FIELD_KWARGS)
            if unknown:
                raise TypeError(
                    f"scoped(override=...) got unknown Field argument(s) "
                    f"{', '.join(unknown)}; pass valid pydantic Field() keywords"
                )
            info = Field(**dict(override))
    has_payload = info is not None or as_type is not _NO_TYPE or convert is not None
    if has_payload and len(expr.atoms()) != 1:
        raise TypeError(
            "scoped(...) with per-scope payload (override / as_type / convert) "
            "must reference exactly one scope; split membership across separate "
            "scoped() markers to attach per-scope payloads"
        )
    return Scoped(expr, field_override=info, field_type=as_type, convert=convert)


def _check_str(value: object, message: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{message}, got {value!r}")


def _check_target(target: object, marker: str) -> None:
    if isinstance(target, str):
        return
    from .model import ScopedModel

    if isinstance(target, type) and issubclass(target, ScopedModel):
        return
    raise TypeError(
        f"{marker}() target must be a ScopedModel subclass or a string forward "
        f"reference, got {target!r}"
    )


def ref(target: type[ScopedModel] | str, *, field: str = "id") -> Ref:
    """Declare that this field references ``target`` (by ``target``'s ``field``).

    ``target`` may be a string for models defined later or in cycles; string
    targets resolve lazily. A bare name (``ref("Customer")``) resolves against
    the owning model's module; a fully-qualified ``ref("pkg.mod:Customer")`` or
    ``ref("pkg.mod.Customer")`` resolves the named module via ``importlib``, for
    a target that lives in another module.

    Usage::

        class Order(ScopedModel):
            customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
            # a target in another module, by qualified path:
            coupon_id: Annotated[UUID, ref("shop.promos:Coupon"), scoped(Public)]
    """
    _check_target(target, "ref")
    _check_str(field, "ref() field must be a string")
    return Ref(target, field)


def backref(target: type[ScopedModel] | str, *, via: str, field: str = "id") -> BackRef:
    """Declare a reverse reference: ``target.via`` is a ``ref`` back to this model.

    The marked field is a real, validated field holding ids of ``target``
    (identified by ``target``'s ``field``); if it has no default, an empty one
    is implied. The ``via=`` link is checked against the target's forward
    ``ref`` when ``__prism__.refs`` is first resolved.

    Usage::

        class Customer(ScopedModel):
            order_ids: Annotated[list[UUID], backref(Order, via="customer_id")]
    """
    _check_target(target, "backref")
    _check_str(via, "backref() via must be a field name string")
    _check_str(field, "backref() field must be a string")
    return BackRef(target, via, field)


PRISM_MARKERS = (Scoped, Ref, BackRef)
