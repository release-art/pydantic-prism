"""A three-model relationship graph with refs that survive projection.

Run from the repository root:

    pdm run python examples/graph/main.py

Shows: forward refs, a declared backref, cardinality inference, graph
introspection (`__refs__`, `walk()`), refs surviving projection, and a tiny
hand-rolled resolver built on RefInfo — the kind of thing pydantic-prism
deliberately leaves to you (storage is your problem).
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from pydantic_prism import Scope, ScopedModel, backref, ref, scoped


class Public(Scope): ...


class Internal(Public): ...


class Customer(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    name: Annotated[str, scoped(Public)]
    order_ids: Annotated[
        list[UUID], backref("Order", via="customer_id"), scoped(Internal)
    ]


class Product(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    title: Annotated[str, scoped(Public)]
    unit_cost: Annotated[Decimal, scoped(Internal)]


class Order(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    customer_id: Annotated[UUID, ref(Customer), scoped(Public)]
    product_ids: Annotated[list[UUID], ref(Product), scoped(Public)]
    total: Annotated[Decimal, scoped(Internal)]


def demo() -> None:
    # --- introspection ------------------------------------------------------
    print("Order.__refs__:")
    for field_name, info in Order.__refs__.items():
        print(
            f"  {field_name} -> {info.target.__name__}.{info.target_field}"
            f" (many={info.many}, kind={info.kind})"
        )

    print("\nCustomer.__refs__.incoming:")
    for field_name, info in Customer.__refs__.incoming.items():
        print(f"  {field_name} <- {info.target.__name__} via {info.via!r}")

    print("\nwalk() from Order:")
    for source, edge in Order.__refs__.walk():
        print(f"  {source.__name__}.{edge.field_name} -> {edge.target.__name__}")

    # --- refs survive projection -------------------------------------------
    OrderPublic = Order.scope(Public)
    assert OrderPublic.__refs__["customer_id"].target is Customer
    print(f"\n{OrderPublic.__name__} fields: {list(OrderPublic.model_fields)}")
    print(f"{OrderPublic.__name__} still knows customer_id -> Customer")

    # --- a minimal resolver built on RefInfo (storage stays YOUR problem) ---
    ada = Customer(id=uuid4(), name="Ada")
    boots = Product(id=uuid4(), title="Boots", unit_cost=Decimal("80"))
    order = Order(
        id=uuid4(), customer_id=ada.id, product_ids=[boots.id], total=Decimal("99.90")
    )
    store: dict[type[ScopedModel], dict[UUID, ScopedModel]] = {
        Customer: {ada.id: ada},
        Product: {boots.id: boots},
    }

    def resolve(instance: ScopedModel, field_name: str) -> list[ScopedModel]:
        info = type(instance).__refs__[field_name]
        raw = getattr(instance, field_name)
        ids = list(raw) if info.many else [raw]
        return [store[info.target][value] for value in ids]

    (customer,) = resolve(order, "customer_id")
    (product,) = resolve(order, "product_ids")
    print(
        f"\nresolved: order {order.id} -> customer {customer.name!r}, products [{product.title!r}]"
    )


if __name__ == "__main__":
    demo()
