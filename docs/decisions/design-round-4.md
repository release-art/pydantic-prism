# Design memo — round 4 (static-type visibility for projections)

Phase 1 output, 2026-06-10. The single biggest adoption blocker: in a
pyright/Pylance-strict codebase, `Screenshot.scope(Ref)` is `type[Projection]`
with opaque fields. Hand-written `ScreenshotRef` types; prism's dynamic
projection does not. Today this makes prism a runtime-correctness win and a
static-correctness loss.

## The hard constraint (decides the whole shape)

Field-to-scope membership lives in `Annotated` metadata; `.scope()` runs the
scope algebra (`issubclass`, `| & - ~`) at *runtime* to choose survivors. **No
static type checker evaluates that.** And "universal" rules out a plugin:
VSCode hints come from Pylance = the pyright engine, which has **no
third-party plugin API** by design; a mypy plugin helps `mypy` on the CLI but
never appears in a VSCode hover. The only channel every tool reads with zero
configuration is ordinary type declarations the analyzer already understands —
**concrete classes in a real `.py` file**. So the design question is not
"which plugin" but *where the checker-visible declaration comes from and how it
stays honest.* Decision (round-4 direction, already taken): **generate real
classes with a CLI; verify they haven't drifted at startup.**

---

## Q1. Generated-class realness — shim vs fully materialized

The deep fork. A generated `ScreenshotRef` must (a) show fields to the checker
and (b) behave correctly at runtime — validators, `__refs__`, carried bases,
partial `None`-defaults, nested-model scope propagation. Materializing *(b)* as
generated source is a large, fragile surface (field validators emitted as code,
MRO reconstruction, etc.) and would duplicate `_project`.

**Recommend: typed shim over the genuine runtime projection.** Generate, per
projection:

```python
if TYPE_CHECKING:
    class ScreenshotRef(Projection):   # what pyright/Pylance/mypy read
        id: UUID
        timestamp: datetime
else:
    ScreenshotRef = Screenshot.scope(Ref)   # the genuine, cached projection
```

The checker reads a real class with real fields; the runtime object is the
authentic `.scope()` result, so *every* behavior (validators, refs, bases,
partial, FastAPI `response_model=ScreenshotRef`) is correct for free and
`ScreenshotRef is Screenshot.scope(Ref)` holds — the auto-name
(`f"{Model.__name__}{expr.token()}"`) already *is* `ScreenshotRef`, so no
`name=` is needed and the cache identity lines up. The shim is the typing
surface; `_project` stays the single source of runtime truth. Fully-materialized
classes are the alternative if someone needs the projection to exist without
importing/constructing the canonical model graph, but nothing in the motivating
case needs that, and the maintenance cost is steep. Note the residual: at the
`Screenshot.scope(Ref)` *call site* the checker still sees `type[Projection]` —
you get types by referencing `ScreenshotRef`, which is exact parity with the
hand-written class this replaces, minus the hand-writing. (Optional later
add-on: generate `.pyi` `@overload`s for `.scope()` to type the call site too.)

## Q2. Drift check — mechanism and timing

A generated shim that silently lies after a model changes is worse than no
shim. The user's choice: **check at startup.**

**Recommend: a per-projection signature, recomputed and compared when the
generated module is imported; mismatch raises.** The generator stamps each
projection with a signature derived from the live inputs that determine its
shape — ordered `(field_name, annotation_repr, optional)` of the computed
projection, plus the source model's field-scope map and `default_scope`. At
import, prism recomputes the signature from the current models and compares; a
mismatch raises a new `StaleProjectionStubError` naming the model and the
command to re-run. Comparing a hash/signature (not field-by-field) is robust to
the algebra and to nested/partial/base interactions, because it is taken from
the *output* of `_project`, not re-derived. Timing = import of the generated
module (i.e., app startup), which is when `else: ScreenshotRef =
Screenshot.scope(Ref)` runs anyway. A `prism check` subcommand runs the same
comparison as a non-importing CI gate (exit non-zero on drift).

## Q3. CLI surface

**Recommend a `prism` console script** (entry point in `pyproject.toml`),
with `python -m pydantic_prism` as the equivalent module form:

- `prism gen` — (re)generate the stub module.
- `prism check` — verify no drift, exit non-zero otherwise (CI).

Both read configuration from `[tool.pydantic-prism]` in `pyproject.toml`
(target import paths + output file + projection spec; see Q4/Q5). A console
script is the idiom users expect (`alembic`, `ruff`); `-m` keeps it usable
without the script on PATH.

## Q4. Which projections get generated (discovery)

Auto-discovering `.scope(...)` *call sites* needs static analysis of arbitrary
expressions — out. The options are config-driven.

**Recommend: for each listed model, generate one projection per scope in
`Model.scopes()` by default, with an explicit opt-in list for everything else.**
`Model.scopes()` already returns the atom scopes a model actually uses, so the
common case (`Ref`, `Public`, `Storage`) needs zero enumeration — list the
module, get its natural projections. Non-atom expressions (`~Llm`, `A - B`),
`name=`/`bases=`/partial variants, and cross-cutting needs go in an explicit
`projections = [...]` list. Generating-all-atoms can emit an unused class or
two (harmless; they are shims). The alternative — a fully explicit list of every
(model, scope) pair — is more truthful but reintroduces the per-projection
bookkeeping prism exists to remove.

## Q5. Output location, naming, nested refs

- **Location:** a single generated module at a configured path (default
  `<package>/_prism_generated.py`), one file, header banner
  `# generated by prism gen — do not edit`.
- **Names:** the runtime auto-name, `f"{Model.__name__}{expr.token()}"`
  (`ScreenshotRef`, `UserInternalOrPublic`), so the shim name and the cached
  runtime class name coincide; a config `name=` override flows to both the
  generated class and the `else` `.scope(..., name=...)` binding.
- **Nested projections:** a field typed as a nested `ScopedModel` projects to
  `Address.scope(Public)` at runtime; the shim must reference the *generated*
  `AddressPublic`, so generation resolves nested fields to sibling generated
  names (and orders/forward-refs them within the one module). This is the
  fiddliest part of the generator and the main place tests must bite.
- **Partial scopes:** surviving fields render as `T | None` with `= None`,
  matching the runtime partial projection.
- **Carried bases:** under `TYPE_CHECKING` the shim subclasses the carried base
  too (`class RowPublic(AzureTableBase, Projection)`), so `isinstance` helpers
  and base methods type-check.

---

## Scope / sequencing

This is materially larger than rounds 2–3. Proposed slices, shippable in order:

1. **Core generator + shim emission + identity** for flat models (scalars,
   `Optional`, `list`/`dict`) — delivers the motivating case.
2. **Drift check** (`StaleProjectionStubError`, startup + `prism check`).
3. **Nested projections, partial, carried bases** in generated output.
4. Docs, examples, CHANGELOG.

Open for phase 2: the Q1 fork (shim vs materialized) above all; then Q4
discovery default; then whether `prism check` ships in slice 1 or 2.

## Risks / things I'm least sure of

- **Config vs zero-config discovery.** Auto-all-atoms may surprise; an explicit
  list is noisier but unambiguous. Leaning auto + opt-in; want a ruling.
- **Nested-ref name resolution** across the generated module (ordering,
  cycles via forward refs) is where generation bugs will hide.
- **The call-site residual.** If typing `Screenshot.scope(Ref)` *itself*
  (not just `ScreenshotRef`) turns out to be a hard requirement, we need the
  `.pyi` `@overload` add-on, which is a second generated artifact to keep in
  sync. Deferring unless demanded.
