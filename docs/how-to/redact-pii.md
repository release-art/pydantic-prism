# Redact PII for an audit view

**Goal:** derive a view that keeps a normal visibility scope but strips every
field carrying sensitive data — an audit/log-safe projection — without writing
a parallel class.

Classification is an axis *orthogonal* to visibility: a field can be `Public`
**and** `Pii`. Declare classification tags by subclassing `Classification`,
then let `redacted(...)` do the set difference for you.

```python
from typing import Annotated
from uuid import UUID

from pydantic_prism import Classification, Scope, ScopedModel, scoped


class Public(Scope): ...
class Internal(Public): ...

class Pii(Classification): ...
class Secret(Classification): ...


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Public), scoped(Pii)]
    password_hash: Annotated[str, scoped(Internal), scoped(Secret)]
```

`redacted(Internal)` is the `Internal` projection with **every** classification
the model declares removed:

```python
UserAudit = User.redacted(Internal)
assert set(UserAudit.model_fields) == {"id"}        # email (Pii) and hash (Secret) gone
```

The default strips the union of all classifications on the model, so a new
classification added later is auto-redacted — the safe direction. Pass `strip=`
to remove only some:

```python
SecretsOut = User.redacted(Internal, strip=Secret)  # strip Secret, keep Pii
assert set(SecretsOut.model_fields) == {"id", "email"}
```

Refs survive redaction, so the relationship graph stays intact. To inventory
what is classified before redacting:

```python
assert User.classifications() == frozenset({Pii, Secret})
assert User.classified_fields() == {
    "email": frozenset({Pii}),
    "password_hash": frozenset({Secret}),
}
```

> [!NOTE]
> Prism ships only the `Classification` base, not a fixed `Pii`/`Secret`
> taxonomy — name the classes that fit your compliance regime.

**Next:** [trace where classified data flows](trace-data-flow.md) across your
ref graph for a compliance artifact.
