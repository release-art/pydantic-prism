# Derive an LLM tool / function schema

**Goal:** hand an LLM a tool whose schema is exactly the fields the model should
see — no internal columns, no audit metadata — without hand-writing a parallel
schema dict. Tag the canonical model once, project to the scope the model may
fill in, and let prism emit the provider envelope.

The projection already does the hard part (it hides untagged and out-of-scope
fields and carries per-scope descriptions); `tool_schema()` is the thin layer
that normalizes that schema for a provider's strict mode and wraps it in the
provider's tool/function envelope. No vendor SDK is imported — you get a plain
`dict` to pass to `openai` / `anthropic` yourself.

## Tag a tool-input scope, then ask for the schema

```python
from typing import Annotated, Optional

from pydantic_prism import Scope, ScopedModel, scoped


class Tool(Scope, description="Create a calendar event."): ...


class Event(ScopedModel):
    title: Annotated[str, scoped(Tool)]
    attendees: Annotated[list[str], scoped(Tool)]
    notes: Annotated[Optional[str], scoped(Tool)] = None
    internal_id: int = 0  # untagged → never in any projection


tool = Event.tool_schema(Tool, provider="openai")

assert tool["type"] == "function"
assert tool["function"]["name"] == "EventTool"
assert tool["function"]["description"] == "Create a calendar event."
assert tool["function"]["strict"] is True

params = tool["function"]["parameters"]
# Untagged fields never leak into the tool the model sees.
assert "internal_id" not in params["properties"]
```

`Event.tool_schema(Tool, ...)` is the one-step convenience for
`Event.scope(Tool).tool_schema(...)` — the two return the same dict, so use
whichever reads better.

## What `strict=True` changes

OpenAI strict structured outputs require every property to be `required`, forbid
`default`, and express optionality as a `"null"` union. `strict=True` (the
default, and what OpenAI recommends) applies exactly those rewrites — the one
place prism rewrites types rather than only filtering fields:

```python
# Every property is required, even the ones that were optional.
assert set(params["required"]) == {"title", "attendees", "notes"}
# `notes` (Optional, default None) became a nullable union with no default.
assert {"type": "null"} in params["properties"]["notes"]["anyOf"]
assert "default" not in params["properties"]["notes"]
# Objects forbid unknown keys, at every level.
assert params["additionalProperties"] is False
```

## Anthropic: plain JSON Schema, no rewriting

Anthropic's tool `input_schema` is plain JSON Schema 2020-12 and honors
`required` as written — so target it with `strict=False` and the schema stays
faithful to your model's optionality:

```python
anthropic_tool = Event.tool_schema(Tool, provider="anthropic", strict=False)

assert set(anthropic_tool) == {"name", "input_schema", "description"}
# Only fields without a default are required — `notes` stays optional.
assert anthropic_tool["input_schema"]["required"] == ["title", "attendees"]
```

## Mistral: the OpenAI-compatible format

Mistral's tools use the same `{"type": "function", ...}` envelope as OpenAI
(including the optional `strict` flag), so `provider="mistral"` produces the
identical shape. Keep `strict=True` for its stricter validation, or pass
`strict=False` to leave the schema faithful:

```python
mistral_tool = Event.tool_schema(Tool, provider="mistral")
assert mistral_tool == Event.tool_schema(Tool, provider="openai")
```

The five-level depth limit below is an OpenAI structured-outputs constraint, so
it is **not** applied to Mistral.

## Mass-assignment-safe tool input

When the model is *writing* (the tool fills in a record you will persist), build
the write-side projection first so read-only (`Out`) fields are dropped — then
ask it for the schema. `tool_schema()` works on any projection:

```python
from pydantic_prism import Out


class Account(ScopedModel):
    email: Annotated[str, scoped(Tool)]
    created_at: Annotated[str, scoped(Tool, Out)]  # server-set, read-only


write_tool = Account.input(Tool).tool_schema(provider="openai")
# The model can't set a read-only field it should never control.
assert "created_at" not in write_tool["function"]["parameters"]["properties"]
assert "email" in write_tool["function"]["parameters"]["properties"]
```

## Override the name and description

`name` defaults to the projection class name and `description` falls back to a
description on the `Scope` class (above) or the model's docstring. Override
either explicitly — a good tool description is the single biggest lever on tool
performance:

```python
named = Event.tool_schema(
    Tool,
    provider="openai",
    name="create_event",
    description="Schedule a new calendar event for the user.",
)
assert named["function"]["name"] == "create_event"
```

## Depth limit

OpenAI strict structured outputs allow object nesting up to five levels. Under
`provider="openai", strict=True`, a schema that nests deeper than that — or a
recursive (self-referential) model, whose depth is unbounded — emits a
[`ToolSchemaDepthWarning`](../reference/errors.md) at build time and returns the
schema unchanged, so you learn about the likely rejection before the API does.
Project to a shallower scope, or drop `strict=True`, to resolve it.

## See also

- [Use projections with Pydantic AI](use-with-pydantic-ai.md) — on a framework
  that builds schemas from models, hand it the projection instead of an envelope.
- [Prevent mass-assignment](prevent-mass-assignment.md) — the `input()` /
  `output()` and `In` / `Out` mechanics the write-side example builds on.
- [Vary a field's schema per projection](vary-schema-per-scope.md) — set the
  per-scope `description` / `examples` that surface in the tool schema.
