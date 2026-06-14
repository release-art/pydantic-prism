# Change a field's type per projection

**Goal:** give the *same* field a different **type** in different projections —
the one thing [`override=Field(...)`](vary-schema-per-scope.md) cannot do — and
keep round-trips working across the change.

A canonical model stores a `datetime`; the face you hand an LLM wants an ISO
**string**. `as_type=` swaps the annotation per scope, and `convert=Converter(...)`
bridges the values so `from_canonical` / `from_projection` stay total:

```python
from datetime import datetime
from typing import Annotated

from pydantic import Field

from pydantic_prism import Converter, Scope, ScopedModel, scoped


class Storage(Scope): ...
class Llm(Scope): ...


class Event(ScopedModel):
    name: Annotated[str, scoped(Storage, Llm)]
    created: Annotated[
        datetime,
        scoped(Storage),                       # canonical: a datetime
        scoped(
            Llm,
            as_type=str,                       # the Llm face sees a string…
            convert=Converter(                 # …and these bridge the two
                encode=datetime.isoformat,     # canonical → Llm
                decode=datetime.fromisoformat,  # Llm → canonical
            ),
            override=Field(description="ISO-8601 timestamp"),  # composes
        ),
    ]


# The annotation — and the JSON schema — really differ:
assert Event.scope(Storage).model_fields["created"].annotation is datetime
assert Event.scope(Llm).model_fields["created"].annotation is str
assert Event.scope(Llm).model_json_schema()["properties"]["created"]["type"] == "string"

# Round-trip stays total: encode on the way out, decode on the way back.
event = Event(name="launch", created=datetime(2026, 6, 12, 10, 30))
llm = Event.scope(Llm).from_canonical(event)
assert llm.created == "2026-06-12T10:30:00"          # encoded
assert Event.from_projection(llm).created == event.created  # decoded
```

## Converters are optional

Drop `convert=` (or supply only one direction) when pydantic's own coercion
already bridges the types — e.g. a narrowing `Literal[...] → str`, a nullability
change, or an ISO string that pydantic parses back to a `datetime` on its own. A
direction you omit simply falls back to native validation.

> [!WARNING]
> A retyped projection holds a value of a *different type* than the canonical, so
> without a matching converter a round-trip can raise. With `encode` but no
> `decode` (or vice-versa) only one direction is guaranteed total. The retyped
> field's schema is the override's — the canonical is no longer even
> type-compatible with that face.

## It nests, and it reshapes relationships

Converters apply at every level: a type override on a **nested** model's field is
encoded and decoded through the nesting automatically.

`as_type=` also works on relationship fields. When you reshape a `ref()`/`backref()`
or an embedded-model field, prism **re-derives that field's edge per projection**
— a scalar ref retyped to `list[...]` becomes a collection edge; an embedded
model retyped to a scalar drops the edge:

```python
from uuid import UUID

from pydantic_prism import ref


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Storage, Llm)]


class Order(ScopedModel):
    cust: Annotated[
        UUID,
        ref(Customer),
        scoped(Storage),                    # canonical: one customer id (scalar)
        scoped(Llm, as_type=list[UUID]),    # the Llm face batches several
    ]


assert Order.scope(Storage).__prism__.refs["cust"].shape.value == "scalar"
assert Order.scope(Llm).__prism__.refs["cust"].shape.value == "collection"  # re-derived
assert Order.scope(Llm).__prism__.refs["cust"].target is Customer           # still a ref
```

A `scoped()` carrying `as_type=` / `convert=` (like `override=`) must name exactly
one scope; split membership across markers to attach a per-scope type.
