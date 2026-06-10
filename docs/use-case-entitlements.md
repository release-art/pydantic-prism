# Use case — plan-tier / entitlement field gating (multi-tenant SaaS)

Captured 2026-06-10 (third dive). Positioning + feature note, parked for the
docs restructure. **Strong, new** — a distinct visibility axis from PII.

## The pain

Multi-tenant SaaS routinely needs *which response fields a tenant sees to depend
on their subscription tier* — Free sees the basics, Pro sees more, Enterprise
sees everything. Today this is solved with hardcoded plan logic in business code
or per-tenant feature-flag config objects, and the guidance is explicitly "check
entitlements **server-side**" and "never hardcode plan logic into business
rules" ([feature-flag best practices](https://designrevision.com/blog/saas-feature-flags-guide),
[per-tenant flags](https://bugfree.ai/knowledge-hub/handle-per-tenant-feature-flags-multi-tenant-saas-architecture)).
There is no clean *schema-level* answer — the field set per tier is scattered
across `if plan == "pro"` checks.

## Why prism fits

A plan tier is a visibility scope, and tiers form an inheritance ladder
(higher tier = strictly more fields) — exactly prism's scope model:

```python
class Free(Scope): ...
class Pro(Free): ...
class Enterprise(Pro): ...

class Dashboard(ScopedModel):
    id:            Annotated[UUID, scoped(Free)]
    basic_stats:   Annotated[Stats, scoped(Free)]
    advanced_stats:Annotated[Stats, scoped(Pro)]          # Pro and up
    raw_export:    Annotated[bytes, scoped(Enterprise)]   # Enterprise only

# runtime selection — scope() is cached, so the projection per tier is stable
PLAN = {"free": Free, "pro": Pro, "enterprise": Enterprise}

@app.get("/dashboard", response_model=...)        # response_model per tier route, or:
def dashboard(tenant: Tenant):
    view = Dashboard.scope(PLAN[tenant.tier])
    return view.from_canonical(full_dashboard)
```

The entitlement *is* the projection; there is one canonical model and the
"which fields per plan" matrix lives in the field tags, not in scattered
conditionals. Server-side by construction (the field literally isn't in the
lower-tier projection).

## Distinct from — but composable with — PII

PII governance *hides sensitive* fields; entitlements *unlock premium* fields —
opposite intents, same engine, and they **compose**: `Pro - Pii` is "the Pro
field set, with personal data stripped" for, say, a Pro-tier export that still
must be GDPR-safe. That composition is the kind of thing only the set algebra
gives you. See [PII governance](use-case-pii-governance.md) and
[read/write fields](use-case-readwrite-fields.md) — three visibility axes
(sensitivity, role, entitlement) over one model.

## The bet (convention + docs)

- A blessed plan-ladder example and a docs page framing prism as the
  *schema-level* answer to entitlement field-gating (vs. hardcoded plan checks).
- Show the runtime `scope(PLAN[tier])` pattern and the FastAPI wiring (one route
  per tier, or dynamic `response_model`).

## Honest boundary

prism gates field **presence**. It does **not** model numeric limits ("max 5
projects"), rate limits, or boolean feature toggles — that is the
entitlement/feature-flag *config* layer, and prism only owns the "which fields"
slice of it. Pitch accordingly: "the field-shape half of entitlements, done at
the schema."
