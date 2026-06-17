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

The `model` / `scopes` / `modules` paths are imported with `importlib`, so the
target package has to be importable from the project root. A plain (flat) layout
works as-is. For the common **`src/` layout** prism adds `<root>/src` to the
import path automatically when that directory exists — no install required, so
`pydantic-prism check` runs on a fresh CI checkout or under `pipx`/`uvx`/
`pre-commit`. For any other layout, list the import roots explicitly (resolved
relative to the `pyproject.toml` directory):

```toml
[tool.pydantic-prism]
sys-path = ["src", "generated"]     # extra roots prepended before import
```

## 2. Generate

```console
$ pydantic-prism gen
pydantic-prism: wrote 4 projection stub(s) to myapp/_prism.py
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

The stubs also mirror the **scope lattice**: when one face's fields are a subset
of another's (e.g. a `Public` projection's fields ⊆ an `Internal` one's), the
richer stub *subclasses* the leaner one, so a value of the richer face is
assignable where the leaner is expected — matching how a hand-written
inheritance chain behaved. This is a TYPE_CHECKING-only relation: at runtime the
projections stay independent cached classes (so `isinstance` across faces is
`False` — assignability is structural, not nominal). Any **behavior** prism
copies onto a projection — a `@property`, `@classmethod`, `@staticmethod`, or
method on the canonical (anything not `@unprojected`) — is emitted into the stub
too, so the editor sees it.

> **Note — `ruff format`.** The generated file's `# ruff: noqa` banner disables
> *linting*, not *formatting*; `ruff format` may rewrite it (quotes, wrapping)
> and then `pydantic-prism check` reports it stale. Exclude the generated module
> from the formatter — e.g. `[tool.ruff] extend-exclude = ["myapp/_prism.py"]`.

## 3. Gate drift in CI

```console
$ pydantic-prism check        # exit 1 if the stub is out of date
```

`pydantic-prism check` regenerates the module in memory and byte-diffs it against the file
on disk, so any model change that the stub doesn't reflect fails the check. Wire
it into CI so a stale stub fails the build. (There is no runtime check: the
`.scope()` alias is recomputed live every import, so it is never itself stale —
only the static stub the type checker reads can drift, and that is exactly what
`pydantic-prism check` catches.)

Both commands are also available as `python -m pydantic_prism gen|check`. To
also emit a GitHub-rendered model doc beside the stub, see
[export diagrams → shipping with generated models](export-diagrams.md#ship-a-model-doc).
See the full [CLI reference](../reference/cli.md).
