# Trace where scoped data flows

**Goal:** answer the question *given this entry point, where does scoped data
(PII and otherwise) live, and via which references?* — as a JSON artifact or a
diagram.

`data_flow()` walks the forward `ref` / embedded edges reachable from a model
(breadth-first, cycle-safe) and reports every **tagged** field of every model it
reaches, with the field's scopes grouped by **axis**. Axes are inferred
structurally from the scope inheritance forest (see
[`dimensions()`](../reference/api.md)), so PII surfaces under its `Classification`
root automatically — prism is never told which scope is "sensitive."

```python
from typing import Annotated
from uuid import UUID

from pydantic_prism import Classification, FlowReport, Scope, ScopedModel, ref, scoped


class Public(Scope): ...
class Pii(Classification): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Public), scoped(Pii)]


class Account(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    user_id: Annotated[UUID, ref(User), scoped(Public)]


report = Account.data_flow()
assert isinstance(report, FlowReport)
assert bool(report) is True                       # truthy iff tagged data is reachable
assert [node.model for node in report.nodes] == [Account, User]
```

`report.as_dict()` is the JSON artifact — every reachable tagged field, its
scopes grouped by axis (the `Classification` axis is the PII slice):

```python
assert report.as_dict() == {
    "root": "Account",
    "nodes": [
        {
            "model": "Account",
            "fields": [
                {"field": "id", "dimensions": {"Public": ["Public"]}},
                {"field": "user_id", "dimensions": {"Public": ["Public"]}},
            ],
        },
        {
            "model": "User",
            "fields": [
                {"field": "id", "dimensions": {"Public": ["Public"]}},
                {
                    "field": "email",
                    "dimensions": {"Classification": ["Pii"], "Public": ["Public"]},
                },
            ],
        },
    ],
    "edges": [
        {"source": "Account", "field": "user_id", "target": "User", "kind": "ref"}
    ],
}
```

For review, render the same report as a Mermaid `classDiagram` — multi-axis
models badge each field with its axes (`email [Pii]`):

```python
mermaid = report.to_mermaid()                     # or to_mermaid(direction="LR")
assert mermaid.startswith("classDiagram")
```

## From the shell

The `prism flow` subcommand does the same against a `module:Model` path:

```console
$ prism flow myapp.models:Account                 # JSON to stdout (default)
$ prism flow myapp.models:Account --format mermaid
$ prism flow myapp.models:Account --output flow.json
```

Wire the JSON form into CI to fail a build when PII (an axis rooted at your
`Classification` subclass) reaches a model it shouldn't. See the runnable
[`examples/pii_dataflow`](../../examples/pii_dataflow).
