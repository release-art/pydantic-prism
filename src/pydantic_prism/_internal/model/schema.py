"""Scope-attached JSON-schema metadata applied to a projection's fields/model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic.fields import FieldInfo

from ...markers import Scoped
from ..scopes import (
    Scope,
    ScopeExpr,
    _SchemaMeta,  # pyright: ignore[reportPrivateUsage] — intra-package
)

if TYPE_CHECKING:
    from ...model import ScopedModel

__all__ = ["_apply_field_schema", "_apply_model_schema", "_merge_json_schema_extra"]


def _merge_json_schema_extra(original: Any, extra: dict[str, Any]) -> Any:
    """Merge ``extra`` onto an existing ``json_schema_extra`` (dict or callable)."""
    if callable(original):

        def merged(*args: Any) -> None:
            original(*args)
            args[0].update(extra)  # args[0] is the schema dict in every arity

        return merged
    base = dict(original or {})
    base.update(extra)
    return base


def _resolve_field_schema(
    cls: type[ScopedModel], field_name: str, expr: ScopeExpr
) -> _SchemaMeta | None:
    """The per-scope field schema that applies in projection ``expr``, if any.

    Markers whose scope ``expr`` selects are candidates; the most-derived scope
    (a subclass of every other candidate) wins. Candidates with no subclass
    relation are ambiguous and raise.
    """
    candidates: list[tuple[type[Scope], _SchemaMeta]] = []
    for marker in cls.model_fields[field_name].metadata:
        if (
            isinstance(marker, Scoped)
            and marker.field_schema is not None
            and expr.selects(marker.expr)
        ):
            scope = next(iter(marker.expr.atoms()))  # single atom (enforced)
            candidates.append((scope, marker.field_schema))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]
    scopes = [scope for scope, _ in candidates]
    for scope, schema in candidates:
        if all(issubclass(scope, other) for other in scopes):
            return schema
    names = ", ".join(sorted(scope.__name__ for scope in scopes))
    raise TypeError(
        f"{cls.__name__}.{field_name}: ambiguous scoped() schema in projection "
        f"{expr!r}; scopes {names} all apply and are unrelated — attach the schema "
        f"to a single common scope or narrow the projection"
    )


def _apply_field_schema(
    cls: type[ScopedModel], field_name: str, expr: ScopeExpr, info: FieldInfo
) -> None:
    """Overlay the resolved per-scope field schema onto a projected ``FieldInfo``."""
    schema = _resolve_field_schema(cls, field_name, expr)
    if schema is None:
        return
    if "description" in schema:
        info.description = schema["description"]
    if "examples" in schema:
        info.examples = list(schema["examples"])
    if "json_schema_extra" in schema:
        info.json_schema_extra = _merge_json_schema_extra(
            info.json_schema_extra, schema["json_schema_extra"]
        )


def _apply_model_schema(expr: ScopeExpr, model_config: Any) -> None:
    """Merge the model-level schema of ``expr``'s scopes into ``model_config``."""
    extra: dict[str, Any] = {}
    for atom in sorted(expr.atoms(), key=lambda scope: scope.__name__):
        schema: _SchemaMeta | None = vars(atom).get("__prism_model_schema__")
        if not schema:
            continue
        if "description" in schema:
            extra["description"] = schema["description"]
        if "examples" in schema:
            extra["examples"] = list(schema["examples"])
        if "json_schema_extra" in schema:
            extra.update(schema["json_schema_extra"])
    if extra:
        model_config["json_schema_extra"] = _merge_json_schema_extra(
            model_config.get("json_schema_extra"), extra
        )
