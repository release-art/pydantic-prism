# Generate editor stubs

**Goal:** make `Model.scope(...)` projections visible to your editor and type
checker. To pyright/Pylance/mypy, `User.scope(Public)` is just `type[Projection]`
— the scope algebra runs at runtime, so the projection's fields are invisible.
Pyright has no plugin API, so the universal fix is generated declarations.

## 1. Configure

Add a `[tool.pydantic-prism]` block to `pyproject.toml`:

```toml
[tool.pydantic-prism]
output = "myapp/_prism.py"          # where to write the stub module
modules = ["myapp.models"]          # scan these for ScopedModels (one stub per scope)

[[tool.pydantic-prism.projections]] # optional: projections beyond per-atom
model = "myapp.models:Document"
scopes = ["myapp.models:Public", "myapp.models:Internal"]  # union
name = "DocumentPublicView"         # optional name override
```

## 2. Generate

```console
$ prism gen
prism: wrote 4 projection stub(s) to myapp/_prism.py
```

Import the generated names where you want static types:

```python
from myapp._prism import ScreenshotRef   # generated, fully typed

def handler(shot: ScreenshotRef) -> None:
    shot.timestamp     # datetime — autocompletes, type-checks
    shot.nonexistent   # pyright/mypy error
```

Each stub is a `TYPE_CHECKING` class (the typing surface) aliased to the genuine
cached `.scope()` result at runtime — so `ScreenshotRef is Screenshot.scope(Ref)`,
and validators, refs, carried bases, partial defaults, and FastAPI
`response_model=` all keep working. The file carries a do-not-edit banner;
regenerate it, don't hand-edit.

## 3. Gate drift in CI

```console
$ prism check        # exit 1 if the stub is out of date
```

Each stub records a signature; at import (app startup) it is re-checked and
raises [`StaleProjectionStubError`](../reference/errors.md) if the model changed
without a regenerate. Wire `prism check` into CI so a stale stub fails the build.

Both commands are also available as `python -m pydantic_prism gen|check`. To
also emit a GitHub-rendered model doc beside the stub, see
[export diagrams → shipping with generated models](export-diagrams.md#ship-a-model-doc).
See the full [CLI reference](../reference/cli.md).
