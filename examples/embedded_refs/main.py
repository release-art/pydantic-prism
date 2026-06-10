"""Embedded ref-records: projections used as carrier records in other models.

Run from the repository root:

    pdm run python examples/embedded_refs/main.py

Shows: a hand-rolled "ref scope" carrying ``{id, taken_at}``, used as
``list[SnapshotRef]`` and ``dict[UUID, SnapshotRef]`` — auto-registered as
``embedded`` edges resolving back to the canonical model, no ``ref()``
marker needed.
"""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Carrier(Scope): ...


class LlmSnapshot(ScopedModel):
    id: Annotated[UUID, scoped(Public, Carrier)]
    taken_at: Annotated[str, scoped(Public, Carrier)]
    prompt: Annotated[str, scoped(Public)]
    raw_response: Annotated[str, scoped(Public)]


LlmSnapshotRef = LlmSnapshot.scope(Carrier)  # the {id, taken_at} mini-model


class PageCheck(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    url: Annotated[str, scoped(Public)]
    snapshots: Annotated[list[LlmSnapshotRef], scoped(Public)] = []  # type: ignore[valid-type]
    latest_by_model: Annotated[dict[str, LlmSnapshotRef], scoped(Public)] = {}  # type: ignore[valid-type]


def demo() -> None:
    edge = PageCheck.__refs__["snapshots"]
    print(
        f"snapshots: kind={edge.kind}, target={edge.target.__name__}, "
        f"carrier scope={edge.scope!r}, shape={edge.shape}"
    )
    print(f"embedded edges: {sorted(PageCheck.__refs__.embedded)}")

    sid = uuid4()
    check = PageCheck(
        id=uuid4(),
        url="https://example.com/terms",
        snapshots=[{"id": sid, "taken_at": "2026-06-10T12:00:00Z"}],
    )
    print(f"carrier fields only: {list(type(check.snapshots[0]).model_fields)}")

    # the edge survives projection and still points at the canonical
    projected = PageCheck.scope(Public)
    print(f"projected target: {projected.__refs__['snapshots'].target.__name__}")


if __name__ == "__main__":
    demo()
