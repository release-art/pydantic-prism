# Projections, not inheritance

A projection is a real, separate `BaseModel` subclass built by **filtering**
the canonical's fields — not a child class of the canonical model. This page
explains why, and what it buys over the two things people reach for instead.

## Why filtering, not subclassing

The obvious-looking design is to make `UserPublic` inherit from `User`. It
doesn't work, for a structural reason: **pydantic subclasses cannot remove
required fields.** Inheritance can only add fields or widen them. A projection's
entire job is the opposite — to *narrow* — so inheritance is the wrong tool at
the most basic level.

So a prism projection does not subclass the canonical. It subclasses a shared
`Projection(BaseModel)` base and receives only the fields its scope selects,
rebuilt with their annotations, constraints, and validators intact. (The one
bounded exception is [`projection_bases=`](../how-to/carry-a-custom-base.md):
you may carry a custom *non-`ScopedModel`* base for behavior and `isinstance`
identity — but fields declared on that base are inherited and cannot be removed,
which is exactly why carrying bases is opt-in.)

## What it solves over hand-written `UserIn` / `UserOut`

The status quo is the "DTO zoo": for one entity you hand-write `Create`,
`Update`, `Public`, and storage classes. SQLModel's "one model" promise
officially concedes this — its own docs admit you end up writing the parallel
classes anyway. Those classes are the problem prism removes. They drift from the
canonical, they re-declare every field by hand, they lose constraints in the
copy, and — the part nothing else addresses — they have no idea your models
reference each other. Prism keeps **one source of truth** and derives every
face from it, [references included](what-ref-models.md). The pitch is literally
"stop hand-writing the DTO zoo".

## What it solves over raw `create_model`

You *could* build narrowed models with `create_model` yourself; people do, often
reaching into `pydantic._internal` to make it work. What you'd be reinventing is
the disciplined layer on top:

- **Identity and caching.** `User.scope(Public) is User.scope(Public)`. The same
  expression always returns the same class object, which is what keeps FastAPI
  response models and OpenAPI component `$ref`s stable.
- **Deterministic names.** `UserPublic`, `UserInternalOrPublic` — derived from
  the expression, not `UserBackendDtoFrontendLlmSlice` accidents.
- **Scope propagation into nested models.** A public projection that embedded an
  *unprojected* nested model would leak that model's fields and defeat the whole
  point; prism propagates the scope through `Optional`, unions, and containers.
- **Validator carry and ref-graph survival**, neither of which `create_model`
  gives you for free.

Prism is the cached, propagating, name-stable discipline over `create_model`
that the community kept rebuilding by hand — built on the public pydantic API
only.

> One related limitation, stated honestly: a *dynamically derived* model is
> opaque to static type checkers — this is pydantic core's own stated reason for
> declining to ship view-derivation. Prism's answer is to *generate* readable
> declarations; see [generate editor stubs](../how-to/generate-editor-stubs.md).
