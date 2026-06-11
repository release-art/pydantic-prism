# Use projections with Pydantic AI

**Goal:** give a [Pydantic AI](https://ai.pydantic.dev) agent a narrowed view of
your model — so the LLM only ever sees the fields it should — without writing a
second schema.

Pydantic AI builds its tool and output schemas *itself*, from Pydantic model
classes and function signatures, and applies each model's strict-mode transform
through its own profiles. A prism projection **is** a real `BaseModel` subclass,
so the idiomatic integration is to hand Pydantic AI the **projection** — you
rarely need [`tool_schema()`](derive-llm-tool-schema.md) here at all. The
examples below use `TestModel` so they run offline; in real use you would pass a
model string like `"openai:gpt-4o"`.

## Setup

```python
from typing import Annotated

from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition

from pydantic_prism import Scope, ScopedModel, scoped


class LLMView(Scope, description="Create a customer order."): ...


class Order(ScopedModel):
    item: Annotated[str, scoped(LLMView)]
    quantity: Annotated[int, scoped(LLMView)]
    internal_cost: float = 0.0  # untagged → never in any projection


OrderView = Order.scope(LLMView)
```

## A. Projection as `output_type` (the natural fit)

Hand the projection straight to the agent. Pydantic AI generates the output-tool
schema from it; prism's job is the narrowing — `internal_cost` never appears.

```python
# In real use: Agent("openai:gpt-4o", output_type=OrderView)
agent = Agent(TestModel(), output_type=OrderView)
result = agent.run_sync("Order three widgets")

assert isinstance(result.output, OrderView)
assert "internal_cost" not in OrderView.model_json_schema()["properties"]
```

## B. Projection as a typed tool argument

A tool that takes the projection as its parameter type gets a schema built from
the projection — `input()` first drops read-only (`Out`) fields, so the model
can't over-post. Round-trip back to canonical with `from_projection`.

```python
order_agent = Agent(TestModel())


@order_agent.tool_plain
def create_order(order: OrderView) -> str:
    saved = Order.from_projection(order)
    return f"created order for {saved.item}"


b = order_agent.run_sync("order widgets")
assert "created order for" in str(b.output)
```

## C. A raw schema you control — `envelope=False`

When you drop to a low-level `Tool` and set the parameters schema yourself (a
`prepare` hook editing `ToolDefinition.parameters_json_schema`), prism gives you
exactly that shape with `envelope=False` — the normalized parameters schema with
no provider wrapper to dig through.

```python
def take_order(**fields: object) -> str:
    return f"received {sorted(fields)}"


async def use_prism_schema(
    ctx: RunContext[None], tool_def: ToolDefinition
) -> ToolDefinition:
    tool_def.parameters_json_schema = Order.input(LLMView).tool_schema(
        provider="openai", envelope=False
    )
    return tool_def


raw_tool = Tool(
    take_order,
    name="take_order",
    description="Create a customer order.",
    takes_ctx=False,
    prepare=use_prism_schema,
)
raw_agent = Agent(TestModel(), tools=[raw_tool])
c = raw_agent.run_sync("order widgets")
assert "received" in str(c.output)
```

## Which path

- **A / B** are the idiomatic ones: hand Pydantic AI the projection as a model
  and let it own schema generation. No `tool_schema()` needed.
- **C** is for when you control the raw parameters schema directly —
  `tool_schema(..., envelope=False)` returns just that dict.

The full envelope form of `tool_schema()` (with the `{"type": "function", ...}`
wrapper) is for calling the **raw** `openai` / `anthropic` / `mistral` SDKs — see
[derive an LLM tool schema](derive-llm-tool-schema.md). On Pydantic AI you want
the projection (A/B) or the bare schema (C).

## See also

- [Derive an LLM tool / function schema](derive-llm-tool-schema.md) — the
  envelope form, for the raw provider SDKs.
- [Prevent mass-assignment](prevent-mass-assignment.md) — the `input()` / `Out`
  mechanics path B relies on.
