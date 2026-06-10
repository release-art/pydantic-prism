"""pydantic-prism: one canonical pydantic model, many scoped projections.

Tag fields on a single model with named scopes via ``Annotated`` metadata,
derive real pydantic model subclasses per scope, and keep FK-style
relationships introspectable across projections.
"""

from ._markers import BackRef, Ref, Scoped, backref, ref, scoped
from ._model import Projection, ScopedModel
from ._refs import RefGraph, RefInfo, RefShape
from ._scopes import Scope, ScopeExpr
from ._validators import scoped_validator
from .errors import (
    EmptyProjectionError,
    PrismError,
    ProjectionBaseError,
    ProjectionNameError,
    RefResolutionError,
    StaleProjectionStubError,
)

__all__ = [
    "BackRef",
    "EmptyProjectionError",
    "PrismError",
    "Projection",
    "ProjectionBaseError",
    "ProjectionNameError",
    "Ref",
    "RefGraph",
    "RefInfo",
    "RefResolutionError",
    "RefShape",
    "Scope",
    "ScopeExpr",
    "Scoped",
    "ScopedModel",
    "StaleProjectionStubError",
    "backref",
    "ref",
    "scoped",
    "scoped_validator",
]
