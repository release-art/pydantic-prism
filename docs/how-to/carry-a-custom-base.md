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

### Preferred fix — derive in `mode="after"`

The trap is a property of the **before**-phase. If the validator computes a value
from *already-parsed* fields, write it as `mode="after"` and read `self`: by then
the base before-hook has already run during core validation, so there is **no
ordering race, no double-run, and no warning**. Give the derived field a default
so the record passes core validation, then fill it in:

```python
class WebsiteRow(DecodingBase, ScopedModel, projection_bases=(DecodingBase,),
                 default_scope=Storage):
    webpages: Annotated[list[str], scoped(Public)] = []
    first: Annotated[str, scoped(Storage)] = ""

    @scoped_validator(Storage, mode="after")
    def derive_first(self):
        if self.webpages and not self.first:   # webpages is already a list[str]
            self.first = self.webpages[0]
        return self


row = WebsiteRow(webpages=json.dumps(["http://a.com"]))
assert row.first == "http://a.com"
assert WebsiteRow.scope(Storage).model_validate(  # survives onto projections
    {"webpages": json.dumps(["http://p.com"])}
).first == "http://p.com"
```

Reach for the before-phase only when you genuinely need *pre-validation* data —
e.g. the derived field is **required** (so the record can't pass core validation
until you fill it) or you must choose among raw input keys before type coercion.

### Before-phase fix — `parent_ordering="after_parent"`

When you do need `mode="before"`, declare `parent_ordering="after_parent"`: prism
wraps the validator to run the inherited before-hooks *first*, so its body sees
transformed data — no manual call, no warning:

```python
class WebsiteRowReq(DecodingBase, ScopedModel, projection_bases=(DecodingBase,),
                    default_scope=Storage):
    webpages: Annotated[list[str], scoped(Public)] = []
    first: Annotated[str, scoped(Storage)]   # required — must be filled pre-validation

    @scoped_validator(Storage, mode="before", parent_ordering="after_parent")
    @classmethod
    def derive_first(cls, data):
        if data.get("webpages") and not data.get("first"):
            data = {**data, "first": data["webpages"][0]}  # webpages already decoded
        return data


assert WebsiteRowReq(webpages=json.dumps(["http://a.com"])).first == "http://a.com"
```

The lower-level [`run_inherited_before`](../reference/api.md) helper does the same
by hand — `data = cls.run_inherited_before(data)` at the top of the validator —
for when you want to interleave it with other logic. It is the friendly
replacement for the `Base.decode.__func__(cls, data)` descriptor dance.

> [!IMPORTANT]
> Both before-phase fixes re-run the inherited hook afterwards under pydantic's
> own pipeline, so it must be **idempotent** — guard it on the input shape
> (`if isinstance(v, str): ...`), which decode hooks already do. A hook that
> transforms unconditionally would run twice. `mode="after"` has no such caveat.

**If the validator does *not* depend on the inherited hook**, assert that and
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
