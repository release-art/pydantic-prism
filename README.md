# pydantic-prism

![Tests](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/tests.svg)
![Coverage](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/coverage.svg)
![Skipped](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/skipped.svg)
![XFailed](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/xfailed.svg)
![Warnings](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/warnings.svg)
![Duration](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/duration.svg)
![Last run](https://raw.githubusercontent.com/release-art/pydantic-prism/main/badges/last-run.svg)

Project one canonical pydantic model along any axis — and keep the
relationship graph that survives the projection.

Tag a single model's fields with named **scopes**; derive real
`pydantic.BaseModel` subclasses per scope (API response, storage row, LLM
tool input, audit log) with working validation, serialization, and JSON
schema. Declare FK-style **references** in the same metadata and introspect
them through `__refs__` — the graph survives every projection. The
projection half has prior art; [combining it with an introspectable
relationship graph](docs/explanation/vs-prior-art.md) does not.

## 30 seconds

```python
from typing import Annotated
from uuid import UUID

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...
class Internal(Public): ...   # Internal sees everything Public sees
class Storage(Internal): ...  # Storage sees everything Internal sees


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    password_hash: Annotated[str, scoped(Storage)]
    display_name: Annotated[str, scoped(Public)]


UserPublic = User.scope(Public)      # fields: id, display_name
UserInternal = User.scope(Internal)  # fields: id, email, display_name
UserStorage = User.scope(Storage)    # all four fields
```

`UserPublic` is a real, cached `BaseModel` subclass named `"UserPublic"` —
`User.scope(Public) is User.scope(Public)`, so FastAPI response models and
OpenAPI component schemas stay stable.

Scopes are classes; inheritance forms the scope graph, so the membership
rule is one line: a field tagged `T` is in projection `S` iff
`issubclass(S, T)`. Untagged fields belong to no scope and can never leak
into a projection. Scopes compose with set operators (`| & - ~`), both in
field tags and at the call site.

## Why not hand-write `UserIn` / `UserOut`?

Parallel classes drift from the canonical, lose constraints, and have no
idea your models reference each other. Prism derives every face from one
source of truth and keeps the references coherent across all of them.
See [projections, not inheritance](docs/explanation/projections-not-inheritance.md).

## Install

```sh
pip install pydantic-prism        # pydantic >= 2.12, Python >= 3.12
```

## Documentation

The docs follow the [Diátaxis](https://diataxis.fr) framework — start where
your need fits:

- **[Documentation home](docs/README.md)** — the full table of contents.
- **[Tutorial: your first scoped model](docs/tutorial/first-scoped-model.md)** —
  one hand-held lesson, one model to two projections.
- **[How-to guides](docs/how-to/README.md)** — short recipes: redact PII,
  trace data flow, PATCH models, FastAPI, ORM bridge, editor stubs, diagrams.
- **[Reference](docs/reference/README.md)** — the [API](docs/reference/api.md),
  the [`prism` CLI](docs/reference/cli.md), and the [error table](docs/reference/errors.md).
- **[Explanation](docs/explanation/README.md)** — the scope algebra, why
  projections aren't inheritance, what `ref()` does and does not model.

[**ROADMAP.md**](ROADMAP.md) lists what is shipped, planned, and deliberately
out of scope.

## Develop

```sh
pdm install -G dev
bin/test.sh                       # pytest with coverage (100% gate)
bin/autoformat.sh                 # ruff format + ruff check --fix
pdm run pyright                   # strict, src/
```

MIT licensed. Built on the public pydantic API only — no `pydantic._internal`.
