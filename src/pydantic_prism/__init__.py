"""pydantic-prism: one canonical pydantic model, many scoped projections.

Tag fields on a single model with named scopes via ``Annotated`` metadata,
derive real pydantic model subclasses per scope, and keep FK-style
relationships introspectable across projections.
"""

from pydantic.experimental.missing_sentinel import MISSING

from ._internal.diagram import Diagram, projection_diagram, scope_diagram
from ._internal.flow import (
    ClassifiedField,
    FlowEdge,
    FlowNode,
    FlowReport,
    build_flow_report,
)
from ._internal.markers import BackRef, Ref, Scoped, backref, ref, scoped
from ._internal.model import Projection, ScopedModel
from ._internal.refs import (
    BackRefInfo,
    EmbeddedRefInfo,
    IdRefInfo,
    RefGraph,
    RefInfo,
    RefShape,
)
from ._internal.scopes import (
    Classification,
    Direction,
    In,
    Out,
    Scope,
    ScopeExpr,
)
from ._internal.validators import scoped_validator
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
    "Classification",
    "ClassifiedField",
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
]
