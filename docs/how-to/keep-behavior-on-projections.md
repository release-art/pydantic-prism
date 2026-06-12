# Keep model behavior on projections

**Goal:** call the methods, `@property`s, `@classmethod`s and `@staticmethod`s
you defined on a canonical `ScopedModel` *on its projections too* — without
hoisting them onto a separate base.

A projection never has the canonical class in its MRO
(`CardStorage → _CardStorageBase → Projection → BaseModel`), so by construction
it cannot *inherit* the canonical's methods. Instead, prism **copies** the
canonical's non-field callables onto every projection automatically:

```python
from typing import Annotated

from pydantic_prism import Scope, ScopedModel, scoped


class Header(Scope): ...
class Storage(Scope): ...


class Card(ScopedModel):
    name: Annotated[str, scoped(Header, Storage)]
    hashes: Annotated[list[str], scoped(Storage)] = []

    @property
    def is_quarantined(self) -> bool:
        return self.name.startswith("!")

    @classmethod
    def of(cls, name: str) -> "Card":
        return cls(name=name)

    def shout(self) -> str:
        return self.name.upper()


storage = Card.scope(Storage)

assert storage(name="!x").is_quarantined is True   # @property survives
assert isinstance(storage.of("hi"), storage)        # @classmethod survives (cls is the projection)
assert storage(name="hi").shout() == "HI"           # plain method survives
```

A `@classmethod` carried this way binds to the *projection*, so `cls(...)`
constructs a projection instance — exactly what a factory wants.

## Opt out with `@unprojected`

Some behavior only makes sense on the canonical — e.g. a method that reads a
field no narrow projection carries. Mark it `@unprojected` to keep it
canonical-only:

```python
from pydantic_prism import unprojected


class Doc(ScopedModel):
    title: Annotated[str, scoped(Header, Storage)]
    hashes: Annotated[list[str], scoped(Storage)] = []

    @unprojected
    def hash_count(self) -> int:
        return len(self.hashes)   # 'hashes' is Storage-only


assert not hasattr(Doc.scope(Header), "hash_count")   # dropped on the Header face
assert Doc(title="t", hashes=["a"]).hash_count() == 1  # still on the canonical
```

`@unprojected` may wrap (or be wrapped by) `@property` / `@classmethod` /
`@staticmethod` in either order.

## What is *not* copied

- **Framework names.** A canonical member named like a `Projection` / `BaseModel`
  attribute (`model_dump`, `scope`, `tool_schema`, …) is never copied — it would
  shadow real machinery. Rename it if you need it on projections.
- **Pydantic-managed members.** `@field_validator` / `@model_validator` /
  `@model_serializer` / `@computed_field` are not plain Python behavior. Field
  validators carry through prism's validator path; `@scoped_validator` controls
  which projections a model validator reaches; and a custom base's pydantic
  behavior (overridden `model_dump`, model validators/serializers, `isinstance`
  identity) is carried with
  [`projection_bases=`](carry-a-custom-base.md), not this mechanism.

> [!WARNING]
> A copied method or property may reference a field the projection dropped and
> raise at call time — that responsibility is the author's. `@unprojected` is the
> escape hatch for members that cannot survive a narrow projection.
