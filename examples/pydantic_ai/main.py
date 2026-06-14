"""Use a prism projection with a Pydantic AI agent.

A projection is a real ``BaseModel`` subclass, so Pydantic AI can take it
directly — as an agent's ``output_type`` or as a tool's typed argument — and
build the schema itself. The LLM only ever sees the scoped fields; the untagged
``internal_cost`` never reaches the model.

Run it (offline, via ``TestModel`` — no API key needed)::

    python examples/pydantic_ai/main.py
"""

from __future__ import annotations

from typing import Annotated

from pydantic_prism import Scope, ScopedModel, scoped


class LLMView(Scope, description="Create a customer order."): ...


class Order(ScopedModel):
    item: Annotated[str, scoped(LLMView)]
    quantity: Annotated[int, scoped(LLMView)]
    internal_cost: float = 0.0  # untagged → never in any projection


OrderView = Order.scope(LLMView)


def demo() -> None:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    # In real use: Agent("openai:gpt-4o", output_type=OrderView)
    agent = Agent(TestModel(), output_type=OrderView)
    result = agent.run_sync("Order three widgets")
    print("output_type result:", result.output.model_dump())
    print("fields the model saw:", list(OrderView.model_json_schema()["properties"]))

    tool_agent = Agent(TestModel())

    @tool_agent.tool_plain
    def create_order(order: OrderView) -> str:
        saved = Order.from_projection(order)
        return f"created order for {saved.item}"

    print("tool result:", tool_agent.run_sync("order widgets").output)


if __name__ == "__main__":
    demo()
