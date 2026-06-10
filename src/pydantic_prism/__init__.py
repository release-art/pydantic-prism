"""pydantic-prism: one canonical pydantic model, many scoped projections.

Tag fields on a single model with named scopes via ``Annotated`` metadata,
derive real pydantic model subclasses per scope, and keep FK-style
relationships introspectable across projections.
"""

from pydantic.experimental.missing_sentinel import MISSING

from ._diagram import Diagram, projection_diagram, scope_diagram
from ._markers import BackRef, Ref, Scoped, backref, ref, scoped
from ._model import Projection, ScopedModel
from ._refs import (
    BackRefInfo,
    EmbeddedRefInfo,
    IdRefInfo,
    RefGraph,
    RefInfo,
    RefShape,
)
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
    "MISSING",
    "BackRef",
    "BackRefInfo",
    "Diagram",
    "EmbeddedRefInfo",
    "EmptyProjectionError",
    "IdRefInfo",
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
    "projection_diagram",
    "ref",
    "scope_diagram",
    "scoped",
    "scoped_validator",
]
