"""Derive LLM tool / function schemas from a projection.

A projection already filters fields and carries per-scope ``description`` /
``examples`` (see :mod:`pydantic_prism._internal.model.schema`), so its
``model_json_schema()`` is most of an LLM tool schema already. This module is
the thin remainder: it **normalizes** that schema for a provider's strict mode
and wraps it in the provider's tool envelope.

The normalization is the one place prism rewrites types rather than only
filtering fields — and it is gated behind an explicit ``strict=True``. OpenAI
strict structured outputs require every property to be ``required``, forbid
``default``, and express optionality as a ``"null"`` union; ``strict`` applies
exactly those rewrites. Anthropic tool ``input_schema`` is plain JSON Schema and
needs none of them, so a non-strict call leaves the schema as pydantic emitted
it. Mistral uses the OpenAI-compatible tools format, so it shares the OpenAI
envelope; the OpenAI-specific 5-level depth check is *not* applied to it.

No vendor SDK is imported: every function returns plain ``dict`` objects that
the caller hands to ``openai`` / ``anthropic`` / ``mistral`` themselves.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Literal, cast

from .errors import ToolSchemaDepthWarning

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import BaseModel

__all__ = ["ToolProvider"]

ToolProvider = Literal["openai", "anthropic", "mistral"]

# OpenAI strict structured outputs allow object nesting up to this depth.
_OPENAI_MAX_DEPTH = 5

# Schema keywords that describe a field rather than constrain its value; they
# stay outside the nullable union so the description survives the rewrite.
_META_KEYS = frozenset(
    {"description", "title", "examples", "deprecated", "readOnly", "writeOnly"}
)

# How a key's value carries nested schemas: a mapping of them, a list of them,
# or a single one. ``$defs``/``properties`` map names to schemas.
_MAP_KEYS = ("$defs", "properties")
_LIST_KEYS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SINGLE_KEYS = ("items", "additionalProperties", "not")


def build(
    projection: type[BaseModel],
    *,
    provider: ToolProvider,
    strict: bool,
    name: str | None,
    description: str | None,
    envelope: bool,
) -> dict[str, Any]:
    """Normalize a projection's JSON schema, optionally wrapping it in an envelope.

    With ``envelope=True`` (the default) returns the provider's tool/function
    envelope; with ``envelope=False`` returns just the normalized parameters
    schema — the shape a framework wants for its own tool definition (e.g.
    Pydantic AI's ``ToolDefinition.parameters_json_schema``).
    """
    schema = projection.model_json_schema()
    schema.pop("title", None)
    schema_description = schema.pop("description", None)
    # A projection's auto __doc__ ("Projection of X to scope Y.") is an internal
    # artifact, not a tool description; ignore it and fall back to the canonical
    # model's own docstring. A *deliberate* per-scope description (set via the
    # vary-schema mechanism) differs from __doc__ and is kept.
    if schema_description == projection.__doc__:
        source = getattr(getattr(projection, "__prism__", None), "source", None)
        schema_description = getattr(source, "__doc__", None)
    tool_name = name or projection.__name__
    tool_description = description or schema_description
    if strict:
        _strictify(schema)
    if provider == "openai" and strict:
        _check_depth(schema, tool_name)
    if not envelope:
        return schema
    return _envelope(
        schema,
        provider=provider,
        name=tool_name,
        description=tool_description,
        strict=strict,
    )


def _envelope(
    schema: dict[str, Any],
    *,
    provider: ToolProvider,
    name: str,
    description: str | None,
    strict: bool,
) -> dict[str, Any]:
    """Wrap a normalized schema in the provider's tool/function envelope."""
    if provider in ("openai", "mistral"):
        # Mistral uses the OpenAI-compatible tools format: a `type: function`
        # wrapper with name/description/parameters and an optional `strict` flag.
        function: dict[str, Any] = {
            "name": name,
            "parameters": schema,
            "strict": strict,
        }
        if description:
            function["description"] = description
        return {"type": "function", "function": function}
    if provider == "anthropic":
        tool: dict[str, Any] = {"name": name, "input_schema": schema}
        if description:
            tool["description"] = description
        return tool
    raise ValueError(f"unknown tool provider: {provider!r}")  # noqa: TRY003


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Narrow a JSON value to a schema dict (typed), or None."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _as_list(value: Any) -> list[Any] | None:
    """Narrow a JSON value to a list (typed), or None."""
    return cast("list[Any]", value) if isinstance(value, list) else None


def _subschemas(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every nested schema dict reachable one level below ``schema``."""
    for key in _MAP_KEYS:
        mapping = _as_dict(schema.get(key))
        for value in mapping.values() if mapping else ():
            child = _as_dict(value)
            if child is not None:
                yield child
    for child in _children(schema):
        yield child


def _children(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield nested schemas that do not add an object-nesting level."""
    for key in _LIST_KEYS:
        items = _as_list(schema.get(key))
        for value in items or ():
            child = _as_dict(value)
            if child is not None:
                yield child
    for key in _SINGLE_KEYS:
        child = _as_dict(schema.get(key))
        if child is not None:
            yield child


def _strictify(schema: dict[str, Any]) -> None:
    """Recursively rewrite ``schema`` in place to satisfy OpenAI strict mode.

    Every object gets ``additionalProperties: false`` and lists *all* its
    properties as ``required``; any property that was optional or carried a
    ``default`` is made nullable and its ``default`` dropped. ``$ref`` strings
    are never followed (recursive models do not loop) — each ``$defs`` entry is
    normalized once where it is defined.
    """
    properties = _as_dict(schema.get("properties"))
    if properties is not None:
        required = set(schema.get("required", []))
        for field_name, value in properties.items():
            # A JSON Schema "properties" value is always an object schema.
            field = cast("dict[str, Any]", value)
            optional = field_name not in required or "default" in field
            field.pop("default", None)
            if optional:
                _make_nullable(field)
        schema["required"] = list(properties)
        schema["additionalProperties"] = False
    for subschema in _subschemas(schema):
        _strictify(subschema)


def _make_nullable(schema: dict[str, Any]) -> None:
    """Add ``{"type": "null"}`` to ``schema``'s type union, in place."""
    any_of = _as_list(schema.get("anyOf"))
    if any_of is not None:
        if {"type": "null"} not in any_of:
            any_of.append({"type": "null"})
        return
    meta = {key: schema.pop(key) for key in list(schema) if key in _META_KEYS}
    inner = {key: schema.pop(key) for key in list(schema)}
    schema["anyOf"] = [inner, {"type": "null"}]
    schema.update(meta)


def _check_depth(schema: dict[str, Any], name: str) -> None:
    """Warn when object nesting exceeds OpenAI's strict-mode depth limit."""
    defs: dict[str, Any] = _as_dict(schema.get("$defs")) or {}
    depth, path, recursive = _object_depth(schema, defs, frozenset(), [])
    if recursive:
        warnings.warn(
            f"Tool schema {name!r} references a recursive (self-referential) model "
            f"(path: {' → '.join(path) or '<root>'}); OpenAI strict structured "
            f"outputs cannot express unbounded nesting. The schema is returned "
            f"unchanged; the API will likely reject it.",
            ToolSchemaDepthWarning,
            stacklevel=3,
        )
    elif depth > _OPENAI_MAX_DEPTH:
        warnings.warn(
            f"Tool schema {name!r} nests objects {depth} levels deep "
            f"(path: {' → '.join(path)}); OpenAI strict structured outputs allow at "
            f"most {_OPENAI_MAX_DEPTH}. The schema is returned unchanged; the API "
            f"will likely reject it.",
            ToolSchemaDepthWarning,
            stacklevel=3,
        )


def _object_depth(
    node: dict[str, Any],
    defs: dict[str, Any],
    active: frozenset[str],
    path: list[str],
) -> tuple[int, list[str], bool]:
    """Max object-nesting depth reachable from ``node``, resolving ``$ref``.

    Returns ``(depth, deepest_path, recursive)``. ``active`` is the set of
    ``$defs`` names on the current resolution path; re-entering one means the
    model is recursive (its depth is unbounded under strict mode).
    """
    ref = node.get("$ref")
    if isinstance(ref, str):
        return _ref_depth(ref, defs, active, path)

    best_depth, best_path, recursive = 0, path, False

    properties = _as_dict(node.get("properties"))
    if properties is not None:
        for field_name, value in properties.items():
            # A JSON Schema "properties" value is always an object schema.
            field = cast("dict[str, Any]", value)
            depth, sub_path, sub_recursive = _object_depth(
                field, defs, active, [*path, str(field_name)]
            )
            recursive = recursive or sub_recursive
            if depth + 1 > best_depth:
                best_depth, best_path = depth + 1, sub_path
        # An object with no nested objects is still one level of nesting.
        best_depth = max(best_depth, 1)

    for child in _children(node):
        depth, sub_path, sub_recursive = _object_depth(child, defs, active, path)
        recursive = recursive or sub_recursive
        if depth > best_depth:
            best_depth, best_path = depth, sub_path

    return best_depth, best_path, recursive


def _ref_depth(
    ref: str,
    defs: dict[str, Any],
    active: frozenset[str],
    path: list[str],
) -> tuple[int, list[str], bool]:
    """Depth of a ``$ref`` target, flagging a recursive (re-entered) one."""
    target_name = ref.rsplit("/", 1)[-1]
    if target_name in active:
        return 0, path, True
    target = _as_dict(defs.get(target_name))
    if target is None:  # pragma: no cover - malformed $ref
        return 0, path, False
    return _object_depth(target, defs, active | {target_name}, path)
