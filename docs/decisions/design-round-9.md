# Design memo — round 9 (RefInfo shape audit)

Phase 1 output, 2026-06-10. Decide `RefInfo`'s shape and commit: discriminated
subtypes, or the current single dataclass — drifting between them is the bad
outcome the feedback names.

## Audit (the numbers, corrected)

`RefInfo` has **nine** fields plus one property, not "~8 optionals":

| field | when meaningful | always present? |
|---|---|---|
| `field_name`, `target`, `target_field`, `shape`, `optional`, `kind` | all edges | **yes** (6) |
| `key_type` | `shape is KEYED_DICT` | conditional on **shape** |
| `via` | `kind == "backref"` | conditional on **kind** |
| `scope` | `kind == "embedded"` | conditional on **kind** |
| `.many` (property) | all edges | derived from `shape` |

So only **three** fields are conditional, and they split across **two
orthogonal axes**: `key_type` is driven by `shape`, while `via`/`scope` are
driven by `kind`. This matters because the feedback's proposed split —
`IdRefInfo` / `EmbeddedRefInfo` / **`KeyedDictRefInfo`** — mixes the axes:
`Id`/`Embedded` are *kinds*, `KeyedDict` is a *shape*. A keyed dict can be a
`ref` (`dict[UUID, Payload]`) **or** an `embedded` edge (`dict[UUID,
SnapshotRef]`), so there is no clean three-way type partition along that line.
The only clean discriminant is `kind`.

## Option A — commit to the single dataclass

Keep one `RefInfo`; formalize the contract: `kind` is the discriminant,
`key_type`/`via`/`scope` are documented as conditional, `.many` is the stable
derived property. The `.outgoing` / `.incoming` / `.embedded` accessors already
partition by kind for callers who want a filtered view.

- **Pro:** no breaking change; the common path (`info.target`, `info.shape`,
  `info.kind`) is uniform and flat; the "bag" is small (3 conditional fields, one
  of which is shape-not-kind so it wouldn't leave a kind-split base anyway);
  matches an introspection-only record that callers mostly just read.
- **Con:** `via`/`scope` are typed `… | None` even where they can't apply, so a
  type checker can't prove `info.via` is set on a backref without a `None` check.

## Option B — split by `kind` (the only clean axis)

A base `RefInfo` (the 6 always-present fields + `key_type` + `.many`) and three
variants adding only their kind-specific field:

```
RefInfo (base)                      # field_name, target, target_field, shape,
  ├─ IdRefInfo      kind="ref"      #   optional, kind, key_type, .many
  ├─ BackRefInfo    kind="backref"  # + via: str
  └─ EmbeddedRefInfo kind="embedded"# + scope: ScopeExpr | None
```

`key_type` stays on the base (it tracks `shape`, not `kind`). `__refs__[name]`
returns the base `RefInfo`; the accessors get **precise** types —
`outgoing: dict[str, IdRefInfo]`, `incoming: dict[str, BackRefInfo]`,
`embedded: dict[str, EmbeddedRefInfo]` — so `graph.incoming["x"].via` is `str`,
no `None` check. `isinstance` / `match info.kind` narrow `__refs__` reads.

- **Pro:** kind-specific fields are non-optional on their variant; the
  introspection surface (the library's whole pitch) gets type-precise; aligns
  with the structural bent of the rest of the API.
- **Con:** **breaking change** — `via`/`scope` leave the base, so code reading
  them off a base-typed `RefInfo` must narrow first (acceptable pre-1.0, and
  exactly the reads that *should* discriminate); three new public types + a
  base; more docs/tests. `key_type` is still shape-conditional on the base —
  the split removes two conditional fields (`via`, `scope`), not all three.

## Recommendation

**Lean A (commit)** — but it's close, and genuinely the owner's call. The reason
to lean commit: the problem is smaller than "8 optionals" suggested (3
conditional fields), the only clean discriminant (`kind`) wouldn't even capture
`key_type`, and the dominant consumer pattern is "read `.target`/`.shape`/`.kind`
uniformly," which a flat record serves best with zero breakage. The strongest
reason to choose **B** instead is the precise accessor typing
(`incoming[...].via: str`), which fits this codebase's structural values and the
introspection-first pitch; pre-1.0 is the right (and feedback-invited) moment if
we're going to. What we must *not* do is add subtypes while keeping every field
on the base too — that is the drift.

## Phase-2 questions

1. **Commit (A) vs split-by-kind (B).**
2. If **B**: keep `RefInfo` as the importable **base** class (recommended, so
   `isinstance`/imports survive) vs make it a union alias.
3. Either way: keep `.many` (recommended — cheap, documented) — confirm.
