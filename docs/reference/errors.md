# Errors

Misuse of the API itself (wrong argument types, markers in field defaults)
raises plain `TypeError`. The classes below cover **domain** errors — detectable
only once models and scopes are put together. All subclass `PrismError`.

## Hierarchy

```
PrismError(Exception)
├── EmptyProjectionError   (PrismError, ValueError)
├── ProjectionNameError    (PrismError, ValueError)
├── ProjectionBaseError    (PrismError, ValueError)
├── RefResolutionError     (PrismError, ValueError)
└── StaleProjectionStubError (PrismError, RuntimeError)
```

| exception | raised when |
|---|---|
| `PrismError` | Base class for all prism domain errors; catch this to catch them all. |
| `EmptyProjectionError` | `Model.scope(...)` selected zero fields — almost always a typo'd scope or a never-tagged model. The message lists the scopes the model defines. |
| `ProjectionNameError` | Two different scope expressions (or `bases`) would produce one projection class name. Pass `name=` to disambiguate. Also raised *at model definition* when two of a model's scopes share a class-name token (their `cls_name_token`, else `__name__`) — there, rename one or give it a distinct `cls_name_token=`. |
| `ProjectionBaseError` | A field declared on a carried base is tagged with a scope the requested expression does not select — inherited fields can't be removed, so narrowing would leak it. |
| `RefResolutionError` | A `ref` / `backref` couldn't resolve: a string target names no `ScopedModel` in the owning module, a function-local model, a `backref(via=...)` that doesn't line up with a forward `ref`, or a keyed-dict key type that doesn't match the target id type. Raised lazily, on `__refs__` access. |
| `StaleProjectionStubError` | A `prism gen`-generated stub no longer matches its canonical model. Raised at import (app startup). Re-run `prism gen`; `prism check` surfaces the same drift as a CI gate. |

## Situation → error → when

| situation | error | when |
|---|---|---|
| marker used as a field default | `TypeError` | class definition |
| marker nested below the field's top-level `Annotated` | `TypeError` | class definition |
| `ref()` target neither `ScopedModel` nor str | `TypeError` | marker construction |
| `default_scope=` value is not a `Scope` class or expression | `TypeError` | class definition |
| two `ref` / `backref` markers on one field | `TypeError` | class definition |
| `from_projection()` given a partial projection (a delta, not a record) | `TypeError` | `.from_projection()` call |
| `redacted()` called with no visibility scope | `TypeError` | `.redacted()` call |
| projection selects zero fields | `EmptyProjectionError` | `.scope()` call |
| two of a model's scopes share a class-name token | `ProjectionNameError` | class definition |
| one projection name for two different expressions (or bases) | `ProjectionNameError` | `.scope()` call |
| `bases=` / `projection_bases=` entry invalid (not a `BaseModel`, a `ScopedModel`, or not an ancestor) | `TypeError` | `.scope()` call / class definition |
| carried-base field tagged with a scope the expression does not select | `ProjectionBaseError` | `.scope()` call |
| string ref target doesn't resolve (or model is function-local) | `RefResolutionError` | `__refs__` access |
| `backref(via=...)` doesn't match a forward ref | `RefResolutionError` | `__refs__` access |
| keyed-dict `ref()` key type doesn't match the target id type | `RefResolutionError` | `__refs__` access |
| a generated stub no longer matches its model | `StaleProjectionStubError` | import of the generated module (startup) |

Models whose annotations were forward references at definition time are handled:
`.scope()` resolves them (or raises pydantic's clear error), and an explicit
`model_rebuild()` refreshes marker collection too.

## Warnings

Advisory diagnostics — non-fatal — are emitted as warnings under `PrismWarning`
(a `UserWarning` subclass). Filter on `PrismWarning` to silence (or, with
`filterwarnings("error")`, escalate) every prism warning at once, or on a
concrete subclass for one kind.

```
PrismWarning(UserWarning)
├── PrismBaseDropWarning
└── PrismOrderingWarning
```

| warning | emitted when |
|---|---|
| `PrismWarning` | Base class for all prism advisory warnings; filter this to catch them all. |
| `PrismBaseDropWarning` | `Model.scope(...)` would drop a non-`ScopedModel` base's overridden `model_dump`/`model_validate` (or its model validators/serializers) because the base isn't carried. Declare `projection_bases=(Base,)` to carry it, or `projection_bases=()` to silence. One-shot per model. |
| `PrismOrderingWarning` | A `@scoped_validator(mode="before")` coexists with a plain `@model_validator(mode="before")` inherited from a base. pydantic runs the scoped one first (child-first), so a child that depends on the base hook sees untransformed data. Best fix: use `mode="after"` if the value derives from already-parsed fields. Otherwise call `cls.run_inherited_before(data)` at the top of the validator (the inherited hook re-runs, so must be idempotent), or `parent_ordering="acknowledged"` to assert independence. One-shot per `(class, validator)`. See [before-validator ordering](../how-to/carry-a-custom-base.md#before-validator-ordering-with-scoped_validator). |
