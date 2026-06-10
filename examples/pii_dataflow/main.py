"""Schema governance: classify fields, derive redacted views, trace PII flow.

Run from the repository root:

    pdm run python examples/pii_dataflow/main.py

The idea: treat data **classification** (PII, Secret) as a scope *dimension*
orthogonal to **visibility** (Public < Internal < Storage). A field carries its
visibility scope plus, optionally, a classification scope — two `scoped()`
markers, unioned. Classifications subclass `Classification` (itself a `Scope`),
so prism can tell the two axes apart and do the governance work first-class:

  * `Model.redacted(Internal)`     → an audit-safe view: the Internal projection
    with every classification stripped (redaction is set difference; no parallel
    "log model", no hand-maintained excludes).
  * `Model.classified_fields()`    → the per-model PII/Secret inventory.
  * `Model.classified_flow()`      → a `FlowReport` tracing classified data
    across the ref graph: *where does personal data flow, through which refs?*
    Renders to JSON (`.as_dict()`) or Mermaid (`.to_mermaid()`) for review, and
    from the CLI via `prism flow examples.pii_dataflow.main:Order`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from pydantic_prism import Classification, Scope, ScopedModel, ref, scoped


# --- visibility ladder (inheritance = "broader") ---------------------------
class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


# --- classification dimension (orthogonal: a field can be Public AND Pii) ---
class Pii(Classification): ...


class Secret(Classification): ...


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


def _labels(tags: frozenset[type[Classification]]) -> str:
    return "+".join(sorted(c.__name__ for c in tags))


def demo() -> None:
    # --- 1. classification inventory per model ------------------------------
    print("PII / Secret inventory:")
    for model in (User, Address, Order):
        for field, tags in model.classified_fields().items():
            print(f"  {model.__name__}.{field:<13} [{_labels(tags)}]")

    # --- 2. redaction is set difference, not a parallel class ---------------
    # redacted(Internal) strips *every* classification the model declares.
    UserAudit = User.redacted(Internal)
    print(f"\nUser fields:        {list(User.model_fields)}")
    print(f"User.redacted(Internal)  (strips {_labels(User.classifications())})")
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
    report = Order.classified_flow()
    print("\nClassified data reachable from Order (follow the refs):")
    for node in report.nodes:
        fields = ", ".join(
            f"{f.field_name} [{'+'.join(f.labels)}]" for f in node.fields
        )
        print(f"  {node.model.__name__}: {fields}")

    # --- 4. the same report as the compliance artifact (JSON / Mermaid) -----
    print("\nFlow report edges:")
    for edge in report.edges:
        print(f"  {edge.source.__name__}.{edge.field_name} -> {edge.target.__name__}")

    # --- 5. refs survive redaction (the graph still holds) ------------------
    assert UserAudit.__refs__["address_id"].target is Address
    print("\nThe redacted UserAudit still knows address_id -> Address")


if __name__ == "__main__":
    demo()
