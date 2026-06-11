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

from typing import Any, Callable, Literal, cast, get_args
from weakref import WeakKeyDictionary

from pydantic import model_validator

from ._internal.scopes import ScopeExpr, ScopeLike, as_expr, union_all

__all__ = ["scoped_validator"]

# raw function -> the scope expression it was tagged with. Weak so a validator's
# scope entry dies with the function (which the owning class keeps alive).
_SCOPED_VALIDATOR_SCOPES: WeakKeyDictionary[Callable[..., Any], ScopeExpr] = (
    WeakKeyDictionary()
)
# raw function -> its declared parent_ordering, if any. Only recorded when the
# author passed parent_ordering=; absence means "not declared" (warn). The lone
# value silences the ordering warning (the author asserts independence).
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
    inherits a plain ``@model_validator(mode="before")`` from a base. pydantic
    runs this (child) validator *first*, so it sees data the base hook has not
    yet transformed; prism warns about this at class definition
    (:class:`~pydantic_prism.PrismOrderingWarning`). Resolve it by:

    * **Often best — don't use ``mode="before"`` at all.** If the validator
      derives a value from *already-parsed* fields, write it as ``mode="after"``
      and read ``self``: the base before-hook has already run during core
      validation, so there is no ordering race and no warning. (Give the derived
      field a default so the record passes core validation.)
    * if you genuinely need the before-phase, call
      :meth:`ScopedModel.run_inherited_before` at the top of the validator to
      run the inherited hooks first. They re-run under pydantic's pipeline, so
      they must be idempotent — the call is explicit so that double-run is
      visible in your code.
    * ``parent_ordering="acknowledged"`` — assert this validator does **not**
      depend on the base hook's output, silencing the warning with no behavior
      change.

    Usage::

        class Webpage(ScopedModel):
            url: Annotated[str, scoped(Public)]
            hostname: Annotated[str, scoped(Public)] = ""

            @scoped_validator(Update, mode="after")
            def derive_hostname(self) -> "Webpage":
                ...  # reads self.url after parsing — no ordering concern
    """
    if not scopes:
        raise TypeError(
            "scoped_validator() requires at least one scope or scope expression"
        )
    if parent_ordering is not None and parent_ordering not in get_args(ParentOrdering):
        raise ValueError(
            f"scoped_validator(parent_ordering=) accepts only "
            f"{', '.join(map(repr, get_args(ParentOrdering)))} or None; "
            f"got {parent_ordering!r}"
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
