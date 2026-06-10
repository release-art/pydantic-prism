"""Partial scopes: the all-fields-optional Update model.

Run from the repository root:

    pdm run python examples/partial_update/main.py

Shows: a ``partial=True`` scope turning the canonical row into a PATCH-style
Update model — every field optional, ``None`` defaults, canonical defaults
dropped (absent means "don't touch"), JSON schema with nothing required.
"""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from pydantic_prism import Scope, ScopedModel, scoped


class Public(Scope): ...


class Storage(Public): ...


class Update(Storage, partial=True): ...


class SiteRow(ScopedModel):
    id: Annotated[UUID, scoped(Public), Field(description="Row identifier.")]
    url: Annotated[str, scoped(Public), Field(description="Site URL.")]
    status: Annotated[
        str, scoped(Storage), Field(description="Lifecycle status (storage-only).")
    ] = "active"
    api_key: Annotated[
        str, scoped(Storage), Field(description="Secret API key (storage-only).")
    ]


def demo() -> None:
    SiteUpdate = SiteRow.scope(Update)

    empty = SiteUpdate()  # valid: every field defaults to None
    print(f"empty update dumps to: {empty.model_dump(exclude_none=True)}")

    patch = SiteUpdate(url="https://example.org")
    print(f"sparse update: {patch.model_dump(exclude_none=True)}")

    schema = SiteUpdate.model_json_schema()
    print(f"schema requires: {schema.get('required', 'nothing')}")

    # round trip from a full row: every field present, including defaults
    row = SiteRow(id=uuid4(), url="https://example.org", api_key="k")
    full = SiteUpdate.from_canonical(row)
    print(f"from_canonical: {full.model_dump(exclude_none=True)}")

    # mixing a partial scope with a regular one yields a regular projection
    mixed = SiteRow.scope(Update | Public, name="SiteUpdateOrPublic")
    print(f"mixed expression partial: {mixed.model_fields['url'].default is None}")


if __name__ == "__main__":
    demo()
