# Use case — read-only / write-only fields (mass-assignment protection)

Captured 2026-06-10 (second market/feature dive). Positioning + feature note,
parked for the docs restructure. Strongest new find of the second dive.

## The pain (real, unsolved, security-adjacent)

Splitting a model into "what a client may **write**" vs "what the server
**returns**" is a daily need with no clean native answer:

- Pydantic has an *open* request for a native `read_only` field
  ([#9917](https://github.com/pydantic/pydantic/issues/9917)); `init=False` /
  `frozen=True` are the wrong tools.
- FastAPI confirms "there isn't yet a native, clean solution" and the documented
  workaround is **awkward parallel `FooPost` / `FooGet` models**
  ([#5083](https://github.com/fastapi/fastapi/issues/5083),
  [#12233](https://github.com/fastapi/fastapi/discussions/12233)) — precisely the
  hand-maintained duplication prism exists to kill.

The security framing makes this more than ergonomics: letting a client set
server-controlled fields (`id`, `created_at`, `owner_id`, `role`, `is_admin`) is
the **mass-assignment / over-posting** vulnerability class.

## prism solves it by construction

Read/write intent is just scope membership. A server-controlled field is in the
**output** scope but not the **input** scope, so the input projection *has no
such field* — the client cannot over-post it:

```python
class In(Scope): ...      # request body
class Out(Scope): ...      # response

class Account(ScopedModel):
    id:         Annotated[UUID, scoped(Out)]                 # read-only: server sets it
    created_at: Annotated[datetime, scoped(Out)]             # read-only
    is_admin:   Annotated[bool, scoped(Out)]                 # read-only — NOT settable
    email:      Annotated[str, scoped(In, Out)]              # read-write
    password:   Annotated[str, scoped(In)]                   # write-only (never returned)

AccountIn  = Account.scope(In)    # email, password         ← no id/created_at/is_admin
AccountOut = Account.scope(Out)   # id, created_at, is_admin, email   ← no password
```

`AccountIn` literally lacks `is_admin`, so over-posting is impossible by shape,
not by a runtime check. Write-only (`password`) and read-only (`created_at`)
both fall out of the same one model — no `FooPost`/`FooGet` pair.

To turn silent-ignore into hard rejection (so an unknown `is_admin` in the body
*errors* rather than being dropped), the input projection wants
`extra="forbid"`. **Design question:** should prism default input-intent
projections to `extra="forbid"`, or expose it on `.scope(...)`? This is the one
real decision here — the field-shape half already works today.

## Incumbent vocabulary = a migration audience

This is exactly DRF's `read_only_fields` / `write_only` and Marshmallow's
`dump_only` / `load_only` — vocabulary millions of developers already know, and
which carries documented duplication pain (DRF
[#3533](https://github.com/encode/django-rest-framework/issues/3533): "copy-paste
field declarations just to specify read_only"; `drf-dynamic-fields` /
`drf-flex-fields` exist to paper over it). Positioning prism as *"`read_only` /
`write_only`, but DRY across one typed canonical model — and graph-aware"* speaks
directly to that audience in their own terms.

## The bet (mostly convention + one config decision)

| | |
|---|---|
| blessed `In` / `Out` (or `ReadOnly` / `WriteOnly`) scope convention | so it's a recognized pattern, not folklore |
| `extra="forbid"` story for input projections | the over-posting hard-stop; default vs opt-in is the open question |
| docs framing as mass-assignment protection + a DRF/Marshmallow migration page | reaches a large incumbent audience |

Like the [LLM scope](use-case-llm-tool-schema.md), the mechanism already exists;
what's missing is the convention, the `extra` decision, and the framing. Pairs
naturally with [PII governance](use-case-pii-governance.md) (visibility) and
[partial update](use-case-partial-update.md) (the `In` scope is often also
`partial=True` for PATCH).
