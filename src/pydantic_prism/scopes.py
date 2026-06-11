"""Public scope vocabulary — the bundled scope taxonomy prism ships.

The :class:`Scope` base and the scope-expression algebra
(:class:`ScopeExpr`, the ``| & - ~`` operators) live in the internal module and
are re-exported here for convenience; the bundled *axis* taxonomy is defined
here, its public home:

* :class:`Classification` — the data-classification axis (`Pii`, `Secret`, …),
  an open taxonomy you extend.
* :class:`Direction` with the two members :class:`In` / :class:`Out` — the
  read/write axis, a closed binary prism ships whole.

Both are ordinary :class:`Scope` subclasses (a distinct base per axis is all
that distinguishes them), so they compose in the same algebra and tag fields
through the same ``scoped(...)`` marker. Import them from the package root
(``from pydantic_prism import Classification``) or from here.
"""

from __future__ import annotations

from ._internal.scopes import Scope, ScopeExpr

__all__ = ["Classification", "Direction", "In", "Out", "Scope", "ScopeExpr"]


class Classification(Scope):
    """Base for data-classification tags — an axis orthogonal to visibility.

    A classification *is* a :class:`Scope`: it composes in the same expression
    algebra (``Internal - Pii``), tags fields through the same ``scoped(...)``
    marker, and is selected by the same ``matches`` / ``selects`` rules. The
    distinct base is what lets prism tell the two axes apart — enumerate a
    model's classifications (:meth:`ScopedModel.classifications`), auto-derive
    audit-safe views (:meth:`ScopedModel.redacted`), and trace where classified
    data flows (:meth:`ScopedModel.data_flow`).

    Declare concrete tags by subclassing::

        class Pii(Classification): ...
        class Secret(Classification): ...

    prism ships only this base, not a fixed taxonomy — name the classes that fit
    your compliance regime. Because a classification is an ordinary scope, it may
    still be requested directly (``Model.scope(Pii)`` is "every PII field"); the
    governance helpers above are the ergonomic path that keeps the two axes
    explicit.
    """


class Direction(Scope):
    """Base for the read/write *direction* axis — orthogonal to visibility.

    A field's direction says which side of the API it travels on, independent of
    *who* may see it (the visibility ladder ``Public < Internal < ...``). prism
    ships the whole axis, since — unlike :class:`Classification` (an open
    taxonomy) — direction is a closed binary: there are only ever the two members
    :class:`In` and :class:`Out`. A :class:`Direction` *is* a :class:`Scope`, so
    it composes in the same expression algebra and tags through the same
    ``scoped(...)`` marker; the distinct base is what lets prism tell the
    direction axis apart from visibility and drive
    :meth:`~pydantic_prism.ScopedModel.input` / ``output``.

    You annotate only the *exceptions* — a read-only field with :class:`Out`, a
    write-only field with :class:`In`; the read-write majority carries no
    direction tag at all (the DRF / Marshmallow model).
    """


class In(Direction, cls_name_token="WriteOnly"):
    """Write-only direction: a field accepted as **input** but never echoed back.

    Tag a write-only field by unioning :class:`In` onto its visibility scope —
    ``scoped(Public, In)`` — exactly as a classification is unioned on. The field
    then survives :meth:`~pydantic_prism.ScopedModel.input` (and a plain
    :meth:`~pydantic_prism.ScopedModel.scope`) but is dropped from
    :meth:`~pydantic_prism.ScopedModel.output`. Passwords are the canonical case.

    The ``cls_name_token="WriteOnly"`` keyword frees the ``...In`` auto-name for
    the ``input()`` helper: a direct ``Model.scope(In)`` is named
    ``{Model}WriteOnly``.
    """


class Out(Direction, cls_name_token="ReadOnly"):
    """Read-only direction: a field returned as **output** but never accepted in.

    Tag a read-only field by unioning :class:`Out` onto its visibility scope —
    ``scoped(Public, Out)``. The field survives
    :meth:`~pydantic_prism.ScopedModel.output` (and a plain
    :meth:`~pydantic_prism.ScopedModel.scope`) but is dropped from
    :meth:`~pydantic_prism.ScopedModel.input`, so it can never be mass-assigned.
    Server-controlled ``id`` / ``created_at`` are the canonical cases.

    The ``cls_name_token="ReadOnly"`` keyword frees the ``...Out`` auto-name for
    the ``output()`` helper: a direct ``Model.scope(Out)`` is named
    ``{Model}ReadOnly``.
    """
