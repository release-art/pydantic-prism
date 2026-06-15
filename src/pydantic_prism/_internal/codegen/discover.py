"""Discover the (model, scope, name) projections to generate, + the workset."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast, get_args

from ..model import Projection, ScopedModel
from ..scopes import ScopeExpr, as_expr, union_all
from .config import CodegenError, Config, ExtraPolicy, ProjectionKind

__all__ = ["_build_workset", "_discover", "_projections_in", "_reject_name_clashes"]


@dataclass(slots=True)
class _Plan:
    """A planned top-level projection.

    For ``kind == "scope"`` ``expr`` is the scope expression to project; for
    ``"input"`` / ``"output"`` ``expr`` is the *visible* scope (the directional
    method subtracts ``Out`` / ``In`` itself). ``extra`` only applies to input.
    """

    source: type[ScopedModel]
    expr: ScopeExpr
    name: str | None
    kind: ProjectionKind = "scope"
    extra: ExtraPolicy | None = None

    def build(self) -> type[Projection]:
        if self.kind == "input":
            if self.extra is None:
                return self.source.input(self.expr, name=self.name)
            return self.source.input(self.expr, name=self.name, extra=self.extra)
        if self.kind == "output":
            return self.source.output(self.expr, name=self.name)
        return self.source.scope(self.expr, name=self.name)


def _resolve(path: str) -> Any:
    module_name, sep, attr = path.partition(":")
    if not sep or not attr:
        raise CodegenError(f"{path!r}: expected a 'package.module:Name' path")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # noqa: F841 — message includes the path
        raise CodegenError(f"{path!r}: cannot import module {module_name!r}") from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise CodegenError(
            f"{path!r}: {module_name!r} has no attribute {attr!r}"
        ) from exc


_PlanKey = tuple[
    type[ScopedModel], ScopeExpr, str | None, ProjectionKind, ExtraPolicy | None
]


def _discover(config: Config) -> list[_Plan]:
    """The planned projections to generate, deduplicated."""
    if str(config.root) not in sys.path:
        sys.path.insert(0, str(config.root))
    plans: dict[_PlanKey, _Plan] = {}

    def add(plan: _Plan) -> None:
        key: _PlanKey = (plan.source, plan.expr, plan.name, plan.kind, plan.extra)
        plans.setdefault(key, plan)

    for module_name in config.modules:
        module = importlib.import_module(module_name)
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, ScopedModel)
                and obj is not ScopedModel
                and obj.__module__ == module_name
            ):
                for scope in sorted(obj.scopes(), key=lambda s: s.__name__):
                    add(_Plan(obj, as_expr(scope), None))

    for spec in config.projections:
        source = _resolve(spec.model)
        if not (isinstance(source, type) and issubclass(source, ScopedModel)):
            raise CodegenError(f"{spec.model!r} is not a ScopedModel subclass")
        expr = union_all(as_expr(_resolve(path)) for path in spec.scopes)
        add(_Plan(source, expr, spec.name, spec.kind, spec.extra))

    return list(plans.values())


def _build_workset(
    plans: Sequence[_Plan],
) -> tuple[list[type[Projection]], dict[type[Projection], _Plan]]:
    """Build planned projections and every nested projection they reference.

    Returns the ordered, clash-checked workset plus a map from each *top-level*
    built projection back to its plan, so the alias renderer can emit the
    matching ``.scope()`` / ``.input()`` / ``.output()`` runtime call. Nested
    projections collected from field annotations are absent from the map (they
    are always plain ``.scope()`` projections).
    """
    workset: dict[type[Projection], None] = {}
    directives: dict[type[Projection], _Plan] = {}
    for plan in plans:
        built = plan.build()
        directives.setdefault(built, plan)
        _collect(built, workset)
    ordered = sorted(workset, key=lambda p: p.__name__)
    _reject_name_clashes(ordered)
    return ordered, directives


def _collect(proj: type[Projection], workset: dict[type[Projection], None]) -> None:
    if proj in workset:
        return
    workset[proj] = None
    for info in proj.model_fields.values():
        for nested in _projections_in(info.annotation):
            _collect(nested, workset)


def _reject_name_clashes(projections: Sequence[type[Projection]]) -> None:
    seen: dict[str, type[Projection]] = {}
    for proj in projections:
        other = seen.get(proj.__name__)
        if other is not None and other is not proj:
            raise CodegenError(
                f"two projections share the generated name {proj.__name__!r} "
                f"(of {other.__prism__.source.__name__} and "
                f"{proj.__prism__.source.__name__}); pass a distinct name= via a "
                f"projections entry"
            )
        seen[proj.__name__] = proj


def _projections_in(annotation: Any) -> list[type[Projection]]:
    found: list[type[Projection]] = []
    _walk_projections(annotation, found)
    return found


def _walk_projections(annotation: Any, out: list[type[Projection]]) -> None:
    while hasattr(annotation, "__metadata__"):
        annotation = get_args(annotation)[0]
    if isinstance(annotation, type):
        if issubclass(annotation, Projection) and annotation is not Projection:
            out.append(annotation)
        return
    for arg in get_args(annotation):
        if isinstance(arg, list):  # Callable parameter lists
            for item in cast(list[Any], arg):
                _walk_projections(item, out)
        else:
            _walk_projections(arg, out)
