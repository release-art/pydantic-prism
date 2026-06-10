"""Schema governance: classify fields, derive redacted views, trace PII flow.

Run from the repository root:

    pdm run python examples/pii_dataflow/main.py

The idea: treat data **classification** (PII, Secret) as a scope *dimension*
orthogonal to **visibility** (Public < Internal < Storage). A field carries
its visibility scope plus, optionally, a classification scope — two `scoped()`
markers, unioned. Then prism's existing primitives do the governance work:

  * `Model.scope(Internal - Pii - Secret)`  → an audit-safe view (redaction is
    just set difference; no parallel "log model", no hand-maintained excludes).
  * `expr.matches(Pii)`                      → "is this field classified PII?"
  * `__refs__.walk()`                        → trace PII across the ref graph:
    *where does personal data flow, through which references?*

Everything below is built on the public API — nothing here is in the library
(yet). That ~40-line governance layer is the prototype: the question is which
parts deserve to become first-class (`Classification`, `Model.redacted(...)`,
`Model.pii_report()`).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from pydantic_prism import Scope, ScopedModel, ref, scoped


# --- visibility ladder (inheritance = "broader") ---------------------------
class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


# --- classification dimension (orthogonal: a field can be Public AND Pii) ---
class Pii(Scope): ...


class Secret(Scope): ...


CLASSIFICATIONS: tuple[type[Scope], ...] = (Pii, Secret)

# Redaction is set algebra: everything visible to an internal auditor, minus
# anything classified. One expression replaces a hand-maintained "audit model".
AUDIT_SAFE = Internal - Pii - Secret


# --- domain -----------------------------------------------------------------
class Address(ScopedModel):
    id: Annotated[UUID, scoped(Public), Field(description="Address identifier.")]
    city: Annotated[str, scoped(Public), Field(description="City (non-PII).")]
    line1: Annotated[
        str, scoped(Internal), scoped(Pii), Field(description="Street address (PII).")
    ]
    postcode: Annotated[
        str, scoped(Internal), scoped(Pii), Field(description="Postal code (PII).")
    ]


class User(ScopedModel):
    id: Annotated[UUID, scoped(Public), Field(description="User identifier.")]
    display_name: Annotated[
        str, scoped(Public), Field(description="Public display name.")
    ]
    email: Annotated[
        str,
        scoped(Public),
        scoped(Pii),
        Field(description="Contact email — public-facing, still PII."),
    ]
    phone: Annotated[
        str, scoped(Internal), scoped(Pii), Field(description="Phone number (PII).")
    ]
    password_hash: Annotated[
        str,
        scoped(Storage),
        scoped(Secret),
        Field(description="Password hash (secret, storage-only)."),
    ]
    address_id: Annotated[
        UUID, ref(Address), scoped(Internal), Field(description="Home address ref.")
    ]


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public), Field(description="Order identifier.")]
    user_id: Annotated[
        UUID, ref(User), scoped(Public), Field(description="Who placed the order.")
    ]
    ship_to_id: Annotated[
        UUID, ref(Address), scoped(Public), Field(description="Shipping address ref.")
    ]
    card_last4: Annotated[
        str,
        scoped(Internal),
        scoped(Pii),
        Field(description="Card last 4 digits (PII)."),
    ]
    total: Annotated[
        Decimal, scoped(Internal), Field(description="Order total (internal).")
    ]


# --- the governance layer (candidate library API) ---------------------------
def classifications_of(model: type[ScopedModel], field: str) -> frozenset[type[Scope]]:
    """Which classifications a field carries — `expr.matches(C)` per class."""
    expr = model.__field_scopes__.get(field)
    if expr is None:
        return frozenset()
    return frozenset(c for c in CLASSIFICATIONS if expr.matches(c))


def pii_inventory(model: type[ScopedModel]) -> dict[str, frozenset[type[Scope]]]:
    """Every classified field on one model → the classifications it carries."""
    return {
        field: tags
        for field in model.model_fields
        if (tags := classifications_of(model, field))
    }


def dataflow_report(
    root: type[ScopedModel],
) -> Mapping[type[ScopedModel], dict[str, frozenset[type[Scope]]]]:
    """Trace classified data reachable from `root` across the ref graph.

    Walks forward refs/embeds (BFS, cycle-safe) and reports the classified
    fields of every model personal data can reach. This is the artifact a
    compliance review wants: *given this entry point, where does PII live?*
    """
    reachable: set[type[ScopedModel]] = {root}
    for source, edge in root.__refs__.walk():
        reachable.add(source)
        reachable.add(edge.target)
    return {m: inv for m in reachable if (inv := pii_inventory(m))}


def _names(scopes: frozenset[type[Scope]]) -> str:
    return "+".join(sorted(s.__name__ for s in scopes))


def demo() -> None:
    # --- 1. classification inventory per model ------------------------------
    print("PII / Secret inventory:")
    for model in (User, Address, Order):
        for field, tags in pii_inventory(model).items():
            print(f"  {model.__name__}.{field:<13} [{_names(tags)}]")

    # --- 2. redaction is set difference, not a parallel class ---------------
    UserAudit = User.scope(AUDIT_SAFE)
    print(f"\nUser fields:        {list(User.model_fields)}")
    print(f"User.scope({AUDIT_SAFE!r})")
    print(f"  -> audit-safe:    {list(UserAudit.model_fields)}")

    ada = User(
        id=uuid4(),
        display_name="Ada",
        email="ada@example.com",
        phone="+1-555-0100",
        password_hash="$argon2id$…",
        address_id=uuid4(),
    )
    safe = UserAudit.from_canonical(ada)
    print(f"  redacted dump:    {safe.model_dump(mode='json')}")
    assert "email" not in safe.model_dump()
    assert "password_hash" not in safe.model_dump()

    # --- 3. data-flow: where does classified data go, reachable from Order? --
    print("\nClassified data reachable from Order (follow the refs):")
    for source, edge in Order.__refs__.walk():
        downstream = pii_inventory(edge.target)
        hits = ", ".join(f"{f} [{_names(t)}]" for f, t in downstream.items())
        marker = f"  ⮑ {hits}" if hits else ""
        print(
            f"  {source.__name__}.{edge.field_name} -> {edge.target.__name__}{marker}"
        )

    print("\nGovernance report — classified data reachable from Order:")
    for model, inventory in dataflow_report(Order).items():
        fields = ", ".join(f"{f} [{_names(t)}]" for f, t in inventory.items())
        print(f"  {model.__name__}: {fields}")

    # --- 4. refs survive redaction (the graph still holds) ------------------
    assert UserAudit.__refs__["address_id"].target is Address
    print("\nThe redacted UserAudit still knows address_id -> Address")


if __name__ == "__main__":
    demo()
