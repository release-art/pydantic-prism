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

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["Scope", "ScopeExpr", "ScopeLike", "as_expr", "union_all"]


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

    def token(self) -> str:
        """CamelCase fragment used to auto-name derived classes."""
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

    Scopes are only ever used as classes and cannot be instantiated.
    """

    def __new__(cls, *args: object, **kwargs: object) -> Scope:
        raise TypeError(
            f"{cls.__name__} is a scope and is used as a class, never instantiated; "
            f"write scoped({cls.__name__}), not scoped({cls.__name__}())"
        )


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

    def token(self) -> str:
        return self.scope.__name__

    def __repr__(self) -> str:
        return self.scope.__name__


@dataclass(frozen=True)
class _Union(ScopeExpr):
    operands: tuple[ScopeExpr, ...]

    def matches(self, scope: type[Scope]) -> bool:
        return any(operand.matches(scope) for operand in self.operands)

    def selects(self, tag: ScopeExpr) -> bool:
        return any(operand.selects(tag) for operand in self.operands)

    def token(self) -> str:
        return "Or".join(operand.token() for operand in self.operands)

    def __repr__(self) -> str:
        return "(" + " | ".join(repr(operand) for operand in self.operands) + ")"


@dataclass(frozen=True)
class _Intersection(ScopeExpr):
    operands: tuple[ScopeExpr, ...]

    def matches(self, scope: type[Scope]) -> bool:
        return all(operand.matches(scope) for operand in self.operands)

    def selects(self, tag: ScopeExpr) -> bool:
        return all(operand.selects(tag) for operand in self.operands)

    def token(self) -> str:
        return "And".join(operand.token() for operand in self.operands)

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

    def token(self) -> str:
        return f"{self.left.token()}Not{self.right.token()}"

    def __repr__(self) -> str:
        return f"({self.left!r} - {self.right!r})"


@dataclass(frozen=True)
class _Complement(ScopeExpr):
    operand: ScopeExpr

    def matches(self, scope: type[Scope]) -> bool:
        return not self.operand.matches(scope)

    def selects(self, tag: ScopeExpr) -> bool:
        return not self.operand.selects(tag)

    def token(self) -> str:
        return f"Not{self.operand.token()}"

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
    # structurally equal expressions compare (and cache) equal.
    unique = list(dict.fromkeys(flat))
    unique.sort(key=repr)
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
