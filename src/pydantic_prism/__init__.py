"""pydantic-prism: one canonical pydantic model, many scoped projections.

Tag fields on a single model with named scopes via ``Annotated`` metadata,
derive real pydantic model subclasses per scope, and keep FK-style
relationships introspectable across projections.
"""

from importlib.metadata import PackageNotFoundError, version

from pydantic.experimental.missing_sentinel import MISSING

from ._internal.scopes import Scope, ScopeExpr
from .diagram import Diagram, projection_diagram, scope_diagram
from .errors import (
    EmptyProjectionError,
    PrismError,
    ProjectionBaseError,
    ProjectionNameError,
    RefResolutionError,
    StaleProjectionStubError,
)
from .flow import (
    FlowEdge,
    FlowField,
    FlowNode,
    FlowReport,
    build_flow_report,
)
from .markers import BackRef, Ref, Scoped, backref, ref, scoped
from .model import Projection, ScopedModel
from .refs import (
    BackRefInfo,
    EmbeddedRefInfo,
    IdRefInfo,
    RefGraph,
    RefInfo,
    RefShape,
)
from .scopes import Classification, Direction, In, Out
from .validators import scoped_validator

try:
    __version__ = version("pydantic-prism")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

__all__ = [
    "MISSING",
    "BackRef",
    "BackRefInfo",
    "Classification",
    "FlowField",
    "Diagram",
    "Direction",
    "EmbeddedRefInfo",
    "EmptyProjectionError",
    "FlowEdge",
    "FlowNode",
    "FlowReport",
    "IdRefInfo",
    "In",
    "Out",
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
    "build_flow_report",
    "projection_diagram",
    "ref",
    "scope_diagram",
    "scoped",
    "scoped_validator",
    "__version__",
]
