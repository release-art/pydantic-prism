"""``@scoped_validator`` — a model validator that survives projection.

Plain ``@model_validator`` is *not* carried onto projections: it assumes the
full canonical field set (decision 14). ``@scoped_validator(*scopes, mode=...)``
is the opt-in exception — a real pydantic model validator that *also* carries
onto every projection whose scope expression selects the listed scopes, using
the same membership rule as scoped fields (``projection_expr.selects(tag)``).

The scope tag cannot live on the decorated callable (pydantic stores
``before``/``wrap`` validators as bound methods with no ``__dict__``), so it is
recorded in a module-level registry keyed by the raw function;
``ScopedModel`` resolves it into the per-class ``__prism_validator_scopes__``
map at collection time.
"""

from __future__ import annotations

from typing import Any, Callable, Literal, cast
from weakref import WeakKeyDictionary

from pydantic import model_validator

from ._internal.scopes import ScopeExpr, ScopeLike, as_expr, union_all

__all__ = ["scoped_validator"]

# raw function -> the scope expression it was tagged with. Weak so a validator's
# scope entry dies with the function (which the owning class keeps alive).
_SCOPED_VALIDATOR_SCOPES: WeakKeyDictionary[Callable[..., Any], ScopeExpr] = (
    WeakKeyDictionary()
)
# raw function -> its parent_ordering acknowledgement, if any. Only recorded when
# the author passed parent_ordering=; absence means "not declared" (warn).
ParentOrdering = Literal["acknowledged"]
_SCOPED_VALIDATOR_PARENT_ORDERING: WeakKeyDictionary[
    Callable[..., Any], ParentOrdering
] = WeakKeyDictionary()


def scoped_validator(
    *scopes: ScopeLike,
    mode: Literal["before", "after", "wrap"],
    parent_ordering: ParentOrdering | None = None,
) -> Callable[[Any], Any]:
    """Declare a model validator that survives projection to the given scopes.

    Behaves exactly like ``@model_validator(mode=...)`` on the canonical model,
    and additionally carries onto any projection whose scope expression selects
    one of ``scopes`` (varargs union; expressions allowed, like ``scoped()``).
    Use the root ``Scope`` to carry onto every projection.

    The carried validator runs against the narrowed projection; listing a scope
    asserts the fields it touches survive there (prism does not check this —
    a ``mode="after"`` validator reading a dropped field raises at validation).

    ``parent_ordering`` concerns ``mode="before"`` validators on a model that
    inherits a plain ``@model_validator(mode="before")`` from a non-``ScopedModel``
    base. pydantic runs this (child) validator *first*, so it sees data the base
    hook has not yet transformed; prism warns about this at class definition
    (:class:`~pydantic_prism.PrismOrderingWarning`). Pass
    ``parent_ordering="acknowledged"`` to assert this validator does **not**
    depend on the base hook's output and silence the warning. To instead *depend*
    on it, call :meth:`ScopedModel.run_inherited_before` inside the validator.

    Usage::

        class Webpage(ScopedModel):
            url: Annotated[str, scoped(Public)]
            hostname: Annotated[str, scoped(Public)] = ""

            @scoped_validator(Update, mode="before")
            @classmethod
            def derive_hostname(cls, data: Any) -> Any:
                ...
    """
    if not scopes:
        raise TypeError(
            "scoped_validator() requires at least one scope or scope expression"
        )
    if parent_ordering is not None and parent_ordering != "acknowledged":
        raise ValueError(
            f"scoped_validator(parent_ordering=) accepts only 'acknowledged' or "
            f"None; got {parent_ordering!r}"
        )
    expr = union_all(as_expr(scope) for scope in scopes)
    make = cast(Callable[..., Callable[[Any], Any]], model_validator)

    def decorator(func: Any) -> Any:
        # classmethod/staticmethod (before/wrap) carry __func__; a plain
        # function (after) is its own raw form.
        raw: Any = getattr(func, "__func__", func)
        _SCOPED_VALIDATOR_SCOPES[raw] = expr
        if parent_ordering is not None:
            _SCOPED_VALIDATOR_PARENT_ORDERING[raw] = parent_ordering
        return make(mode=mode)(func)

    return decorator
