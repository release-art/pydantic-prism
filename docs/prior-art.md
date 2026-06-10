# Prior-art memo — pydantic-prism v0.1

Phase 1 output. Sources were read at source/docs level (not skimmed) in June 2026.
Each entry: what it does well, what's awkward, what we steal or avoid.

## pydantic-extension (humblemat810, PyPI `pydantic-extension` 0.0.7)

The closest existing thing: Annotated marker instances (`DtoField()`, `BackendField()`,
`ExcludeMode("llm")`) tag fields on one model, and `User["dto", "frontend"]` derives a
**real `BaseModel` subclass** via `create_model`, cached for identity stability
(`User["dto"] is User["dto"]`), with union composition across modes and a deep
annotation-rewriter that projects nested models through `Optional`/`Union`/containers.
What's awkward: a heavy magic layer that walks `inspect.stack()` to detect langchain
frames and silently switches dump/validate/schema behavior to "llm" mode —
`model_validate` can return an instance of a *different class* than the one called;
its `model_dump` override breaks vanilla pydantic callers (`mode=` kwarg collision);
slices subclass plain `BaseModel` so the parent's validators and methods silently
vanish; modes are class-named (`DtoField`) so new scopes need `register_mode()`
class-generation; generated names degenerate (`UserBackendDtoFrontendLlmNotLlmSlice`);
packaging/docs are broken (no declared deps, wrong install name in README).

**Steal:** cached `create_model`-built real BaseModel slices; union semantics for
multi-scope; per-field markers in `Annotated`. **Avoid:** all implicit context magic
(stack sniffing, ContextVar mode), overriding `model_dump`/`model_validate` at all,
fixed marker classes per scope, subscript-only access (collides with `Generic[T]`).

## pydantic-views (alfred82santa, PyPI `pydantic-views` 0.3.0)

CRUD-shaped views from a 6-value `AccessMode` enum used as inert `Annotated`
metadata (`ReadOnly = Annotated[T, AccessMode.READ_ONLY]`); `Builder` objects derive
views (`BuilderUpdate().build_view(User)` → `UserUpdate`), with genuinely good
mechanics: markers stripped from the derived model's metadata, untagged fields in
every view, all-optional Update models done via `default_factory=PydanticUndefined`
(keeps `model_fields_set` truthful instead of polluting annotations with `| None`),
recursive nested-view substitution with `ForwardRef` + `model_rebuild` for cycles,
and `__module__`/`__doc__`/deterministic `{Model}{View}` naming on generated classes.
What's awkward: scope *names* are not user-definable — everything must map onto the
fixed CRUD enum; views are built imperatively by builder objects rather than asked of
the model; it monkey-patches a `model_views` registry attribute onto user classes;
Python ≥3.13 only; visible copy-paste bugs and reliance on pydantic `_internal`.

**Steal:** the inclusion rule (drop iff field has markers AND none match), marker
stripping, `__module__`/`__doc__`/naming hygiene on generated classes, ForwardRef +
`model_rebuild` recipe for nested models. **Avoid:** fixed scope vocabulary,
builder-object ceremony, monkey-patched registries.

## pydantic discussions #2547 / issue #5293 / discussion #8782

Demand for Pick/Omit/Partial-style derivation is recurring since 2021; pydantic core
**closed #5293 as will-not-implement** (dmontagu: too much maintenance "until
something comparable is added to the `typing` module", and static type checkers
can't see dynamically derived models anyway). #8782 is the closest to our design:
a user proposes inert `Annotated` markers (`ExposedViews(["customer"])`) plus
`restricted_view_class(view)`, and community answers prove the pattern works by
reading markers back from `FieldInfo.metadata` — but the answers degrade into
core-schema surgery via `pydantic._internal` for nested cases.

**Implications:** (a) the library fills a confirmed, explicitly-vacated gap;
(b) static type-checker opacity of derived models is a known, accepted limitation —
be honest about it in the README rather than promising plugin magic; (c) build on
public API only (`FieldInfo.metadata`, `create_model`, `model_rebuild`), never
`pydantic._internal`.

## pydantic v2's own idioms (verified on 2.13.4)

Pydantic decomposes `Field()` constraints into `annotated_types` objects stored in
`FieldInfo.metadata` in source order, and — verified empirically — **preserves
unknown objects in `Annotated` metadata verbatim, silently, with working validation,
serialization and JSON schema**. This is the load-bearing fact: inert frozen
dataclass markers are a fully supported pattern (FastAPI's `Query`/`Depends` rely on
it). Caveats found: only *top-level* `Annotated` metadata is lifted into
`FieldInfo.metadata` (markers inside `list[Annotated[...]]` stay embedded in the
annotation); markers must not duck-type `annotated_types` members; docs recommend
keeping `default`/`default_factory`/`alias` in assignment position for static
checkers — which dovetails with our rule that markers live in `Annotated` and
defaults stay defaults.

**Steal:** frozen dataclass markers; read scopes via `model_fields[*].metadata`;
follow the `Annotated[T, marker, Field(...)]` composition idiom.

## Zod / Effect Schema / ArkType (naming survey)

Zod and ArkType both copy TypeScript utility-type vocabulary (`pick`/`omit`/
`partial`/`required`/`extend`); all their derivation is structural and repeated at
each call site — **no named reusable projections**. The one true prior art for
"tag fields once, derive variants by name" is `@effect/sql`'s `Model.Class`: field
tags are named for the field's *role* (`Model.Generated`, `Model.Sensitive`) and
variants for the *use case* (`Group.insert`, `Group.json`) — but its variant set is
fixed by the library. ArkType's `scope()` shows string-name references between
sibling types reading naturally and handling cycles.

**Steal:** the naming lesson — derivation call sites should read as a use case, not
a field list; short lowercase verbs; "scope" itself is established vocabulary
(ArkType) without ORM connotations. **Avoid:** Zod's `{field: true}` mask noise;
fixed variant sets.

## dddesign / eventsourcing (entity identity & refs)

dddesign (pydantic-based) does nominal IDs by subclassing (`class CustomerId(AutoUUID)`)
but declares cross-aggregate references *stringly and externally*
(`AggregateDependencyMapper(entity_attribute_name='media_id', ...)`) — exactly the
distance-from-the-field problem `Annotated[UUID, ref(Customer)]` removes. It does
validate that an FK field's annotation matches the target id's annotation, which is
worth copying. eventsourcing uses bare `ref: UUID` attributes with zero typing of
the target — the failure mode our marker exists to fix — though its per-class
deterministic `create_id()` (uuid5 from natural key) is a nice identity policy we
don't need in v0.1.

**Steal:** ref-annotation vs target-id-annotation consistency checking.
**Avoid:** external/stringly relationship declarations; untyped UUID refs.

## Consolidated design conclusions

1. Markers are inert frozen dataclasses in `Annotated`; read back from
   `FieldInfo.metadata`; stripped from derived models' metadata. Public pydantic
   API only.
2. Derived scopes are cached, real `BaseModel` subclasses built with `create_model`,
   with deterministic names, correct `__module__`/`__doc__`, and identity stability.
3. Scope names are user-defined strings (the gap every prior library leaves open);
   composition is union; no implicit context magic of any kind — never override
   `model_dump`/`model_validate` behavior.
4. Relationship metadata (`ref`) on fields, introspectable, surviving projection —
   greenfield; nothing surveyed does this.
5. Be explicit in the README that derived models are opaque to static type checkers
   (pydantic core's stated reason for not building this); that's the cost of dynamic
   derivation everywhere in the ecosystem.
