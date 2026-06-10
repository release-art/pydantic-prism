"""Exceptions raised by pydantic-prism.

Misuse of the API itself (wrong argument types, markers placed in field
defaults) raises plain :class:`TypeError`; these classes cover domain errors
that can only be detected once models and scopes are put together.
"""

__all__ = ["EmptyProjectionError", "PrismError", "RefResolutionError"]


class PrismError(Exception):
    """Base class for all pydantic-prism domain errors."""


class EmptyProjectionError(PrismError, ValueError):
    """A projection selected zero fields.

    Raised by ``Model.scope(...)`` when no field of the model belongs to the
    requested scope expression. An empty model is almost always a mistake
    (a typo'd scope, or a model whose fields were never tagged).
    """


class RefResolutionError(PrismError, ValueError):
    """A ``ref``/``backref`` declaration could not be resolved.

    Raised lazily — on ``__refs__`` access — when a string target does not
    name a ``ScopedModel`` in the owning model's module, or when a
    ``backref(..., via=...)`` does not line up with a forward ``ref`` on the
    target model.
    """
