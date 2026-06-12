"""Scope-attached JSON-schema metadata applied to a projection's fields/model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic.fields import FieldInfo

from ...markers import (
    _NO_TYPE,  # pyright: ignore[reportPrivateUsage] — intra-package
    Scoped,
)
from ..scopes import (
    Scope,
    ScopeExpr,
    _SchemaMeta,  # pyright: ignore[reportPrivateUsage] — intra-package
)

if TYPE_CHECKING:
    from ...model import ScopedModel

__all__ = [
    "_apply_field_spec",
    "_apply_model_schema",
    "_merge_constraints",
    "_merge_json_schema_extra",
    "_resolve_field_spec",
]


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


def _resolve_field_spec(
    cls: type[ScopedModel], field_name: str, expr: ScopeExpr
) -> Scoped | None:
    """The per-scope payload marker that applies in projection ``expr``, if any.

    Markers carrying a payload (``override`` / ``as_type`` / ``convert``) whose
    scope ``expr`` selects are candidates; the most-derived scope (a subclass of
    every other candidate) wins wholesale — the winning marker supplies *all*
    three aspects. Candidates with no subclass relation are ambiguous and raise.
    """
    candidates: list[tuple[type[Scope], Scoped]] = []
    for marker in cls.model_fields[field_name].metadata:
        if (
            isinstance(marker, Scoped)
            and _has_payload(marker)
            and expr.selects(marker.expr)
        ):
            scope = next(iter(marker.expr.atoms()))  # single atom (enforced)
            candidates.append((scope, marker))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]
    scopes = [scope for scope, _ in candidates]
    for scope, marker in candidates:
        if all(issubclass(scope, other) for other in scopes):
            return marker
    names = ", ".join(sorted(scope.__name__ for scope in scopes))
    raise TypeError(
        f"{cls.__name__}.{field_name}: ambiguous scoped() payload in projection "
        f"{expr!r}; scopes {names} all apply and are unrelated — attach the payload "
        f"to a single common scope or narrow the projection"
    )


def _has_payload(marker: Scoped) -> bool:
    """Whether a marker carries any per-scope payload (override/as_type/convert)."""
    return (
        marker.field_override is not None
        or marker.field_type is not _NO_TYPE
        or marker.convert is not None
    )


def _apply_field_spec(
    cls: type[ScopedModel], field_name: str, expr: ScopeExpr, info: FieldInfo
) -> Scoped | None:
    """Apply the resolved per-scope payload onto a projected ``FieldInfo``.

    Sets the overridden annotation (``as_type``) — *before* the caller rewrites
    nested models — then overlays the ``override`` ``FieldInfo`` (its
    explicitly-set scalar attributes, with ``json_schema_extra`` merged and
    constraints merged by kind). Returns the winning marker (so the builder can
    read its ``field_type`` for ref re-derivation and its ``convert``), or None.
    """
    marker = _resolve_field_spec(cls, field_name, expr)
    if marker is None:
        return None
    if marker.field_type is not _NO_TYPE:
        info.annotation = marker.field_type
    override = marker.field_override
    if override is not None:
        attributes_set: dict[str, Any] = override._attributes_set  # pyright: ignore[reportPrivateUsage]
        for key, value in attributes_set.items():
            if key == "json_schema_extra":
                info.json_schema_extra = _merge_json_schema_extra(
                    info.json_schema_extra, cast("dict[str, Any]", value)
                )
            else:
                setattr(info, key, value)
        if override.metadata:
            info.metadata = _merge_constraints(info.metadata, override.metadata)
    return marker


def _merge_constraints(canonical: list[Any], overlay: list[Any]) -> list[Any]:
    """Overlay per-scope constraints onto canonical ones, overriding by kind.

    A constraint *kind* is its concrete type (``MinLen`` vs ``MaxLen`` vs ``Ge``
    …, each distinct). Every kind present in ``overlay`` replaces the canonical
    entry of that kind; the rest of the canonical constraints inherit. Overrides
    are arbitrary — a looser bound is honored, so the projection can accept what
    the canonical rejects.
    """
    overridden: set[type[Any]] = {type(entry) for entry in overlay}
    kept = [entry for entry in canonical if type(entry) not in overridden]
    return [*kept, *overlay]


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
