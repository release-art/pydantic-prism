"""Field markers placed inside ``Annotated[...]`` metadata.

All pydantic-prism field metadata is declared this way — never as a field
default. Marker order inside one ``Annotated`` is insignificant, and prism
markers compose freely with pydantic's own (``Field(...)``, validators,
constraints).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._scopes import ScopeExpr, ScopeLike, as_expr, union_all

if TYPE_CHECKING:
    from ._model import ScopedModel

__all__ = ["BackRef", "Ref", "Scoped", "backref", "ref", "scoped"]


@dataclass(frozen=True)
class Scoped:
    """Marker produced by :func:`scoped`. Holds the field's scope expression."""

    expr: ScopeExpr


@dataclass(frozen=True)
class Ref:
    """Marker produced by :func:`ref`. A forward, FK-style reference."""

    target: type[ScopedModel] | str
    target_field: str = "id"


@dataclass(frozen=True)
class BackRef:
    """Marker produced by :func:`backref`. A declared reverse reference."""

    target: type[ScopedModel] | str
    via: str
    target_field: str = "id"


def scoped(*scopes: ScopeLike) -> Scoped:
    """Tag a field with the scopes (or scope expression) it belongs to.

    Multiple arguments union: ``scoped(A, B)`` is ``scoped(A | B)``.

    Usage::

        class User(ScopedModel):
            id: Annotated[UUID, scoped(Public, Storage)]
            password_hash: Annotated[str, scoped(Storage)]
    """
    if not scopes:
        raise TypeError("scoped() requires at least one scope or scope expression")
    return Scoped(union_all(as_expr(scope) for scope in scopes))


def _check_str(value: object, message: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{message}, got {value!r}")


def _check_target(target: object, marker: str) -> None:
    if isinstance(target, str):
        return
    from ._model import ScopedModel

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
