"""Render annotations, scope expressions, and field defaults to source text."""

from __future__ import annotations

import enum
import inspect
import types
from dataclasses import dataclass, field
from typing import Any, Literal, Union, cast, get_args, get_origin

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
    "_render_behavior",
    "_render_bare",
    "_render_literal",
    "_render_scope_expr",
    "_render_type_ref",
]


# --- import bookkeeping ----------------------------------------------------


def _empty_import_set() -> set[tuple[str, str]]:
    return set()


def _empty_bindings() -> dict[tuple[str, str], str]:
    return {}


@dataclass(slots=True)
class _Imports:
    """Collected imports plus the bound name each is referenced by.

    ``runtime`` / ``typing_only`` hold ``(module, top_level_name)`` pairs. When
    two distinct modules export the same top-level name, the second is bound to
    an alias so the generated file references the right type — ``bound`` maps
    each ``(module, name)`` to the identifier actually used in source.
    """

    runtime: set[tuple[str, str]] = field(default_factory=_empty_import_set)
    typing_only: set[tuple[str, str]] = field(default_factory=_empty_import_set)
    bound: dict[tuple[str, str], str] = field(default_factory=_empty_bindings)

    def add_runtime(self, module: str, qualname: str) -> str:
        return self._bind(self.runtime, module, qualname)

    def add_typing(self, module: str, qualname: str) -> str:
        return self._bind(self.typing_only, module, qualname)

    def _bind(self, bucket: set[tuple[str, str]], module: str, qualname: str) -> str:
        base, _, rest = qualname.partition(".")
        key = (module, base)
        name = self.bound.get(key)
        if name is None:
            name = base if not self._taken(base) else self._alias(module, base)
            self.bound[key] = name
        bucket.add(key)
        return f"{name}.{rest}" if rest else name

    def _taken(self, name: str) -> bool:
        return name in self.bound.values()

    def _alias(self, module: str, base: str) -> str:
        stem = module.rsplit(".", 1)[-1]
        candidate = f"{stem}_{base}"
        suffix = 2
        while self._taken(candidate):
            candidate = f"{stem}_{base}_{suffix}"
            suffix += 1
        return candidate


def _import_lines(
    pairs: set[tuple[str, str]],
    indent: str,
    bound: dict[tuple[str, str], str] | None = None,
) -> list[str]:
    by_module: dict[str, set[str]] = {}
    for module, name in pairs:
        by_module.setdefault(module, set()).add(name)
    return [
        f"{indent}from {module} import "
        + ", ".join(_import_clause(module, name, bound) for name in sorted(names))
        for module, names in sorted(by_module.items())
    ]


def _import_clause(
    module: str, name: str, bound: dict[tuple[str, str], str] | None
) -> str:
    alias = bound.get((module, name)) if bound else None
    return f"{name} as {alias}" if alias and alias != name else name


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
        literal = imports.add_typing("typing", "Literal")
        return f"{literal}[{rendered}]"
    name = _render_type_ref(origin, imports)
    args = get_args(annotation)
    parts = [
        "..." if arg is Ellipsis else _render_annotation(arg, imports) for arg in args
    ]
    return f"{name}[{', '.join(parts)}]"


def _render_bare(annotation: Any, imports: _Imports) -> str:
    if annotation is Any:
        return imports.add_typing("typing", "Any")
    if annotation is MISSING:
        # the partial-scope optional marker (pydantic 2.12 sentinel)
        return imports.add_typing("pydantic.experimental.missing_sentinel", "MISSING")
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
    return imports.add_typing(module, qualname)


def _render_literal(value: Any, imports: _Imports) -> str:
    if value is None:
        return "None"
    if isinstance(value, enum.Enum):
        cls = type(value)
        ref = imports.add_typing(cls.__module__, cls.__qualname__)
        return f"{ref}.{value.name}"
    if isinstance(value, (bool, int, float, str, bytes)):
        return repr(value)
    raise CodegenError(f"cannot render Literal value {value!r} to source")


# --- scope-expression rendering --------------------------------------------


def _render_scope_expr(expr: ScopeExpr, imports: _Imports) -> str:
    if isinstance(expr, _Atom):
        scope = expr.scope
        return imports.add_runtime(scope.__module__, scope.__qualname__)
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
        name = imports.add_typing("pydantic.experimental.missing_sentinel", "MISSING")
        return f" = {name}"
    if info.default_factory is not None:
        for factory in _FACTORIES:
            if info.default_factory is factory:
                field_ref = imports.add_typing("pydantic", "Field")
                return f" = {field_ref}(default_factory={factory.__name__})"
        ref = _factory_ref(info.default_factory, imports)
        if ref is not None:
            field_ref = imports.add_typing("pydantic", "Field")
            return f" = {field_ref}(default_factory={ref})"
        return ""
    default = info.default
    if default is None:
        return " = None"
    if isinstance(default, (bool, int, float, str, bytes)):
        return f" = {default!r}"
    return ""


def _factory_ref(factory: Any, imports: _Imports) -> str | None:
    """An import reference for a ``default_factory`` callable, or ``None``.

    A module-level callable (a class or function with a resolvable ``__module__``
    / ``__qualname__``) renders as ``Field(default_factory=Name)`` so the stub
    field reads optional. A lambda or function-local callable is not importable —
    return ``None`` and let the field look required (conservative, never wrong).
    """
    module = getattr(factory, "__module__", None)
    qualname = getattr(factory, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(qualname, str):
        return None
    if "<locals>" in qualname or "<lambda>" in qualname:
        return None
    return imports.add_typing(module, qualname)


# --- behavior rendering ----------------------------------------------------


def _render_behavior(name: str, member: Any, imports: _Imports) -> list[str]:
    """Render a copied behavior as stub lines: decorator (if any), ``def``, ``...``.

    Mirrors the decorator (``@property`` / ``@classmethod`` / ``@staticmethod``)
    and the underlying function's signature so the projection's typed surface
    matches the runtime object prism copied on. The body is always ``...`` — the
    real implementation lives on the canonical at runtime.
    """
    if isinstance(member, property):
        return _render_def(name, "@property", member.fget, imports)
    if isinstance(member, classmethod):
        return _render_def(name, "@classmethod", cast(Any, member).__func__, imports)
    if isinstance(member, staticmethod):
        return _render_def(name, "@staticmethod", cast(Any, member).__func__, imports)
    return _render_def(name, None, member, imports)


def _render_def(
    name: str, decorator: str | None, func: Any, imports: _Imports
) -> list[str]:
    # eval_str resolves PEP 563 string annotations against the function's module;
    # if a name won't resolve we keep the signature but drop its annotations.
    try:
        sig = inspect.signature(func, eval_str=True)
        typed = True
    except Exception:  # noqa: BLE001 — any resolution failure → untyped fallback
        sig = inspect.signature(func)
        typed = False
    params = _render_params(sig, imports, typed)
    ret = ""
    if typed and sig.return_annotation is not inspect.Signature.empty:
        ret = f" -> {_safe_annotation(sig.return_annotation, imports)}"
    lines = [f"        {decorator}"] if decorator else []
    lines.append(f"        def {name}({params}){ret}: ...")
    return lines


def _render_params(sig: inspect.Signature, imports: _Imports, typed: bool) -> str:
    parts: list[str] = []
    star_seen = False
    for p in sig.parameters.values():
        if p.kind is p.VAR_POSITIONAL:
            parts.append(_annotate(f"*{p.name}", p, imports, typed))
            star_seen = True
            continue
        if p.kind is p.VAR_KEYWORD:
            parts.append(_annotate(f"**{p.name}", p, imports, typed))
            continue
        if p.kind is p.KEYWORD_ONLY and not star_seen:
            parts.append("*")
            star_seen = True
        piece = _annotate(p.name, p, imports, typed)
        if p.default is not inspect.Parameter.empty:
            piece += " = ..."
        parts.append(piece)
    return ", ".join(parts)


def _annotate(head: str, p: inspect.Parameter, imports: _Imports, typed: bool) -> str:
    """``head`` with a ``: T`` annotation appended when one is available."""
    if typed and p.annotation is not inspect.Parameter.empty:
        return f"{head}: {_safe_annotation(p.annotation, imports)}"
    return head


def _safe_annotation(annotation: Any, imports: _Imports) -> str:
    """Render an annotation, falling back to ``Any`` when it cannot be rendered."""
    try:
        return _render_annotation(annotation, imports)
    except CodegenError:
        return imports.add_typing("typing", "Any")
