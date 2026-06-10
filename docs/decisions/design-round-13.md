# Design memo — round 13 (auto-generated example READMEs)

Phase 1 output, 2026-06-10. Each `examples/<name>/` should ship an
auto-generated `README.md` with the round-12 diagrams + field docs. This is repo
tooling over the existing `build_readme`, not a library API change.

## Constraint that shaped the wiring

The examples are standalone scripts (not a package), and `bin/test.sh` runs
coverage as `--cov=src` — but the project's `pytest` gate is `--cov-fail-under=100`
over everything imported. If a *pytest* imported the example modules in-process,
their unrun `demo()` / `__main__` lines would drop coverage below 100% and fail
the gate. So the freshness check must not import examples in the pytest process.

## Decisions

- **Generator:** `bin/gen_example_readmes.py` loads each `examples/*/main.py` by
  path (unique synthetic module name), collects its `ScopedModel`s, and renders
  `build_readme(...)` (the same builder as `prism gen --readme`). `--check`
  verifies freshness instead of writing.
- **Freshness gate:** `tests/test_example_readmes.py` runs the generator with
  `--check` as a **subprocess** — example imports happen in the child, so they
  never touch this suite's coverage. A stale README fails CI, mirroring
  `prism check`.
- **Content:** identical to `prism gen` READMEs (scope / projection /
  relationship Mermaid + field/description tables), grouped by source model.
- **Banner:** `build_readme` gained a `regen_hint` parameter so the do-not-edit
  banner names the right command (`python bin/gen_example_readmes.py` for
  examples, `prism gen` for stubs). The relationships section is now gated on the
  diagram actually having edges, so a backref-only model no longer emits a lone
  node.

README-only (examples need no static-typing stubs); files live at
`examples/<name>/README.md`.
