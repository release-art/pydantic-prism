# CLI reference

The `pydantic-prism` console script (installed with the package). Everything is also
available as `python -m pydantic_prism <command>`. There are four subcommands:
`gen`, `check`, `diagram`, `flow`.

```console
$ pydantic-prism <command> [options]
```

## `pydantic-prism gen`

Generate the static-typing stub module (and optionally a README) from
`[tool.pydantic-prism]`.

| option | default | meaning |
|---|---|---|
| `--config PATH` | `pyproject.toml` | Path to the config file. |
| `--readme PATH` | config value | Also write a GitHub-rendered model doc at `PATH` (overrides config). |

```console
$ pydantic-prism gen
pydantic-prism: wrote 4 projection stub(s) to myapp/_prism.py
```

See [generate editor stubs](../how-to/generate-editor-stubs.md).

## `pydantic-prism check`

Exit non-zero if the generated stub module (or configured README) is out of
date. A CI gate. Same options as `gen`.

```console
$ pydantic-prism check
pydantic-prism: myapp/_prism.py is up to date        # exit 0; exit 1 if stale
```

## `pydantic-prism diagram`

Render a structure diagram to stdout or a file.

```console
$ pydantic-prism diagram {scope|projection|refs} [module:Name ...] [options]
```

| argument / option | values | default | meaning |
|---|---|---|---|
| `kind` | `scope` / `projection` / `refs` | — | What to draw. |
| `paths` | `module:Name ...` | — | `scope`: optional scope paths (none = all declared). `projection` / `refs`: exactly **one** model path. |
| `--format` | `mermaid` / `dot` / `d2` / `json` | `mermaid` | Output format. |
| `--output FILE` | — | stdout | Write to a file instead of stdout. |
| `--direction` | `TD` / `LR` | `TD` | Layout direction. |

```console
$ pydantic-prism diagram scope
$ pydantic-prism diagram projection myapp.models:User --format dot --output user.dot
$ pydantic-prism diagram refs myapp.models:Order --format json
```

See [export diagrams](../how-to/export-diagrams.md).

## `pydantic-prism flow`

Trace where classified (PII/Secret) data flows from a model across its ref
graph, and emit the compliance artifact.

```console
$ pydantic-prism flow module:Model [options]
```

| argument / option | values | default | meaning |
|---|---|---|---|
| `path` | `module:Model` | — | The entry-point model (exactly one). |
| `--format` | `json` / `mermaid` | `json` | Output format. |
| `--output FILE` | — | stdout | Write to a file instead of stdout. |
| `--direction` | `TD` / `LR` | `TD` | Layout direction (Mermaid only). |

```console
$ pydantic-prism flow myapp.models:Account
$ pydantic-prism flow myapp.models:Account --format mermaid --output flow.mmd
```

See [trace data flow](../how-to/trace-data-flow.md).

## Exit codes

| code | meaning |
|---|---|
| `0` | success / up to date |
| `1` | `check`: a stub or README is stale |
| `2` | a config/resolution error (e.g. a path that doesn't name the expected kind) |

## `[tool.pydantic-prism]` config

```toml
[tool.pydantic-prism]
output = "myapp/_prism.py"          # required: where pydantic-prism gen writes the stub module
modules = ["myapp.models"]          # scan these for ScopedModels (one stub per scope)
readme = "myapp/MODELS.md"          # optional: also emit a GitHub model doc

[[tool.pydantic-prism.projections]] # optional: projections beyond per-atom
model = "myapp.models:Document"
scopes = ["myapp.models:Public", "myapp.models:Internal"]  # union
name = "DocumentPublicView"         # optional name override
```

| key | required | meaning |
|---|---|---|
| `output` | yes | Path the stub module is written to. |
| `modules` | one of `modules` / `projections` | Modules to scan; each scope yields one per-atom projection stub. |
| `projections` | one of `modules` / `projections` | Extra projections (unions, name overrides) beyond per-atom. |
| `readme` | no | Path for the generated GitHub model doc. |

A config that selects nothing (neither `modules` nor `projections`) is an error.
The table is parsed with pydantic, so a malformed or misspelled key (e.g. a
non-string `output`, an unknown key, or a projection missing `scopes`) fails
with a native `pydantic.ValidationError` naming the offending field.
