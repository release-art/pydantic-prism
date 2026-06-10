"""Custom-base composition: projections that keep your base class behavior.

Run from the repository root:

    pdm run python examples/custom_base/main.py

Shows: an Azure-Table-style base with a custom ``model_dump`` envelope and a
``@model_validator(mode="before")`` unwrap, carried onto projections via
``projection_bases=`` so round trips, validators, and ``isinstance`` checks
keep working on derived classes.
"""

from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, model_validator

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Storage(Public): ...


class TableRowBase(BaseModel):
    """Pretend Azure Table Storage row: dumps wrap data in an envelope."""

    @model_validator(mode="before")
    @classmethod
    def _unwrap(cls, values: Any) -> Any:
        if isinstance(values, dict) and "Data" in values:
            return values["Data"]
        return values

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return {"Data": super().model_dump(**kwargs)}


class SiteRow(TableRowBase, ScopedModel, projection_bases=(TableRowBase,)):
    id: Annotated[UUID, scoped(Public)]
    url: Annotated[str, scoped(Public)]
    api_key: Annotated[str, scoped(Storage)]


def demo() -> None:
    row = SiteRow(id=uuid4(), url="https://example.com", api_key="secret")
    print(f"canonical dump (enveloped): {row.model_dump()}")

    SitePublic = SiteRow.scope(Public)
    public = SitePublic.from_canonical(row)  # envelope handled automatically
    print(f"projection is a TableRowBase: {isinstance(public, TableRowBase)}")
    print(f"projection dump (still enveloped): {public.model_dump()}")
    print(f"api_key leaked: {'api_key' in type(public).model_fields}")

    # per-call override: a projection without the base, for plain JSON shapes
    SiteFlat = SiteRow.scope(Public, bases=(), name="SitePublicFlat")
    flat = SiteFlat(id=row.id, url=row.url)
    print(f"flat projection dump: {flat.model_dump()}")


if __name__ == "__main__":
    demo()
