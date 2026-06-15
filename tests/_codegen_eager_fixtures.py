"""A model deliberately WITHOUT ``from __future__ import annotations``.

On Python 3.14 such a class carries a PEP-649 ``__annotate_func__`` callable in
its ``__dict__`` — the exact regression vector for the codegen dunder leak (a
model that *does* stringize annotations via the future import never grows the
attribute, so it would not reproduce the bug).
"""

from typing import Annotated

from pydantic_prism import Scope, ScopedModel, scoped


class Eager(Scope): ...


class Widget(ScopedModel):
    name: Annotated[str, scoped(Eager)]

    def shout(self) -> str:
        return self.name.upper()
