"""Dict-keyed refs: ``dict[UUID, Embedded]`` where the key IS the foreign id.

Run from the repository root:

    pdm run python examples/dict_keyed_refs/main.py

Shows: ``ref()`` on a keyed-dict annotation, ``RefShape.KEYED_DICT`` with the
recorded key type, the expected/found-highlights shape with a back-pointer,
and the refs surviving projection.
"""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic_prism import Scope, ScopedModel, ref, scoped


class Public(Scope): ...


class Internal(Public): ...


class ExpectedHighlight(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    quote: Annotated[str, scoped(Public)]


class FoundHighlight(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    expected_id: Annotated[UUID, ref(ExpectedHighlight), scoped(Public)]
    snippet: Annotated[str, scoped(Public)]
    score: Annotated[float, scoped(Internal)] = 0.0


class ComplianceAudit(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    expected: Annotated[
        dict[UUID, ExpectedHighlight], ref(ExpectedHighlight), scoped(Public)
    ]
    found: Annotated[dict[UUID, FoundHighlight], ref(FoundHighlight), scoped(Public)]


def demo() -> None:
    info = ComplianceAudit.__refs__["expected"]
    print(
        f"expected: shape={info.shape}, key={info.key_type.__name__}, "
        f"target={info.target.__name__}"
    )

    eid, fid = uuid4(), uuid4()
    audit = ComplianceAudit(
        id=uuid4(),
        expected={eid: ExpectedHighlight(id=eid, quote="must disclose fees")},
        found={fid: FoundHighlight(id=fid, expected_id=eid, snippet="fees: ...")},
    )

    AuditPublic = ComplianceAudit.scope(Public)
    public = AuditPublic.from_canonical(audit)
    print(f"projected refs: {dict(AuditPublic.__refs__)!r}")
    print(f"found -> expected back-pointer: {public.found[fid].expected_id == eid}")  # type: ignore[attr-defined]
    print("graph edges:")
    for source, edge in ComplianceAudit.__refs__.walk():
        print(
            f"  {source.__name__}.{edge.field_name} -> "
            f"{edge.target.__name__} ({edge.shape})"
        )


if __name__ == "__main__":
    demo()
