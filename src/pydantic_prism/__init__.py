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
    PrismBaseDropWarning,
    PrismError,
    PrismOrderingWarning,
    PrismWarning,
    ProjectionBaseError,
    ProjectionNameError,
    RefResolutionError,
    ToolSchemaDepthWarning,
)
from .flow import (
    FlowEdge,
    FlowField,
    FlowNode,
    FlowReport,
    build_flow_report,
)
from .markers import BackRef, Converter, Heritage, Ref, Scoped, backref, ref, scoped
from .model import ModelState, Projection, ProjectionState, ScopedModel, unprojected
from .refs import (
    BackRefInfo,
    EmbeddedRefInfo,
    IdRefInfo,
    RefGraph,
    RefInfo,
    RefShape,
)
from .scopes import Classification, Direction, In, Out
from .toolschema import ToolProvider
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
    "Converter",
    "FlowField",
    "Diagram",
    "Direction",
    "EmbeddedRefInfo",
    "EmptyProjectionError",
    "FlowEdge",
    "Heritage",
    "FlowNode",
    "FlowReport",
    "IdRefInfo",
    "In",
    "ModelState",
    "ProjectionState",
    "Out",
    "PrismBaseDropWarning",
    "PrismError",
    "PrismOrderingWarning",
    "PrismWarning",
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
    "ToolProvider",
    "ToolSchemaDepthWarning",
    "backref",
    "build_flow_report",
    "projection_diagram",
    "ref",
    "scope_diagram",
    "scoped",
    "scoped_validator",
    "unprojected",
    "__version__",
]
