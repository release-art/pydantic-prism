"""Field markers placed inside ``Annotated[...]`` metadata.

All pydantic-prism field metadata is declared this way — never as a field
default. Marker order inside one ``Annotated`` is insignificant, and prism
markers compose freely with pydantic's own (``Field(...)``, validators,
constraints).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .scopes import ScopeExpr, ScopeLike, as_expr, union_all

if TYPE_CHECKING:
    from .model import ScopedModel

__all__ = ["BackRef", "Ref", "Scoped", "backref", "ref", "scoped"]


@dataclass(frozen=True, slots=True)
class Scoped:
    """Marker produced by :func:`scoped`. Holds the field's scope expression.

    ``field_schema`` (when present) carries per-scope JSON-schema metadata —
    ``description`` / ``examples`` / ``json_schema_extra`` keys — that lands on
    the field in projections selecting this marker's (single) scope.
    """

    expr: ScopeExpr
    field_schema: Mapping[str, Any] | None = None


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
    description: str | None = None,
    examples: Sequence[Any] | None = None,
    json_schema_extra: dict[str, Any] | None = None,
) -> Scoped:
    """Tag a field with the scopes (or scope expression) it belongs to.

    Multiple arguments union: ``scoped(A, B)`` is ``scoped(A | B)``.

    Optional ``description`` / ``examples`` / ``json_schema_extra`` attach
    per-scope JSON-schema metadata to the field: it lands on the field's schema
    in projections that select this scope, so the same field can read
    differently per projection. A schema-carrying ``scoped()`` must name exactly
    one ``Scope`` class (so its metadata keys to a single scope); split membership
    across markers to attach per-scope schema::

        email: Annotated[
            str,
            scoped(Public, description="User contact (public-facing)"),
            scoped(Internal, description="User identity, for internal audit"),
        ]

    Usage::

        class User(ScopedModel):
            id: Annotated[UUID, scoped(Public, Storage)]
            password_hash: Annotated[str, scoped(Storage)]
    """
    if not scopes:
        raise TypeError("scoped() requires at least one scope or scope expression")
    expr = union_all(as_expr(scope) for scope in scopes)
    schema: dict[str, Any] = {}
    if description is not None:
        schema["description"] = description
    if examples is not None:
        schema["examples"] = list(examples)
    if json_schema_extra is not None:
        schema["json_schema_extra"] = dict(json_schema_extra)
    if schema and len(expr.atoms()) != 1:
        raise TypeError(
            "scoped(...) with schema metadata (description/examples/"
            "json_schema_extra) must reference exactly one scope; split "
            "membership across separate scoped() markers to attach per-scope "
            "schema"
        )
    return Scoped(expr, field_schema=schema or None)


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
    targets resolve lazily against the owning model's module.

    Usage::

        class Order(ScopedModel):
            customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
    """
    _check_target(target, "ref")
    _check_str(field, "ref() field must be a string")
    return Ref(target, field)


def backref(target: type[ScopedModel] | str, *, via: str, field: str = "id") -> BackRef:
    """Declare a reverse reference: ``target.via`` is a ``ref`` back to this model.

    The marked field is a real, validated field holding ids of ``target``
    (identified by ``target``'s ``field``); if it has no default, an empty one
    is implied. The ``via=`` link is checked against the target's forward
    ``ref`` when ``__refs__`` is first resolved.

    Usage::

        class Customer(ScopedModel):
            order_ids: Annotated[list[UUID], backref(Order, via="customer_id")]
    """
    _check_target(target, "backref")
    _check_str(via, "backref() via must be a field name string")
    _check_str(field, "backref() field must be a string")
    return BackRef(target, via, field)


PRISM_MARKERS = (Scoped, Ref, BackRef)
