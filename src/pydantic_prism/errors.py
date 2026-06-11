"""Exceptions raised by pydantic-prism.

Misuse of the API itself (wrong argument types, markers placed in field
defaults) raises plain :class:`TypeError`; these classes cover domain errors
that can only be detected once models and scopes are put together.
"""

__all__ = [
    "EmptyProjectionError",
    "PrismError",
    "ProjectionBaseError",
    "ProjectionNameError",
    "RefResolutionError",
    "StaleProjectionStubError",
]


class PrismError(Exception):
    """Base class for all pydantic-prism domain errors."""


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

    Raised lazily — on ``__refs__`` access — when a string target does not
    name a ``ScopedModel`` in the owning model's module, or when a
    ``backref(..., via=...)`` does not line up with a forward ``ref`` on the
    target model.
    """


class StaleProjectionStubError(PrismError, RuntimeError):
    """A generated projection stub no longer matches its canonical model.

    Raised at import of a ``prism gen``-generated module (i.e. application
    startup) when a projection's live shape no longer matches the signature
    recorded when the stub was generated — the model changed but the stub was
    not regenerated, so the static types it declares are lying. Re-run
    ``prism gen``. ``prism check`` surfaces the same drift as a CI gate.
    """
