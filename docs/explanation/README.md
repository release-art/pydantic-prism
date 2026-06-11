# Explanation

Understanding-oriented background — the *why* behind prism's design. These
pages don't teach a task or list an API; they explain the ideas so the rest of
the docs make sense.

- **[Scopes and the algebra](scopes-and-the-algebra.md)** — why scopes are
  classes, why inheritance forms the graph, the one-line membership rule, the
  set operators, and the orthogonal classification axis.
- **[Projections, not inheritance](projections-not-inheritance.md)** — why a
  projection is a filtered, real `BaseModel` subclass rather than a child class
  of the canonical; what this solves over hand-written DTOs and raw
  `create_model`.
- **[What `ref()` models — and what it doesn't](what-ref-models.md)** — the
  deliberate decision that references are introspection-only: no resolution, no
  referential integrity, no ORM.
- **[Compared to prior art](vs-prior-art.md)** — the honest overlap with
  existing projection libraries, and the two things that are genuinely new.
