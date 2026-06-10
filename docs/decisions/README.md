# Design decisions (ADR archive)

The historical design record, archived verbatim. These are *decision records*,
not user documentation — they capture the reasoning, alternatives, and
trade-offs behind the shipped API. For how the library works today, start at the
[documentation home](../README.md); the [explanation pages](../explanation/README.md)
distill the durable "why" from these memos.

## The decision log

- [**API decision record**](api-decisions.md) — the numbered running log of
  every API decision (v0.1 onward). The canonical reference for *what* was
  decided and *why*.

## Design memos, by round

Each memo works through one round of adoption feedback or a new capability.

| round | topic |
|---|---|
| [2](design-round-2.md) | Adoption feedback — `projection_bases=`, scope propagation |
| [3](design-round-3.md) | Class-level `default_scope=` |
| [4](design-round-4.md) | Static-type visibility for projections (`prism gen`) |
| [5](design-round-5.md) | `@scoped_validator` — model validators that survive projection |
| [6](design-round-6.md) | `with_updates` patch API |
| [7](design-round-7.md) | Projection naming + per-scope schema metadata |
| [8](design-round-8.md) | Partial round-trip story + doc-debt audit |
| [9](design-round-9.md) | `RefInfo` shape audit (scalar / collection / keyed-dict) |
| [10](design-round-10.md) | Diagram export |
| [11](design-round-11.md) | Preserve field metadata in derived objects |
| [12](design-round-12.md) | Diagram CLI + generated README |
| [13](design-round-13.md) | Auto-generated example READMEs |
| [15](design-round-15.md) | Partial scopes via the `MISSING` sentinel |
| [16](design-round-16.md) | Classification axis + data-flow governance |

> [!NOTE]
> Rounds 1 and 14 have no memo in this archive — the numbering follows the
> original design process and is preserved as-is rather than renumbered.
