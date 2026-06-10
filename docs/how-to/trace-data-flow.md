# Trace where classified data flows

**Goal:** answer the compliance question *given this entry point, where does
classified data live, and via which references?* — as a JSON artifact or a
diagram.

`classified_flow()` walks the forward `ref` / embedded edges reachable from a
model (breadth-first, cycle-safe) and reports the classified fields of every
model it reaches.

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


report = Account.classified_flow()
assert isinstance(report, FlowReport)
assert bool(report) is True                       # truthy iff classified data is reachable
assert [node.model for node in report.nodes] == [User]
```

`report.as_dict()` is the JSON artifact — `Account` itself holds nothing
classified, but it reaches `User.email`:

```python
assert report.as_dict() == {
    "root": "Account",
    "nodes": [
        {"model": "User", "fields": [{"field": "email", "classifications": ["Pii"]}]}
    ],
    "edges": [
        {"source": "Account", "field": "user_id", "target": "User", "kind": "ref"}
    ],
}
```

For review, render the same report as a Mermaid `classDiagram`:

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

Wire the JSON form into CI to fail a build when personal data reaches a model
it shouldn't. See the runnable [`examples/pii_dataflow`](../../examples/pii_dataflow).
