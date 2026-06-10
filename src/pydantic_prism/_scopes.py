"""Scope classes and the scope-expression algebra.

Scopes are declared as subclasses of :class:`Scope`; Python inheritance forms
the scope graph. A subclass is a *broader* scope: ``class Internal(Public)``
means every field visible in ``Public`` is also visible in ``Internal``.

Scope classes and scope expressions compose with set-like operators —
``A | B`` (union), ``A & B`` (intersection), ``A - B`` (difference) and
``~A`` (complement) — usable both inside ``scoped(...)`` field tags and as
arguments to ``Model.scope(...)``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

__all__ = [
    "Classification",
    "Scope",
    "ScopeExpr",
    "ScopeLike",
    "as_expr",
    "union_all",
]


class ScopeExpr:
    """A composable scope expression.

    Two evaluations exist, one per side of the API:

    - ``matches(scope)`` — used for *field tags*: does a field tagged with
      this expression belong to the concrete scope class ``scope``?
    - ``selects(tag)`` — used for *projections*: does a field tagged with
      expression ``tag`` survive a projection requested with this expression?
    """

    def matches(self, scope: type[Scope]) -> bool:
        raise NotImplementedError

    def selects(self, tag: ScopeExpr) -> bool:
        raise NotImplementedError

    def atoms(self) -> frozenset[type[Scope]]:
        """Every concrete Scope class appearing anywhere in this expression."""
        raise NotImplementedError

    def is_partial(self) -> bool:
        """Whether projections to this expression make every field optional.

        An expression is partial iff *all* of its atoms are partial scopes —
        the conservative rule: mixing a partial scope with a regular one
        yields a regular projection.
        """
        return all(scope.__prism_partial__ for scope in self.atoms())

    def token(self) -> str:
        """CamelCase fragment used to auto-name derived classes."""
        raise NotImplementedError

    def sort_key(self) -> str:
        """Module-qualified, structure-tagged key for canonical ordering."""
        raise NotImplementedError

    def __or__(self, other: ScopeLike) -> ScopeExpr:
        return union_all([self, as_expr(other)])

    def __ror__(self, other: ScopeLike) -> ScopeExpr:
        return union_all([as_expr(other), self])

    def __and__(self, other: ScopeLike) -> ScopeExpr:
        return intersect_all([self, as_expr(other)])

    def __rand__(self, other: ScopeLike) -> ScopeExpr:
        return intersect_all([as_expr(other), self])

    def __sub__(self, other: ScopeLike) -> ScopeExpr:
        return _Difference(self, as_expr(other))

    def __rsub__(self, other: ScopeLike) -> ScopeExpr:
        return _Difference(as_expr(other), self)

    def __invert__(self) -> ScopeExpr:
        return _Complement(self)


class ScopeMeta(type):
    """Metaclass giving Scope *classes* the same operators as expressions."""

    def __or__(cls, other: ScopeLike) -> ScopeExpr:
        return as_expr(cls) | other

    def __ror__(cls, other: ScopeLike) -> ScopeExpr:
        return as_expr(other) | as_expr(cls)

    def __and__(cls, other: ScopeLike) -> ScopeExpr:
        return as_expr(cls) & other

    def __rand__(cls, other: ScopeLike) -> ScopeExpr:
        return as_expr(other) & as_expr(cls)

    def __sub__(cls, other: ScopeLike) -> ScopeExpr:
        return as_expr(cls) - other

    def __rsub__(cls, other: ScopeLike) -> ScopeExpr:
        return as_expr(other) - as_expr(cls)

    def __invert__(cls) -> ScopeExpr:
        return ~as_expr(cls)


class Scope(metaclass=ScopeMeta):
    """Base class for user-declared scopes.

    Subclass to declare a scope; subclass a scope to extend it::

        class Public(Scope): ...
        class Internal(Public): ...   # Internal sees everything Public sees

    ``Scope`` itself is the root: a field tagged ``scoped(Scope)`` belongs to
    every scope (the wildcard), since every scope subclasses the root.

    Declaring ``partial=True`` makes the scope *partial*: every projection to
    it gets all surviving fields as ``T | None`` with ``default=None`` (the
    PATCH/Update-model shape)::

        class Update(Storage, partial=True): ...

    The flag inherits down the scope graph like any class attribute and may
    be re-declared (``partial=False``) by a subclass.

    A scope may also carry JSON-schema metadata that lands on the *projected
    model's* schema when a projection selects it::

        class Public(Scope, description="Public-facing view", examples=[...]): ...

    ``description`` / ``examples`` / ``json_schema_extra`` are merged into the
    schema root of every projection whose expression contains this scope. This
    metadata is *not* inherited: a broader subclass does not reuse a narrower
    scope's prose.

    Scopes are only ever used as classes and cannot be instantiated.
    """

    __prism_partial__: ClassVar[bool] = False
    # Model-level JSON-schema metadata for projections that select this scope.
    # Read per-class (via vars()), never inherited.
    __prism_model_schema__: ClassVar[dict[str, Any]] = {}

    def __init_subclass__(
        cls,
        partial: bool | None = None,
        description: str | None = None,
        examples: Sequence[Any] | None = None,
        json_schema_extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if partial is not None:
            cls.__prism_partial__ = bool(partial)
        schema: dict[str, Any] = {}
        if description is not None:
            schema["description"] = description
        if examples is not None:
            schema["examples"] = list(examples)
        if json_schema_extra is not None:
            schema["json_schema_extra"] = dict(json_schema_extra)
        if schema:
            cls.__prism_model_schema__ = schema

    def __new__(cls, *args: object, **kwargs: object) -> Scope:
        raise TypeError(
            f"{cls.__name__} is a scope and is used as a class, never instantiated; "
            f"write scoped({cls.__name__}), not scoped({cls.__name__}())"
        )


class Classification(Scope):
    """Base for data-classification tags — an axis orthogonal to visibility.

    A classification *is* a :class:`Scope`: it composes in the same expression
    algebra (``Internal - Pii``), tags fields through the same ``scoped(...)``
    marker, and is selected by the same ``matches`` / ``selects`` rules. The
    distinct base is what lets prism tell the two axes apart — enumerate a
    model's classifications (:meth:`ScopedModel.classifications`), auto-derive
    audit-safe views (:meth:`ScopedModel.redacted`), and trace where classified
    data flows (:meth:`ScopedModel.classified_flow`).

    Declare concrete tags by subclassing::

        class Pii(Classification): ...
        class Secret(Classification): ...

    prism ships only this base, not a fixed taxonomy — name the classes that fit
    your compliance regime. Because a classification is an ordinary scope, it may
    still be requested directly (``Model.scope(Pii)`` is "every PII field"); the
    governance helpers above are the ergonomic path that keeps the two axes
    explicit.
    """


type ScopeLike = type[Scope] | ScopeExpr


def as_expr(value: object) -> ScopeExpr:
    """Coerce a Scope subclass or expression to a :class:`ScopeExpr`."""
    if isinstance(value, ScopeExpr):
        return value
    if isinstance(value, type) and issubclass(value, Scope):
        return _Atom(value)
    raise TypeError(f"expected a Scope subclass or a scope expression, got {value!r}")


@dataclass(frozen=True)
class _Atom(ScopeExpr):
    scope: type[Scope]

    def matches(self, scope: type[Scope]) -> bool:
        return issubclass(scope, self.scope)

    def selects(self, tag: ScopeExpr) -> bool:
        return tag.matches(self.scope)

    def atoms(self) -> frozenset[type[Scope]]:
        return frozenset((self.scope,))

    def token(self) -> str:
        return self.scope.__name__

    def sort_key(self) -> str:
        return f"{self.scope.__module__}.{self.scope.__qualname__}"

    def __repr__(self) -> str:
        return self.scope.__name__


@dataclass(frozen=True)
class _Union(ScopeExpr):
    operands: tuple[ScopeExpr, ...]

    def matches(self, scope: type[Scope]) -> bool:
        return any(operand.matches(scope) for operand in self.operands)

    def selects(self, tag: ScopeExpr) -> bool:
        return any(operand.selects(tag) for operand in self.operands)

    def atoms(self) -> frozenset[type[Scope]]:
        return frozenset(
            scope for operand in self.operands for scope in operand.atoms()
        )

    def token(self) -> str:
        return "Or".join(operand.token() for operand in self.operands)

    def sort_key(self) -> str:
        return "or(" + ",".join(operand.sort_key() for operand in self.operands) + ")"

    def __repr__(self) -> str:
        return "(" + " | ".join(repr(operand) for operand in self.operands) + ")"


@dataclass(frozen=True)
class _Intersection(ScopeExpr):
    operands: tuple[ScopeExpr, ...]

    def matches(self, scope: type[Scope]) -> bool:
        return all(operand.matches(scope) for operand in self.operands)

    def selects(self, tag: ScopeExpr) -> bool:
        return all(operand.selects(tag) for operand in self.operands)

    def atoms(self) -> frozenset[type[Scope]]:
        return frozenset(
            scope for operand in self.operands for scope in operand.atoms()
        )

    def token(self) -> str:
        return "And".join(operand.token() for operand in self.operands)

    def sort_key(self) -> str:
        return "and(" + ",".join(operand.sort_key() for operand in self.operands) + ")"

    def __repr__(self) -> str:
        return "(" + " & ".join(repr(operand) for operand in self.operands) + ")"


@dataclass(frozen=True)
class _Difference(ScopeExpr):
    left: ScopeExpr
    right: ScopeExpr

    def matches(self, scope: type[Scope]) -> bool:
        return self.left.matches(scope) and not self.right.matches(scope)

    def selects(self, tag: ScopeExpr) -> bool:
        return self.left.selects(tag) and not self.right.selects(tag)

    def atoms(self) -> frozenset[type[Scope]]:
        return self.left.atoms() | self.right.atoms()

    def token(self) -> str:
        return f"{self.left.token()}Not{self.right.token()}"

    def sort_key(self) -> str:
        return f"sub({self.left.sort_key()},{self.right.sort_key()})"

    def __repr__(self) -> str:
        return f"({self.left!r} - {self.right!r})"


@dataclass(frozen=True)
class _Complement(ScopeExpr):
    operand: ScopeExpr

    def matches(self, scope: type[Scope]) -> bool:
        return not self.operand.matches(scope)

    def selects(self, tag: ScopeExpr) -> bool:
        return not self.operand.selects(tag)

    def atoms(self) -> frozenset[type[Scope]]:
        return self.operand.atoms()

    def token(self) -> str:
        return f"Not{self.operand.token()}"

    def sort_key(self) -> str:
        return f"not({self.operand.sort_key()})"

    def __repr__(self) -> str:
        return f"~{self.operand!r}"


def _flatten(
    exprs: Iterable[ScopeExpr], op: type[_Union] | type[_Intersection]
) -> tuple[ScopeExpr, ...]:
    flat: list[ScopeExpr] = []
    for expr in exprs:
        if isinstance(expr, op):
            flat.extend(expr.operands)
        else:
            flat.append(expr)
    # Canonical form: deduplicate and order deterministically so that
    # structurally equal expressions compare (and cache) equal. The key is
    # module-qualified: two scopes sharing a bare class name still order
    # consistently.
    unique = list(dict.fromkeys(flat))
    unique.sort(key=lambda expr: expr.sort_key())
    return tuple(unique)


def union_all(exprs: Iterable[ScopeExpr]) -> ScopeExpr:
    operands = _flatten(exprs, _Union)
    if not operands:
        raise TypeError("a scope expression requires at least one scope")
    if len(operands) == 1:
        return operands[0]
    return _Union(operands)


def intersect_all(exprs: Iterable[ScopeExpr]) -> ScopeExpr:
    operands = _flatten(exprs, _Intersection)
    if not operands:
        raise TypeError("a scope expression requires at least one scope")
    if len(operands) == 1:
        return operands[0]
    return _Intersection(operands)
