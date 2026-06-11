# Carry a custom pydantic base onto projections

**Goal:** keep a custom base class's behavior — overridden `model_dump`, model
validators, helper methods, `isinstance` identity — on the derived projections.

By default a projection is built on a fresh `Projection` base and does **not**
inherit your canonical's custom base. Declare `projection_bases=` to carry it.

```python
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...
class Storage(Public): ...


class TableRowBase(BaseModel):
    def table_name(self) -> str:
        return type(self).__name__.lower()


class Row(TableRowBase, ScopedModel, projection_bases=(TableRowBase,)):
    id: Annotated[UUID, scoped(Public)]
    api_key: Annotated[str, scoped(Storage)]


RowPublic = Row.scope(Public)
row = RowPublic(id=uuid4())

assert isinstance(row, TableRowBase)          # identity preserved
assert row.table_name() == "rowpublic"        # base method works
assert "api_key" not in RowPublic.model_fields  # Storage-only field still dropped
```

`projection_bases=` sets the default for every `.scope()` call and is inherited
by subclasses. Override per call with `bases=`, or opt out with `bases=()`:

```python
RowFlat = Row.scope(Public, bases=(), name="RowFlat")
assert not issubclass(RowFlat, TableRowBase)  # plain projection, no base behavior
```

> [!WARNING]
> **Fields declared on a carried base are inherited by every projection** —
> pydantic cannot remove inherited fields. Treat them as infrastructure fields.
> If a base-declared field is tagged with a scope the expression doesn't
> select, `.scope()` raises
> [`ProjectionBaseError`](../reference/errors.md) rather than leak it.

Calling `.scope()` on a model whose base overrides `model_dump`/`model_validate`
*without* a declaration warns once; declare `projection_bases=()` to silence it.
Runnable: [`examples/custom_base`](../../examples/custom_base).

## Before-validator ordering with `@scoped_validator`

**The rule:** pydantic v2 runs `mode="before"` model validators **child-first,
then up the MRO**. So a `@scoped_validator(mode="before")` on your model runs
*before* a plain `@model_validator(mode="before")` it inherits from a base.

**The failure mode.** A common base hook *transforms raw input* — e.g.
JSON-decodes stringified columns coming out of storage. If a child
`@scoped_validator(mode="before")` *depends* on that transformation, it runs
first and sees the **undecoded** value — iterating the still-encoded string
`'["..."]'` character-by-character:

```python
import json
from pydantic import model_validator
from pydantic_prism import scoped_validator


class DecodingBase(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def decode(cls, data):
        if isinstance(data.get("webpages"), str):
            data = {**data, "webpages": json.loads(data["webpages"])}  # str -> list
        return data


class WebsiteRowBad(DecodingBase, ScopedModel, projection_bases=(DecodingBase,),
                    default_scope=Storage):
    webpages: Annotated[list[str], scoped(Public)] = []
    first: Annotated[str, scoped(Storage)] = ""

    @scoped_validator(Storage, mode="before")  # ⚠️ runs BEFORE decode
    @classmethod
    def derive_first(cls, data):
        if data.get("webpages") and not data.get("first"):
            data = {**data, "first": data["webpages"][0]}  # webpages[0] == '['
        return data


bad = WebsiteRowBad(webpages=json.dumps(["http://a.com"]))
assert bad.first == "["          # saw the raw JSON string's first character
assert bad.webpages == ["http://a.com"]  # the base hook decoded it — too late
```

Tests that pass native lists never hit it; real encoded data breaks at runtime.
prism warns about this shape at class definition
([`PrismOrderingWarning`](../reference/errors.md)).

**The fix — run the inherited hook explicitly.** Call
[`run_inherited_before`](../reference/api.md) at the top of the child validator
to apply the inherited `before`-hooks *first*, then operate on the transformed
data:

```python
class WebsiteRow(DecodingBase, ScopedModel, projection_bases=(DecodingBase,),
                 default_scope=Storage):
    webpages: Annotated[list[str], scoped(Public)] = []
    first: Annotated[str, scoped(Storage)] = ""

    @scoped_validator(Storage, mode="before")
    @classmethod
    def derive_first(cls, data):
        data = cls.run_inherited_before(data)  # decode now; webpages is a list
        if data.get("webpages") and not data.get("first"):
            data = {**data, "first": data["webpages"][0]}
        return data


row = WebsiteRow(webpages=json.dumps(["http://a.com"]))
assert row.first == "http://a.com"
assert WebsiteRow.scope(Storage).model_validate(  # survives onto projections
    {"webpages": json.dumps(["http://p.com"])}
).first == "http://p.com"
```

`run_inherited_before` runs every inherited `before`-validator (nearest ancestor
first, parent-most last) and is the friendly replacement for the
`Base.decode.__func__(cls, data)` descriptor dance. It also keeps working once
the validator is carried onto a projection.

> [!IMPORTANT]
> The inherited hook still runs again afterwards under pydantic's own pipeline,
> so it must be **idempotent** — guard it on the input shape
> (`if isinstance(v, str): ...`), which decode hooks already do. A hook that
> transforms unconditionally would run twice.

**If the child does *not* depend on the inherited hook**, assert that and
silence the warning with `parent_ordering="acknowledged"`:

```python
class WebsiteRowOk(DecodingBase, ScopedModel, projection_bases=(DecodingBase,),
                   default_scope=Storage):
    webpages: Annotated[list[str], scoped(Public)] = []

    @scoped_validator(Storage, mode="before", parent_ordering="acknowledged")
    @classmethod
    def passthrough(cls, data):
        return data  # independent of decode — no warning
```
