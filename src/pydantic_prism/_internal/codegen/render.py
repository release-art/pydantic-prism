"""Render annotations, scope expressions, and field defaults to source text."""

from __future__ import annotations

import enum
import types
from dataclasses import dataclass, field
from typing import Any, Literal, Union, get_args, get_origin

from pydantic.experimental.missing_sentinel import MISSING

from ..model import Projection
from ..scopes import (
    ScopeExpr,
    _Atom,  # pyright: ignore[reportPrivateUsage] — intra-package expr rendering
    _Complement,  # pyright: ignore[reportPrivateUsage]
    _Difference,  # pyright: ignore[reportPrivateUsage]
    _Intersection,  # pyright: ignore[reportPrivateUsage]
    _Union,  # pyright: ignore[reportPrivateUsage]
)
from .config import CodegenError

__all__ = [
    "_Imports",
    "_field_suffix",
    "_import_lines",
    "_render_annotation",
    "_render_bare",
    "_render_literal",
    "_render_scope_expr",
    "_render_type_ref",
]


# --- import bookkeeping ----------------------------------------------------


def _empty_import_set() -> set[tuple[str, str]]:
    return set()


@dataclass
class _Imports:
    runtime: set[tuple[str, str]] = field(default_factory=_empty_import_set)
    typing_only: set[tuple[str, str]] = field(default_factory=_empty_import_set)

    def add_runtime(self, module: str, name: str) -> None:
        self.runtime.add((module, name))

    def add_typing(self, module: str, name: str) -> None:
        self.typing_only.add((module, name))


def _import_lines(pairs: set[tuple[str, str]], indent: str) -> list[str]:
    by_module: dict[str, set[str]] = {}
    for module, name in pairs:
        by_module.setdefault(module, set()).add(name)
    return [
        f"{indent}from {module} import {', '.join(sorted(by_module[module]))}"
        for module in sorted(by_module)
    ]


# --- annotation rendering --------------------------------------------------


def _render_annotation(annotation: Any, imports: _Imports) -> str:
    while hasattr(annotation, "__metadata__"):  # strip Annotated (typing only)
        annotation = get_args(annotation)[0]
    if annotation is None or annotation is types.NoneType:
        return "None"
    origin = get_origin(annotation)
    if origin is None:
        return _render_bare(annotation, imports)
    if origin is Union or origin is types.UnionType:
        return " | ".join(_render_annotation(a, imports) for a in get_args(annotation))
    if origin is Literal:
        rendered = ", ".join(_render_literal(v, imports) for v in get_args(annotation))
        imports.add_typing("typing", "Literal")
        return f"Literal[{rendered}]"
    name = _render_type_ref(origin, imports)
    args = get_args(annotation)
    parts = [
        "..." if arg is Ellipsis else _render_annotation(arg, imports) for arg in args
    ]
    return f"{name}[{', '.join(parts)}]"


def _render_bare(annotation: Any, imports: _Imports) -> str:
    if annotation is Any:
        imports.add_typing("typing", "Any")
        return "Any"
    if annotation is MISSING:
        # the partial-scope optional marker (pydantic 2.12 sentinel)
        imports.add_typing("pydantic.experimental.missing_sentinel", "MISSING")
        return "MISSING"
    if isinstance(annotation, type):
        return _render_type_ref(annotation, imports)
    raise CodegenError(
        f"cannot render annotation {annotation!r} to source; only concrete "
        f"types, unions, Optional, Literal, and standard containers are supported"
    )


def _render_type_ref(tp: type[Any], imports: _Imports) -> str:
    if issubclass(tp, Projection) and tp is not Projection:
        return tp.__name__  # sibling stub class; forward-referenced by name
    module = tp.__module__
    qualname = tp.__qualname__
    if module == "builtins":
        return qualname
    imports.add_typing(module, qualname.split(".")[0])
    return qualname


def _render_literal(value: Any, imports: _Imports) -> str:
    if value is None:
        return "None"
    if isinstance(value, enum.Enum):
        cls = type(value)
        imports.add_typing(cls.__module__, cls.__qualname__.split(".")[0])
        return f"{cls.__qualname__}.{value.name}"
    if isinstance(value, (bool, int, float, str, bytes)):
        return repr(value)
    raise CodegenError(f"cannot render Literal value {value!r} to source")


# --- scope-expression rendering --------------------------------------------


def _render_scope_expr(expr: ScopeExpr, imports: _Imports) -> str:
    if isinstance(expr, _Atom):
        scope = expr.scope
        imports.add_runtime(scope.__module__, scope.__qualname__.split(".")[0])
        return scope.__qualname__
    if isinstance(expr, _Union):
        return (
            "("
            + " | ".join(_render_scope_expr(o, imports) for o in expr.operands)
            + ")"
        )
    if isinstance(expr, _Intersection):
        return (
            "("
            + " & ".join(_render_scope_expr(o, imports) for o in expr.operands)
            + ")"
        )
    if isinstance(expr, _Difference):
        left = _render_scope_expr(expr.left, imports)
        right = _render_scope_expr(expr.right, imports)
        return f"({left} - {right})"
    if isinstance(expr, _Complement):
        return f"~{_render_scope_expr(expr.operand, imports)}"
    raise CodegenError(f"cannot render scope expression {expr!r} to source")


# --- field rendering -------------------------------------------------------

_FACTORIES: tuple[type[Any], ...] = (list, dict, set, frozenset, tuple)


def _field_suffix(info: Any, imports: _Imports) -> str:
    """The ``= default`` tail for a stub field, type-correct or omitted.

    Required fields get nothing. Optional fields are made optional in the
    synthesized constructor only when the default renders cleanly (``None``, a
    simple literal, a known builtin ``default_factory``, or the partial-scope
    ``MISSING`` sentinel); anything exotic is left looking required — the runtime
    object is authoritative, so this only makes the stub's constructor
    conservative, never wrong.
    """
    if info.is_required():
        return ""
    if info.default is MISSING:  # partial-scope field
        imports.add_typing("pydantic.experimental.missing_sentinel", "MISSING")
        return " = MISSING"
    if info.default_factory is not None:
        for factory in _FACTORIES:
            if info.default_factory is factory:
                imports.add_typing("pydantic", "Field")
                return f" = Field(default_factory={factory.__name__})"
        return ""
    default = info.default
    if default is None:
        return " = None"
    if isinstance(default, (bool, int, float, str, bytes)):
        return f" = {default!r}"
    return ""
