"""Exceptions and warnings raised by pydantic-prism.

Misuse of the API itself (wrong argument types, markers placed in field
defaults) raises plain :class:`TypeError`; these classes cover domain errors
that can only be detected once models and scopes are put together. Diagnostics
that are advisory rather than fatal are emitted as warnings under
:class:`PrismWarning`.
"""

__all__ = [
    "EmptyProjectionError",
    "PrismBaseDropWarning",
    "PrismError",
    "PrismOrderingWarning",
    "PrismWarning",
    "ProjectionBaseError",
    "ProjectionNameError",
    "RefResolutionError",
    "ToolSchemaDepthWarning",
]


class PrismError(Exception):
    """Base class for all pydantic-prism domain errors."""


class PrismWarning(UserWarning):
    """Base class for all pydantic-prism advisory warnings.

    A :class:`UserWarning` subclass, so existing ``UserWarning`` filters keep
    working; filter on this class to silence (or escalate) *every* prism
    diagnostic at once, or on a concrete subclass for one kind in particular.
    """


class PrismBaseDropWarning(PrismWarning):
    """A projection would drop pydantic behavior from an un-carried base.

    Emitted once per canonical model by ``Model.scope(...)`` when a
    non-``ScopedModel`` base overrides ``model_dump``/``model_validate`` (or
    declares model validators/serializers) but is not carried. Declare
    ``projection_bases=(Base,)`` to carry it, or ``projection_bases=()`` to
    silence the warning.
    """


class PrismOrderingWarning(PrismWarning):
    """A ``@scoped_validator(mode="before")`` may run before a base's hook.

    Emitted at class definition when a model declares a
    ``@scoped_validator(mode="before")`` while inheriting a plain
    ``@model_validator(mode="before")`` from a non-``ScopedModel`` base.
    pydantic v2 runs the scoped validator *first* (child-first), so if it
    depends on the base hook's transformation it sees untransformed data. Fix
    by calling :meth:`ScopedModel.run_inherited_before` inside the validator, or
    assert independence with ``parent_ordering="acknowledged"`` to silence it.
    """


class ToolSchemaDepthWarning(PrismWarning):
    """An LLM tool schema nests objects deeper than the provider allows.

    Emitted by ``tool_schema(provider="openai", strict=True)`` when the
    projection's object nesting exceeds OpenAI's 5-level limit for strict
    structured outputs, or when a recursive (self-referential) model makes the
    depth unbounded. prism still returns the schema unchanged — the warning
    surfaces the likely API rejection at build time rather than as an opaque
    400 from the vendor. Project to a shallower scope, or drop ``strict=True``.
    """


class EmptyProjectionError(PrismError, ValueError):
    """A projection selected zero fields.

    Raised by ``Model.scope(...)`` when no field of the model belongs to the
    requested scope expression. An empty model is almost always a mistake
    (a typo'd scope, or a model whose fields were never tagged).
    """


class ProjectionNameError(PrismError, ValueError):
    """Two different scope expressions would produce one projection class name.

    Raised by ``Model.scope(...)`` when an auto-generated or explicit ``name=``
    is already taken by a projection of the same model with a different
    expression (e.g. two scopes that share a bare class name). Pass ``name=``
    to disambiguate.
    """


class ProjectionBaseError(PrismError, ValueError):
    """A carried base makes the requested projection impossible to honor.

    Raised by ``Model.scope(..., bases=...)`` when a field *declared on a
    carried base* is tagged with ``scoped(...)`` but the requested expression
    does not select it: inherited fields cannot be removed from a pydantic
    subclass, so the narrowing would silently leak the field instead.
    """


class RefResolutionError(PrismError, ValueError):
    """A ``ref``/``backref`` declaration could not be resolved.

    Raised lazily — on ``__prism__.refs`` access — when a string target does not
    name a ``ScopedModel`` in the owning model's module, or when a
    ``backref(..., via=...)`` does not line up with a forward ``ref`` on the
    target model.
    """
