# API reference

Everything `pydantic_prism` exports, with exact spellings. Every name in the
import block below is in `pydantic_prism.__all__`. (`Node` / `NodeField` are the
element types a `Diagram` holds — you reach them through `diagram.nodes`, not a
top-level import.)

```python
from pydantic_prism import (
    MISSING, Scope, ScopeExpr, Classification, Direction, In, Out,
    ScopedModel, Projection,
    scoped, scoped_validator, ref, backref, Ref, BackRef, Scoped, RefShape,
    RefGraph, RefInfo, IdRefInfo, BackRefInfo, EmbeddedRefInfo,
    FlowReport, FlowNode, FlowEdge, FlowField, build_flow_report,
    Diagram, scope_diagram, projection_diagram,
    PrismError, EmptyProjectionError, ProjectionNameError,
    ProjectionBaseError, RefResolutionError, StaleProjectionStubError,
)
```

## Markers and functions

| name | kind | summary |
|---|---|---|
| `scoped(*scopes, description=, examples=, json_schema_extra=)` | marker fn | Tags a field with scopes / a scope expression (varargs union). Optional schema kwargs attach per-scope field schema (one scope per schema-bearing marker). |
| `scoped_validator(*scopes, mode=...)` | decorator | A `@model_validator` that **also** carries onto projections whose expression selects `scopes`. `mode` is required (`"before" \| "after" \| "wrap"`). |
| `ref(target, *, field="id")` | marker fn | Forward FK-style reference. `target`: `ScopedModel` subclass or string name. Keyed-dict shape inferred from a `dict[...]` annotation. |
| `backref(target, *, via, field="id")` | marker fn | Declared reverse reference; `via` names the forward-`ref` field on `target`. |
| `Ref` / `BackRef` / `Scoped` | marker types | The frozen-dataclass instances produced by `ref()` / `backref()` / `scoped()`; you rarely name these directly. |
| `RefShape` | StrEnum | `SCALAR`, `COLLECTION`, `KEYED_DICT` — also comparable to their lowercase strings. |
| `MISSING` | sentinel | pydantic 2.12's missing-sentinel, re-exported. A partial-scope field reads as `MISSING` when absent (`field is MISSING`). |

All prism metadata lives inside `Annotated[...]`; marker order within one
`Annotated` is insignificant. Using a marker as a field *default*, or nesting it
below the top-level `Annotated`, raises `TypeError` at class definition.

## Scopes

| name | kind | summary |
|---|---|---|
| `Scope` | class | Subclass to declare a scope; subclass a scope to **broaden** it. The root is the wildcard. Never instantiated. Class keywords: `partial=True`; `description=` / `examples=` / `json_schema_extra=` (model-level schema for projections that select it); `cls_name_token=` (the CamelCase fragment this scope contributes to a derived class's auto-name, defaulting to its `__name__`). All *not* inherited. |
| `Classification` | class | Subclass of `Scope` for data-classification tags — an axis orthogonal to visibility. Composes in the same algebra; the distinct base is what lets prism enumerate, redact, and trace classified data. |
| `Direction` / `In` / `Out` | classes | The read/write **direction** axis — a closed binary prism ships whole (both `In`/`Out`). Tag a read-only field `scoped(..., Out)`, a write-only field `scoped(..., In)`; drive `Model.input()` / `Model.output()`. See [prevent mass-assignment](../how-to/prevent-mass-assignment.md). |
| `ScopeExpr` | class | A scope expression, built from scopes with `\| & - ~`. Methods: `.matches(scope)`, `.selects(tag)`, `.atoms()`, `.is_partial()`; varargs `.union(*s)` / `.intersection(*s)` / `.difference(*s)` (named forms of `\| & -`). |

Operators (usable in `scoped(...)` tags and in `Model.scope(...)`):

| operator | meaning |
|---|---|
| `A \| B` | union — in either |
| `A & B` | intersection — in both |
| `A - B` | difference — in A and not in B |
| `~A` | complement — not in A |

For *programmatic* composition over a runtime list, the operators also have
named varargs forms on both scope classes and expressions —
`A.union(B, C)`, `base.difference(*to_strip)`, `reduce(ScopeExpr.union, scopes)`.
Prefer the operators for statically-known scopes.

`A - B` and `~A` propagate through scope inheritance: a field tagged
`scoped(Scope - Llm)` is excluded from `Llm` and every scope that extends it.

## `ScopedModel` — canonical models

| name | kind | summary |
|---|---|---|
| `Model.scope(scope, *, name=None, bases=None)` | classmethod | Derive/fetch the cached projection class for one scope or expression (compose with `\| & - ~`). `name` and `bases` join the cache key. |
| `Model.input(visible=None, *, name=None, bases=None, extra="forbid")` | classmethod | Write-side projection: `visible - Out` (drops read-only fields, deep). Defaults `name="{Model}In"` and `extra="forbid"`. `visible` is one scope/expression, falling back to `default_scope=` when omitted. |
| `Model.output(visible=None, *, name=None, bases=None)` | classmethod | Read-side projection: `visible - In` (drops write-only fields, deep). Defaults `name="{Model}Out"`; config untouched. `visible` is one scope/expression, falling back to `default_scope=`. |
| `Model.scopes()` | classmethod | `frozenset[type[Scope]]` of the atom scopes used in field tags. |
| `Model.from_projection(projection, /, **extra)` | classmethod | Complete projection → canonical instance; missing fields via `**extra` or canonical defaults. Rejects **partial** projections (use `with_updates`). |
| `instance.with_updates(patch, /)` | method | Apply a (partial) projection's set fields as a PATCH; returns a new, re-validated instance. `self` unchanged. |
| `Model.__refs__` | ClassVar | The model's `RefGraph`. |
| `Model.__field_scopes__` | ClassVar | `dict[str, ScopeExpr]`: each field's **resolved** scope (class default folded in for untagged fields). |
| `Model.__prism_default_scope__` | ClassVar | `ScopeExpr \| None`: the class-level `default_scope=` (inherited down the MRO), or `None`. |
| `Model.__prism_validator_scopes__` | ClassVar | `dict[str, ScopeExpr]`: each `@scoped_validator`'s name → the expression deciding which projections carry it. |

Class keywords: `projection_bases=(...)`, `default_scope=` (the scope untagged
fields fall back to), `projection_name_template=` (`{model}` / `{scope}`
placeholders; the result must be a valid identifier).

### Round-trips

| you have | you want | use | missing fields come from |
|---|---|---|---|
| a **full** projection | a fresh canonical | `Model.from_projection(projection, **extra)` | `**extra` / canonical defaults |
| a **partial** patch + a baseline | the updated canonical | `baseline.with_updates(patch)` | the **baseline** instance |
| a canonical | a projection | `Projection.from_canonical(instance)` | — (narrows) |

`from_canonical` forwards `mode`, `by_alias` (default `True`), `context`,
`exclude_none`, `exclude_unset`, `exclude_defaults`, and `narrow` to the
instance's `model_dump`.

## `Projection` — derived classes

| name | kind | summary |
|---|---|---|
| `Projection.from_canonical(instance, *, mode, by_alias, context, exclude_none, exclude_unset, exclude_defaults, narrow)` | classmethod | Canonical (or wider projection) instance → projected instance; kwargs forwarded to `model_dump`. The instance-level narrowing counterpart of re-projection. |
| `Projection.scope(scope, *, name=None, bases=None)` | classmethod | **Re-project**: derive a narrower projection from this one — `Source.scope(__prism_scope__ & scope)`. Only ever narrows (a view can't expose more than it has); returns a *sibling* projection of the canonical, not a subclass. `bases` defaults to this projection's `__prism_bases__`. |
| `Projection.__prism_source__` | ClassVar | The canonical `ScopedModel` class this projection derives from. |
| `Projection.__prism_scope__` | ClassVar | The `ScopeExpr` the projection was built for. |
| `Projection.__prism_bases__` | ClassVar | The carried bases tuple (`()` when none). |
| `Projection.__refs__` | ClassVar | The surviving slice of the canonical's `RefGraph`. |

## Validators

`@field_validator`s carry to projections for the fields that survive.
`@model_validator`s on the canonical's own body do **not** (they assume the full
field set); model validators on a *carried base* do. To make a model validator
travel, declare it with `@scoped_validator(*scopes, mode=...)` — it carries onto
every projection whose expression selects one of `scopes`. Field-set safety is
yours: prism does not check that the touched fields survive there.

## Axes, governance, and data flow

A scope's **axis** (dimension) is its top ancestor just below `Scope`, read from
the inheritance forest (`dimension_root`). `dimensions()` and `data_flow()` are
*structural* (any axis, no marker import); `classifications()` / `redacted()` are
the *semantic* slice (Classification-marker-based — they need to know an axis
means "redact me").

| name | kind | summary |
|---|---|---|
| `Model.dimensions()` | classmethod | `dict[type[Scope], frozenset[type[Scope]]]`: the model's scopes grouped by axis root, inferred structurally. Discovers visibility / classification / direction / any user axis. |
| `Model.classifications()` | classmethod | `frozenset[type[Classification]]` declared on the model (the classification slice of `scopes()`). |
| `Model.classified_fields()` | classmethod | `dict[str, frozenset[type[Classification]]]`: field → classifications it carries. |
| `Model.redacted(visible, *, strip=None, name=None, bases=None)` | classmethod | The `visible` projection (one scope/expression) with classifications stripped (set difference). `strip` defaults to **all** declared classifications. |
| `Model.data_flow()` | classmethod | A `FlowReport`: every reachable model's tagged fields with scopes grouped by axis, across the ref graph (BFS, cycle-safe). PII surfaces as the `Classification`-rooted slice. |
| `build_flow_report(root)` | function | The underlying builder; `data_flow()` calls it. |
| `FlowReport` | dataclass | `.root`, `.nodes`, `.edges`; `.as_dict()` (JSON artifact), `.to_mermaid(direction="TD")`. Truthy iff any tagged data is reachable. |
| `FlowNode` | dataclass | A reached model with tagged data: `.model`, `.fields` (`tuple[FlowField, ...]`). |
| `FlowEdge` | dataclass | One forward edge of the walk: `.source`, `.field_name`, `.target`, `.kind`. |
| `FlowField` | dataclass | `.field_name`, `.scopes`, `.labels` (sorted names), `.by_dimension` (`{axis: (names,)}`). |

## The relationship graph

| name | kind | summary |
|---|---|---|
| `RefGraph` | class | `Mapping[str, RefInfo]` keyed by field name; `.owner`, `.targets()`, `.walk()` (BFS over forward + embedded edges), `.diagram(...)`, plus kind-typed accessors `.outgoing` (`dict[str, IdRefInfo]`), `.incoming` (`dict[str, BackRefInfo]`), `.embedded` (`dict[str, EmbeddedRefInfo]`). |
| `RefInfo` | dataclass | Base edge: `.field_name`, `.target`, `.target_field`, `.shape`, `.optional`, `.kind`, `.key_type` (shape-driven), `.many` (derived). `__refs__[name]` is typed as this; narrow with `isinstance` / `match .kind`. |
| `IdRefInfo` | dataclass | `kind="ref"`: a forward id-valued FK edge. |
| `BackRefInfo` | dataclass | `kind="backref"`: a declared reverse edge; adds `.via: str`. |
| `EmbeddedRefInfo` | dataclass | `kind="embedded"`: an embedded carrier/composition edge; adds `.scope: ScopeExpr \| None`. `.target` is always the **canonical** model. |

## Diagram export

| name | kind | summary |
|---|---|---|
| `scope_diagram(*scopes, direction="TD")` | function | The scope-inheritance `Diagram`; no args = all declared scopes. |
| `projection_diagram(Model, *, direction="TD")` | function | A canonical model + one node per scope in `Model.scopes()`, with surviving fields. |
| `RefGraph.diagram(*, direction="TD")` | method | The cross-model relationship `Diagram`. |
| `Diagram` | dataclass | `.to_mermaid()`, `.to_dot()`, `.to_d2()`, `.as_dict()`; `.nodes`, `.edges`, `.direction`. |
| `Node` / `NodeField` | dataclass | Node: `.id`, `.label`, `.kind`, `.description`, `.fields`. NodeField: `.name`, `.type`, `.description`. `as_dict()` is lossless. |

`Diagram` emits text only — no Graphviz/Mermaid/D2 dependency.

## Errors

See the dedicated [errors reference](errors.md). All domain errors subclass
`PrismError`; misuse of the API itself raises plain `TypeError`.

## CLI

See the [CLI reference](cli.md) for `prism gen` / `check` / `diagram` / `flow`
and `[tool.pydantic-prism]`.
